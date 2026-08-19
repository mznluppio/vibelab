"""
Base Cache Manager

Pre-installs marketplace bases with dependencies on startup.
Solves WSL slowness by installing in Linux, then copying to user projects.
"""

import asyncio
import json
import logging
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse
from uuid import uuid4

import docker
from sqlalchemy import select

from ..config import get_settings
from ..database import AsyncSessionLocal
from ..models import MarketplaceBase

logger = logging.getLogger(__name__)


CACHE_METADATA_FILENAME = ".vibelab-base-cache.json"
CACHE_METADATA_SCHEMA_VERSION = 2
REMOTE_HEAD_CACHE_SECONDS = 300


def _node_install_command(directory: Path) -> str:
    """Return the lockfile-aligned Node.js install command for a base.

    Cached ``node_modules`` is copied into a project in Docker mode.  It must
    therefore be created by the same package manager the project will use at
    runtime; mixing npm and pnpm makes pnpm try to purge ``node_modules`` and
    abort when the dev container has no TTY.
    """
    if (directory / "bun.lock").exists() or (directory / "bun.lockb").exists():
        return "bun install --frozen-lockfile"
    if (directory / "pnpm-lock.yaml").exists():
        return "pnpm install --frozen-lockfile --config.dangerouslyAllowAllBuilds=true"
    if (directory / "yarn.lock").exists():
        return "yarn install --frozen-lockfile"
    if (directory / "package-lock.json").exists():
        return "npm ci --unsafe-perm"
    return "npm install --unsafe-perm"


class BaseCacheManager:
    """Manages pre-installed marketplace base cache (Docker mode only)."""

    def __init__(self, cache_dir: str = "/app/base-cache"):
        self.cache_dir = Path(cache_dir)
        # Use Docker volume name for mounting to dev containers
        self.cache_volume_name = get_settings().base_cache_volume_name
        self._initialized = False
        self._docker_client: docker.DockerClient | None = None
        self.dev_server_image = "tesslate-devserver:latest"
        self._remote_heads: dict[tuple[str, str], tuple[str | None, float]] = {}
        self._refreshing_base_ids: set[str] = set()

    @property
    def docker_client(self) -> "docker.DockerClient":
        """Lazy-initialize Docker client only when needed (Docker mode only)."""
        if self._docker_client is None:
            import docker

            self._docker_client = docker.from_env()
        return self._docker_client

    def _is_docker_mode(self) -> bool:
        """Check if running in Docker mode."""
        settings = get_settings()
        return settings.deployment_mode == "docker"

    async def initialize_cache(self) -> None:
        """
        Initialize base cache on startup.
        Clones and installs all marketplace bases if not already cached.

        Only runs in Docker mode - K8s mode uses S3 for file storage.
        """
        if self._initialized:
            logger.info("[BASE-CACHE] Already initialized, skipping")
            return

        # Skip cache initialization in K8s mode - no Docker socket available
        if not self._is_docker_mode():
            logger.info("[BASE-CACHE] Skipping cache initialization (Kubernetes mode)")
            self._initialized = True
            return

        logger.info("[BASE-CACHE] Initializing marketplace base cache...")

        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        async with AsyncSessionLocal() as db:
            # Get all active marketplace bases
            result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.is_active))
            bases = result.scalars().all()

            if not bases:
                logger.warning("[BASE-CACHE] No marketplace bases found in database")
                self._initialized = True
                return

            logger.info(f"[BASE-CACHE] Found {len(bases)} marketplace bases")

            # Process each base
            for base in bases:
                await self._process_base(base)

        self._initialized = True
        logger.info("[BASE-CACHE] ✅ Base cache initialization complete!")

    async def _process_base(self, base: MarketplaceBase) -> None:
        """
        Process a single marketplace base: clone and install dependencies.

        Args:
            base: MarketplaceBase model instance
        """
        base_path = self.cache_dir / base.slug

        remote_commit = await self._get_remote_commit(base)
        if self._is_valid_cache(base_path) and self._cache_matches_base(
            base_path, base, remote_commit=remote_commit
        ):
            logger.info(f"[BASE-CACHE] ✓ {base.name} already cached at {base_path}")
            return

        if base_path.exists():
            logger.info(
                "[BASE-CACHE] Refreshing %s because its cached source no longer matches",
                base.name,
            )

        logger.info(f"[BASE-CACHE] 📦 Caching {base.name}...")
        staging_path = self.cache_dir / f".{base.slug}.staging-{uuid4().hex}"

        try:
            # Build the replacement away from readers. The existing cache stays
            # available until the new clone and dependency installation succeed.
            await self._clone_repository(base.git_repo_url, base.default_branch, staging_path)

            await self._install_dependencies(staging_path, base.name)
            self._write_cache_metadata(
                staging_path,
                base,
                commit_sha=await self._get_checked_out_commit(staging_path),
            )
            await asyncio.to_thread(self._publish_cache, staging_path, base_path)

            logger.info(f"[BASE-CACHE] ✅ {base.name} cached successfully!")

        except Exception as e:
            logger.error(f"[BASE-CACHE] ❌ Failed to cache {base.name}: {e}", exc_info=True)
            # Never delete a previously usable cache because a refresh failed.
            if staging_path.exists():
                await asyncio.to_thread(shutil.rmtree, staging_path, ignore_errors=True)

    @staticmethod
    def _is_valid_cache(base_path: Path) -> bool:
        """Return whether a cache directory has a recognizable project root."""
        return base_path.is_dir() and any(
            (base_path / filename).exists()
            for filename in ("package.json", "requirements.txt", "go.mod")
        )

    @staticmethod
    def _metadata_path(base_path: Path) -> Path:
        return base_path / CACHE_METADATA_FILENAME

    def _cache_matches_base(
        self,
        base_path: Path,
        base: MarketplaceBase,
        *,
        remote_commit: str | None = None,
    ) -> bool:
        """Check cache provenance without ever serving a stale source."""
        try:
            metadata = json.loads(self._metadata_path(base_path).read_text())
        except (OSError, json.JSONDecodeError):
            return False

        matches_identity = (
            metadata.get("schema_version") == CACHE_METADATA_SCHEMA_VERSION
            and metadata.get("base_id") == str(base.id)
            and metadata.get("git_repo_url") == base.git_repo_url
            and metadata.get("default_branch") == (base.default_branch or "main")
        )
        # A failed remote lookup must not turn a healthy cached base into an
        # outage. When Git is reachable, however, never serve a cache from a
        # previous commit of the configured branch.
        return matches_identity and (
            remote_commit is None or metadata.get("commit_sha") == remote_commit
        )

    def _write_cache_metadata(
        self, base_path: Path, base: MarketplaceBase, *, commit_sha: str | None
    ) -> None:
        """Write the provenance manifest before atomically publishing a cache."""
        metadata = {
            "schema_version": CACHE_METADATA_SCHEMA_VERSION,
            "base_id": str(base.id),
            # Marketplace bases store canonical token-free URLs. Do not write
            # runtime clone credentials to the durable cache manifest.
            "git_repo_url": base.git_repo_url,
            "default_branch": base.default_branch or "main",
            "commit_sha": commit_sha,
            "built_at": datetime.now(UTC).isoformat(),
        }
        self._metadata_path(base_path).write_text(json.dumps(metadata, indent=2) + "\n")

    async def _get_checked_out_commit(self, directory: Path) -> str | None:
        """Read the exact revision staged in a freshly cloned cache."""
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(directory),
            "rev-parse",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return None
        commit = stdout.decode().strip()
        return commit if commit else None

    async def _get_remote_commit(self, base: MarketplaceBase) -> str | None:
        """Return the branch head with a bounded, shared freshness lookup."""
        branch = base.default_branch or "main"
        key = (base.git_repo_url, branch)
        now = time.monotonic()
        cached = self._remote_heads.get(key)
        if cached and now - cached[1] < REMOTE_HEAD_CACHE_SECONDS:
            return cached[0]

        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "ls-remote",
                "--exit-code",
                self._get_cache_clone_url(base.git_repo_url),
                f"refs/heads/{branch}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            commit = stdout.decode().split(maxsplit=1)[0] if process.returncode == 0 else None
            if commit and len(commit) != 40:
                commit = None
        except (OSError, asyncio.TimeoutError):
            commit = None
        self._remote_heads[key] = (commit, now)
        return commit

    def _refresh_cache_in_background(self, base: MarketplaceBase) -> None:
        """Warm a newer cache without delaying the project creation fallback."""
        base_id = str(base.id)
        if base_id in self._refreshing_base_ids:
            return
        self._refreshing_base_ids.add(base_id)

        async def refresh() -> None:
            try:
                await self._process_base(base)
            finally:
                self._refreshing_base_ids.discard(base_id)

        asyncio.create_task(refresh())

    @staticmethod
    def _publish_cache(staging_path: Path, base_path: Path) -> None:
        """Atomically replace a cache only after its staged build is complete."""
        backup_path = base_path.parent / f".{base_path.name}.backup-{uuid4().hex}"
        had_previous_cache = base_path.exists()

        try:
            if had_previous_cache:
                os.replace(base_path, backup_path)
            os.replace(staging_path, base_path)
        except Exception:
            if had_previous_cache and backup_path.exists() and not base_path.exists():
                os.replace(backup_path, base_path)
            raise
        else:
            if backup_path.exists():
                shutil.rmtree(backup_path, ignore_errors=True)

    async def _clone_repository(self, repo_url: str, branch: str, destination: Path) -> None:
        """
        Clone a git repository.

        Args:
            repo_url: Git repository URL
            branch: Branch to clone
            destination: Destination path
        """
        logger.info(f"[BASE-CACHE]   Cloning {repo_url} (branch: {branch})...")
        clone_url = self._get_cache_clone_url(repo_url)

        # Use git clone with depth=1 for faster cloning
        process = await asyncio.create_subprocess_exec(
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            branch,
            "--single-branch",
            clone_url,
            str(destination),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Git clone failed: {error_msg}")

        logger.info("[BASE-CACHE]   ✓ Clone complete")

    @staticmethod
    def _get_cache_clone_url(repo_url: str) -> str:
        """Return an ephemeral authenticated URL for a managed private base.

        Marketplace metadata and logs always retain the clean repository URL.
        The token is scoped to cache warm-up, read from deployment configuration,
        and passed only to the ``git`` subprocess.
        """
        token = get_settings().base_cache_git_token
        if not token:
            return repo_url

        parsed = urlparse(repo_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname != "github.com":
            return repo_url

        port = f":{parsed.port}" if parsed.port else ""
        netloc = f"x-access-token:{quote(token, safe='')}@{parsed.hostname}{port}"
        return urlunparse(parsed._replace(netloc=netloc))

    async def _install_dependencies(self, base_path: Path, base_name: str) -> None:
        """
        Install dependencies for all languages found in the base.

        Args:
            base_path: Path to the cloned base
            base_name: Name of the base (for logging)
        """
        logger.info(f"[BASE-CACHE]   Installing dependencies for {base_name}...")

        # Check for multi-container structure (frontend/backend)
        has_frontend = (base_path / "frontend").exists()
        has_backend = (base_path / "backend").exists()

        if has_frontend or has_backend:
            # Multi-container base
            if has_frontend:
                await self._install_in_directory(base_path / "frontend", "Frontend")
            if has_backend:
                await self._install_in_directory(base_path / "backend", "Backend")
        else:
            # Single-container base
            await self._install_in_directory(base_path, base_name)

    async def _install_in_directory(self, directory: Path, label: str) -> None:
        """
        Install dependencies in a specific directory using a dev server container.

        Args:
            directory: Directory to install in
            label: Label for logging
        """
        # Detect which package managers are needed
        has_nodejs = (directory / "package.json").exists()
        has_python = (directory / "requirements.txt").exists()
        has_go = (directory / "go.mod").exists()

        if not (has_nodejs or has_python or has_go):
            logger.info(f"[BASE-CACHE]     No dependencies to install ({label})")
            return

        # Build install command
        commands = []

        if has_nodejs:
            logger.info(f"[BASE-CACHE]     Installing Node.js deps ({label})...")
            commands.append(_node_install_command(directory))

        if has_python:
            logger.info(f"[BASE-CACHE]     Installing Python deps ({label})...")
            commands.extend(
                [
                    "python3 -m venv .venv",
                    ".venv/bin/pip install --upgrade pip",
                    ".venv/bin/pip install -r requirements.txt",
                ]
            )

        if has_go:
            logger.info(f"[BASE-CACHE]     Downloading Go modules ({label})...")
            commands.append("go mod download")

        # Run installs in a temporary dev server container
        await self._run_in_container(directory, commands, label)

    async def _run_in_container(self, directory: Path, commands: list[str], label: str) -> None:
        """
        Run commands in a temporary dev server container.

        Args:
            directory: Directory to mount
            commands: List of commands to run
            label: Label for logging
        """
        try:
            # Get the path inside the volume to mount
            # directory is like /app/base-cache/nextjs-16
            # We want to mount just that subdirectory from the volume
            relative_path = directory.relative_to(self.cache_dir)

            logger.info(
                f"[BASE-CACHE]     Mounting volume: {self.cache_volume_name}/{relative_path}"
            )

            # Run container and wait for completion
            # Note: Must override USER directive in devserver image (USER 1000) to run as root
            # User projects will copy these files and run as user 1000:1000
            result = await asyncio.to_thread(
                self.docker_client.containers.run,
                image=self.dev_server_image,
                command=["sh", "-c", " && ".join(commands)],
                volumes={self.cache_volume_name: {"bind": "/cache", "mode": "rw"}},
                working_dir=f"/cache/{relative_path}",
                user="root",  # Override USER 1000 from Dockerfile
                detach=False,  # Wait for completion
                remove=True,  # Auto-cleanup after completion
                stdout=True,
                stderr=True,
            )

            # Result contains combined stdout/stderr
            logs_str = result.decode("utf-8", errors="replace")
            logger.info(f"[BASE-CACHE]     ✓ Install complete ({label})")
            logger.debug(f"[BASE-CACHE]     Logs:\n{logs_str}")

        except docker.errors.ContainerError as e:
            error_msg = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
            logger.warning(f"[BASE-CACHE]     ⚠ Install failed ({label}): {error_msg[:500]}")

        except Exception as e:
            logger.error(f"[BASE-CACHE]     ❌ Container execution failed ({label}): {e}")

    async def get_base_path(
        self,
        base_slug: str,
        *,
        expected_base: MarketplaceBase | None = None,
    ) -> Path | None:
        """
        Get the cached path for a marketplace base.

        Args:
            base_slug: Slug of the marketplace base.
            expected_base: When supplied, require the cache provenance to
                match its current repository URL and branch. This prevents a
                stale slug-only entry from being copied into a new project.

        Returns:
            Path to cached base, or None if not found (always None in K8s mode)
        """
        # In K8s mode, cache is not used - files come from S3
        if not self._is_docker_mode():
            return None

        base_path = self.cache_dir / base_slug
        remote_commit = (
            await self._get_remote_commit(expected_base) if expected_base is not None else None
        )
        if self._is_valid_cache(base_path) and (
            expected_base is None
            or self._cache_matches_base(base_path, expected_base, remote_commit=remote_commit)
        ):
            return base_path
        if expected_base is not None:
            self._refresh_cache_in_background(expected_base)
        return None

    def is_base_cached(self, base_slug: str) -> bool:
        """
        Check if a base is already cached.

        Args:
            base_slug: Slug of the marketplace base

        Returns:
            True if cached, False otherwise (always False in K8s mode)
        """
        # In K8s mode, cache is not used - files come from S3
        if not self._is_docker_mode():
            return False

        base_path = self.cache_dir / base_slug
        return base_path.exists()


# Singleton instance
_base_cache_manager: BaseCacheManager | None = None


def get_base_cache_manager() -> BaseCacheManager:
    """Get the singleton base cache manager instance."""
    global _base_cache_manager

    if _base_cache_manager is None:
        _base_cache_manager = BaseCacheManager()

    return _base_cache_manager

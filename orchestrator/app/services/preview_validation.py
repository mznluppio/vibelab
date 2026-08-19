"""Deterministic post-preview validation for generated web applications.

The agent process cannot reliably execute a project's frontend checks before
the preview container exists. This service runs a template-declared UI check
only after the same container is reachable through the public preview route.
It deliberately skips projects without such a check so non-web and custom
bases retain their existing lifecycle.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID


@dataclass(frozen=True)
class PreviewValidationResult:
    """Outcome of one optional, template-declared preview validation."""

    status: Literal["passed", "failed", "skipped"]
    command: str | None = None
    output: str | None = None


def _package_script_command(script: str) -> list[str]:
    """Return a package-manager-neutral command for one declared script."""
    return [
        "sh",
        "-lc",
        f"if command -v bun >/dev/null 2>&1; then bun run {script}; "
        f"elif command -v pnpm >/dev/null 2>&1; then pnpm run {script}; "
        f"elif command -v yarn >/dev/null 2>&1; then yarn run {script}; "
        f"else npm run {script}; fi",
    ]


_UI_CHECK_COMMAND = _package_script_command("check:ui")


def _has_declared_script(package_content: str | None, script: str) -> bool:
    """Return whether a package manifest explicitly declares ``script``."""
    if not package_content:
        return False
    try:
        package = json.loads(package_content)
    except (TypeError, json.JSONDecodeError):
        return False
    scripts = package.get("scripts") if isinstance(package, dict) else None
    return isinstance(scripts, dict) and isinstance(scripts.get(script), str)


async def _run_declared_check(
    orchestrator: Any,
    *,
    user_id: UUID,
    project_id: UUID,
    project_slug: str,
    container_name: str,
    script: str,
    command: list[str],
    timeout: int,
) -> PreviewValidationResult:
    """Run one opt-in package script in an already started project container."""
    package_content = await orchestrator.read_file(
        user_id=user_id,
        project_id=project_id,
        container_name=container_name,
        file_path="package.json",
        project_slug=project_slug,
    )
    if not _has_declared_script(package_content, script):
        return PreviewValidationResult(status="skipped")

    try:
        output = await asyncio.wait_for(
            orchestrator.execute_command(
                user_id=user_id,
                project_id=project_id,
                container_name=container_name,
                command=command,
                timeout=timeout,
            ),
            timeout=timeout + 5,
        )
    except Exception as exc:
        return PreviewValidationResult(
            status="failed",
            command=script,
            output=str(exc)[:4000],
        )

    return PreviewValidationResult(
        status="passed",
        command=script,
        output=output[-4000:] if output else None,
    )


async def run_preview_preflight(
    orchestrator: Any,
    *,
    user_id: UUID,
    project_id: UUID,
    project_slug: str,
    container_name: str,
) -> PreviewValidationResult:
    """Run a template-declared production build before advertising a preview.

    A healthy container only proves that the process started.  For web apps a
    dev server can stay alive while every route returns a compiler error, so a
    package's explicit ``build`` script is the opt-in contract for a usable
    preview. UI-contract checks stay separate: they are reported after a
    healthy preview exists, but must not hide a working app from its user.
    We do not infer a command for custom bases: projects without the script
    retain their existing lifecycle and simply return ``skipped``.
    """
    return await _run_declared_check(
        orchestrator,
        user_id=user_id,
        project_id=project_id,
        project_slug=project_slug,
        container_name=container_name,
        script="build",
        command=_package_script_command("build"),
        timeout=90,
    )


async def run_preview_validation(
    orchestrator: Any,
    *,
    user_id: UUID,
    project_id: UUID,
    project_slug: str,
    container_name: str,
) -> PreviewValidationResult:
    """Run a project UI check in its already-running preview container.

    The command is selected by executables available inside the isolated
    project container. This avoids assuming Bun in Kubernetes or custom
    templates while retaining the same behaviour across orchestrators.
    """
    return await _run_declared_check(
        orchestrator,
        user_id=user_id,
        project_id=project_id,
        project_slug=project_slug,
        container_name=container_name,
        script="check:ui",
        command=_UI_CHECK_COMMAND,
        timeout=90,
    )

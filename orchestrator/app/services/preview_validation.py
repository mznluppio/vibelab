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


_UI_CHECK_COMMAND = [
    "sh",
    "-lc",
    "if command -v bun >/dev/null 2>&1; then bun run check:ui; "
    "elif command -v pnpm >/dev/null 2>&1; then pnpm run check:ui; "
    "elif command -v yarn >/dev/null 2>&1; then yarn run check:ui; "
    "else npm run check:ui; fi",
]


def _has_ui_check(package_content: str | None) -> bool:
    """Return whether a package manifest explicitly declares ``check:ui``."""
    if not package_content:
        return False
    try:
        package = json.loads(package_content)
    except (TypeError, json.JSONDecodeError):
        return False
    scripts = package.get("scripts") if isinstance(package, dict) else None
    return isinstance(scripts, dict) and isinstance(scripts.get("check:ui"), str)


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
    package_content = await orchestrator.read_file(
        user_id=user_id,
        project_id=project_id,
        container_name=container_name,
        file_path="package.json",
        project_slug=project_slug,
    )
    if not _has_ui_check(package_content):
        return PreviewValidationResult(status="skipped")

    try:
        output = await asyncio.wait_for(
            orchestrator.execute_command(
                user_id=user_id,
                project_id=project_id,
                container_name=container_name,
                command=_UI_CHECK_COMMAND,
                timeout=90,
            ),
            timeout=95,
        )
    except Exception as exc:
        return PreviewValidationResult(
            status="failed",
            command="check:ui",
            output=str(exc)[:4000],
        )

    return PreviewValidationResult(
        status="passed",
        command="check:ui",
        output=output[-4000:] if output else None,
    )

import json
from uuid import uuid4

import pytest

from app.services.preview_validation import run_preview_preflight, run_preview_validation


class _Orchestrator:
    def __init__(self, package: str | None, output: str = "UI contract passed") -> None:
        self.package = package
        self.output = output
        self.commands: list[list[str]] = []

    async def read_file(self, **_kwargs):
        return self.package

    async def execute_command(self, **kwargs):
        self.commands.append(kwargs["command"])
        return self.output


@pytest.mark.asyncio
async def test_runs_declared_ui_check_in_preview_container() -> None:
    orchestrator = _Orchestrator(json.dumps({"scripts": {"check:ui": "node check.mjs"}}))

    result = await run_preview_validation(
        orchestrator,
        user_id=uuid4(),
        project_id=uuid4(),
        project_slug="sample-app",
        container_name="frontend",
    )

    assert result.status == "passed"
    assert result.command == "check:ui"
    assert orchestrator.commands == [[
        "sh",
        "-lc",
        "if command -v bun >/dev/null 2>&1; then bun run check:ui; "
        "elif command -v pnpm >/dev/null 2>&1; then pnpm run check:ui; "
        "elif command -v yarn >/dev/null 2>&1; then yarn run check:ui; "
        "else npm run check:ui; fi",
    ]]


@pytest.mark.asyncio
async def test_runs_declared_production_build_before_preview_is_advertised() -> None:
    orchestrator = _Orchestrator(json.dumps({"scripts": {"build": "next build"}}))

    result = await run_preview_preflight(
        orchestrator,
        user_id=uuid4(),
        project_id=uuid4(),
        project_slug="sample-app",
        container_name="frontend",
    )

    assert result.status == "passed"
    assert result.command == "build"
    assert orchestrator.commands == [[
        "sh",
        "-lc",
        "if command -v bun >/dev/null 2>&1; then bun run build; "
        "elif command -v pnpm >/dev/null 2>&1; then pnpm run build; "
        "elif command -v yarn >/dev/null 2>&1; then yarn run build; "
        "else npm run build; fi",
    ]]


@pytest.mark.asyncio
async def test_skips_preflight_when_the_base_has_not_opted_in() -> None:
    orchestrator = _Orchestrator(json.dumps({"scripts": {"check:ui": "node check.mjs"}}))

    result = await run_preview_preflight(
        orchestrator,
        user_id=uuid4(),
        project_id=uuid4(),
        project_slug="sample-app",
        container_name="frontend",
    )

    assert result.status == "skipped"
    assert orchestrator.commands == []


@pytest.mark.asyncio
async def test_skips_projects_without_a_declared_ui_check() -> None:
    orchestrator = _Orchestrator(json.dumps({"scripts": {"build": "next build"}}))

    result = await run_preview_validation(
        orchestrator,
        user_id=uuid4(),
        project_id=uuid4(),
        project_slug="sample-app",
        container_name="frontend",
    )

    assert result.status == "skipped"
    assert orchestrator.commands == []


@pytest.mark.asyncio
async def test_surfaces_a_failed_ui_check_without_raising() -> None:
    class _FailingOrchestrator(_Orchestrator):
        async def execute_command(self, **kwargs):
            await super().execute_command(**kwargs)
            raise RuntimeError("UI contract failed: missing selector")

    orchestrator = _FailingOrchestrator(json.dumps({"scripts": {"check:ui": "node check.mjs"}}))
    result = await run_preview_validation(
        orchestrator,
        user_id=uuid4(),
        project_id=uuid4(),
        project_slug="sample-app",
        container_name="frontend",
    )

    assert result.status == "failed"
    assert "missing selector" in (result.output or "")

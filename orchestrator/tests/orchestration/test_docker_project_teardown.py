"""Regression tests for destructive Docker workspace cleanup."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.orchestration.docker import DockerOrchestrator


class _Process:
    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def _orchestrator(tmp_path: Path, project_path: Path) -> DockerOrchestrator:
    orchestrator = object.__new__(DockerOrchestrator)
    orchestrator.settings = SimpleNamespace(traefik_container_name="tesslate-traefik")
    orchestrator._get_compose_file_path = lambda _slug: str(tmp_path / "missing-compose.yml")
    orchestrator.get_project_path = lambda _slug: project_path
    orchestrator.delete_project_directory = AsyncMock(return_value=True)
    return orchestrator


@pytest.mark.asyncio
async def test_teardown_removes_project_labelled_orphans_and_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    orchestrator = _orchestrator(tmp_path, project_path)
    commands: list[tuple[str, ...]] = []
    responses = iter(
        [
            _Process(stderr=b"container is not connected to network"),
            _Process(stdout=b"orphan-a\norphan-b\n"),
            _Process(),
            _Process(stderr=b"Error response from daemon: No such network"),
        ]
    )

    async def fake_exec(*command, **_kwargs):
        commands.append(command)
        return next(responses)

    monkeypatch.setattr("app.services.orchestration.docker.asyncio.create_subprocess_exec", fake_exec)

    await orchestrator.delete_project_namespace(
        project_id=uuid4(), user_id=uuid4(), project_slug="workspace-abc"
    )

    assert commands == [
        (
            "docker",
            "network",
            "disconnect",
            "-f",
            "tesslate-workspace-abc",
            "tesslate-traefik",
        ),
        (
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.tesslate.project=workspace-abc",
        ),
        ("docker", "rm", "-f", "orphan-a", "orphan-b"),
        ("docker", "network", "rm", "tesslate-workspace-abc"),
    ]
    orchestrator.delete_project_directory.assert_awaited_once_with("workspace-abc")


@pytest.mark.asyncio
async def test_teardown_fails_without_deleting_database_state_when_compose_down_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    compose_file = tmp_path / "workspace-abc.yml"
    compose_file.touch()
    orchestrator = _orchestrator(tmp_path, project_path)
    orchestrator._get_compose_file_path = lambda _slug: str(compose_file)
    responses = iter(
        [
            _Process(stderr=b"container is not connected to network"),
            _Process(returncode=1, stderr=b"network still has active endpoints"),
        ]
    )

    async def fake_exec(*_command, **_kwargs):
        return next(responses)

    monkeypatch.setattr("app.services.orchestration.docker.asyncio.create_subprocess_exec", fake_exec)

    with pytest.raises(RuntimeError, match="Docker Compose teardown failed"):
        await orchestrator.delete_project_namespace(
            project_id=uuid4(), user_id=uuid4(), project_slug="workspace-abc"
        )

    orchestrator.delete_project_directory.assert_not_awaited()

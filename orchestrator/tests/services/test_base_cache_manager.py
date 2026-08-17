"""Regression coverage for source-aware marketplace base caches."""

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest

from app.services.base_cache_manager import BaseCacheManager


def _base(*, url: str = "https://github.com/vibelab/template.git", branch: str = "main"):
    return SimpleNamespace(
        id=uuid4(),
        name="Test base",
        slug="test-base",
        git_repo_url=url,
        default_branch=branch,
    )


def _manager(tmp_path) -> BaseCacheManager:
    manager = BaseCacheManager(cache_dir=str(tmp_path))
    manager._is_docker_mode = lambda: True
    return manager


@pytest.mark.asyncio
async def test_matching_manifest_reuses_a_complete_cache(tmp_path) -> None:
    manager = _manager(tmp_path)
    base = _base()
    cache_path = tmp_path / base.slug
    cache_path.mkdir()
    (cache_path / "package.json").write_text("{}")
    manager._write_cache_metadata(cache_path, base)
    manager._clone_repository = AsyncMock()

    await manager._process_base(base)

    manager._clone_repository.assert_not_awaited()
    assert await manager.get_base_path(base.slug, expected_base=base) == cache_path


@pytest.mark.asyncio
async def test_changed_source_rebuilds_cache_before_publishing(tmp_path) -> None:
    manager = _manager(tmp_path)
    old_base = _base(url="https://github.com/vibelab/old-template.git")
    new_base = SimpleNamespace(
        **{**old_base.__dict__, "git_repo_url": "https://github.com/vibelab/new-template.git"}
    )
    cache_path = tmp_path / old_base.slug
    cache_path.mkdir()
    (cache_path / "package.json").write_text('{"name":"old"}')
    manager._write_cache_metadata(cache_path, old_base)

    async def clone(_url, _branch, destination):
        destination.mkdir()
        (destination / "package.json").write_text('{"name":"new"}')

    manager._clone_repository = AsyncMock(side_effect=clone)
    manager._install_dependencies = AsyncMock()

    assert await manager.get_base_path(new_base.slug, expected_base=new_base) is None
    await manager._process_base(new_base)

    manager._clone_repository.assert_awaited_once_with(
        new_base.git_repo_url, new_base.default_branch, ANY
    )
    assert (cache_path / "package.json").read_text() == '{"name":"new"}'
    assert await manager.get_base_path(new_base.slug, expected_base=new_base) == cache_path


@pytest.mark.asyncio
async def test_failed_refresh_keeps_previous_cache_but_never_serves_it_as_current(tmp_path) -> None:
    manager = _manager(tmp_path)
    old_base = _base(branch="main")
    new_base = SimpleNamespace(**{**old_base.__dict__, "default_branch": "release"})
    cache_path = tmp_path / old_base.slug
    cache_path.mkdir()
    (cache_path / "package.json").write_text('{"name":"old"}')
    manager._write_cache_metadata(cache_path, old_base)
    manager._clone_repository = AsyncMock(side_effect=RuntimeError("clone failed"))

    await manager._process_base(new_base)

    assert (cache_path / "package.json").read_text() == '{"name":"old"}'
    assert await manager.get_base_path(new_base.slug, expected_base=new_base) is None


@pytest.mark.asyncio
async def test_legacy_cache_without_manifest_is_not_served(tmp_path) -> None:
    manager = _manager(tmp_path)
    base = _base()
    cache_path = tmp_path / base.slug
    cache_path.mkdir()
    (cache_path / "package.json").write_text("{}")

    assert await manager.get_base_path(base.slug, expected_base=base) is None

from types import SimpleNamespace

from app.services.base_cache_manager import BaseCacheManager


def test_cache_manifest_requires_the_current_remote_commit(tmp_path):
    """A branch moving forward must not silently serve its old warm cache."""
    manager = BaseCacheManager(cache_dir=str(tmp_path))
    base = SimpleNamespace(
        id="base-id",
        git_repo_url="https://github.com/example/base.git",
        default_branch="main",
    )
    cache_path = tmp_path / "example"
    cache_path.mkdir()
    (cache_path / "package.json").write_text("{}")
    manager._write_cache_metadata(cache_path, base, commit_sha="a" * 40)

    assert manager._cache_matches_base(cache_path, base, remote_commit="a" * 40)
    assert not manager._cache_matches_base(cache_path, base, remote_commit="b" * 40)


def test_cache_remains_available_when_remote_lookup_is_unavailable(tmp_path):
    """Transient Git outages do not prevent project creation from a valid cache."""
    manager = BaseCacheManager(cache_dir=str(tmp_path))
    base = SimpleNamespace(
        id="base-id",
        git_repo_url="https://github.com/example/base.git",
        default_branch="main",
    )
    cache_path = tmp_path / "example"
    cache_path.mkdir()
    (cache_path / "package.json").write_text("{}")
    manager._write_cache_metadata(cache_path, base, commit_sha="a" * 40)

    assert manager._cache_matches_base(cache_path, base, remote_commit=None)


def test_legacy_cache_is_only_accepted_when_git_is_unavailable(tmp_path):
    """The manifest migration preserves availability without hiding new commits."""
    manager = BaseCacheManager(cache_dir=str(tmp_path))
    base = SimpleNamespace(
        id="base-id",
        git_repo_url="https://github.com/example/base.git",
        default_branch="main",
    )
    cache_path = tmp_path / "example"
    cache_path.mkdir()
    (cache_path / "package.json").write_text("{}")
    (cache_path / ".vibelab-base-cache.json").write_text(
        '{"schema_version": 1, "base_id": "base-id", '
        '"git_repo_url": "https://github.com/example/base.git", '
        '"default_branch": "main"}'
    )

    assert manager._cache_matches_base(cache_path, base, remote_commit=None)
    assert not manager._cache_matches_base(cache_path, base, remote_commit="a" * 40)

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

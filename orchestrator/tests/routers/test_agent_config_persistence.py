"""Regression tests for editable agent JSON configuration."""

from app.routers.marketplace import _merge_agent_config
from app.services.marketplace_sync import _merge_local_agent_config_overrides


def test_library_agent_config_merge_returns_fresh_persistable_object() -> None:
    current = {"auto_start_project": True, "features": {"apps": True}}
    required_base = {"id": "base-id", "slug": "nextjs-16", "name": "Next.js 16"}

    merged = _merge_agent_config(
        current,
        {"required_base": required_base, "features": {"library": False}},
        track_local_overrides=True,
    )

    assert merged is not current
    assert "required_base" not in current
    assert merged["required_base"] == required_base
    assert merged["features"] == {"apps": True, "library": False}
    assert merged["_local_overrides"]["required_base"] == required_base


def test_marketplace_sync_preserves_local_required_base_override() -> None:
    local_base = {"slug": "nextjs-16", "name": "Next.js 16"}
    existing = {
        "auto_start_project": True,
        "required_base": local_base,
        "_local_overrides": {"required_base": local_base},
    }

    merged = _merge_local_agent_config_overrides(
        {"auto_start_project": True, "required_base": {"slug": "other"}},
        existing,
    )

    assert merged["required_base"] == local_base
    assert merged["_local_overrides"]["required_base"] == local_base


def test_marketplace_sync_preserves_explicitly_cleared_required_base() -> None:
    merged = _merge_local_agent_config_overrides(
        {"required_base": {"slug": "upstream-default"}},
        {"required_base": None, "_local_overrides": {"required_base": None}},
    )

    assert merged["required_base"] is None

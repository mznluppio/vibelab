"""Regression checks for VibeLab's central LiteLLM runtime defaults."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import Settings


def test_default_models_use_only_stable_central_aliases() -> None:
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/test")

    assert settings.default_models_list == [
        "vibelab-default",
        "vibelab-fast",
        "vibelab-reasoning",
    ]
    assert settings.default_model == "vibelab-default"


@pytest.mark.asyncio
async def test_non_admin_model_catalog_exposes_only_central_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import marketplace

    async def _models() -> list[dict[str, str]]:
        return [
            {"id": "vibelab-default"},
            {"id": "vibelab-fast"},
            {"id": "vibelab-reasoning"},
            {"id": "must-not-be-exposed"},
        ]

    async def _not_an_admin(*_args: object, **_kwargs: object) -> bool:
        return False

    async def _empty_mapping() -> dict[str, object]:
        return {}

    monkeypatch.setattr(marketplace, "_get_cached_litellm_models", _models)
    monkeypatch.setattr(marketplace, "_get_cached_model_pricing", _empty_mapping)
    monkeypatch.setattr(marketplace, "_get_cached_model_health", _empty_mapping)
    monkeypatch.setattr(marketplace, "_get_cached_model_vision_support", _empty_mapping)
    monkeypatch.setattr(marketplace, "_is_active_team_administrator", _not_an_admin)

    user = SimpleNamespace(
        id=uuid4(),
        default_team_id=uuid4(),
        disabled_models=[],
    )
    response = await marketplace.get_available_models(current_user=user, db=object())

    assert [model["id"] for model in response["models"]] == [
        "builtin/vibelab-default",
        "builtin/vibelab-fast",
        "builtin/vibelab-reasoning",
    ]
    assert response["external_providers"] == []
    assert response["user_providers"] == []
    assert response["custom_models"] == []

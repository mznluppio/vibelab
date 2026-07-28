"""Regression checks for VibeLab's central LiteLLM runtime defaults."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def test_compose_uses_non_blocking_litellm_validation() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text()

    assert "validate-litellm-env" in compose
    assert "${AZURE_API_KEY:?" not in compose
    assert "${LITELLM_MASTER_KEY:?" not in compose
    assert "litellm-disabled-server.py" in compose
    assert "LITELLM_TEAM_ID=${LITELLM_TEAM_ID}" not in compose
    assert "litellm-db-bootstrap:" in compose
    assert "CREATE DATABASE litellm" in compose
    assert "@postgres:5432/litellm" in compose


def test_aks_litellm_uses_a_dedicated_database() -> None:
    terraform = (REPO_ROOT / "k8s/terraform/azure/kubernetes.tf").read_text()

    assert "/litellm?sslmode=require" in terraform
    assert "/litellm\"" in terraform
    assert 'name  = "create-database"' in terraform
    assert "CREATE DATABASE litellm" in terraform
    assert "ADMIN_DATABASE_URL" in terraform


def test_litellm_config_keeps_aliases_and_provider_values_in_environment() -> None:
    config = (REPO_ROOT / "k8s/litellm/vibelab-azure-config.yaml").read_text()

    for alias, env_name in (
        ("vibelab-default", "AZURE_AI_DEFAULT_MODEL"),
        ("vibelab-fast", "AZURE_AI_FAST_MODEL"),
        ("vibelab-reasoning", "AZURE_AI_REASONING_MODEL"),
    ):
        assert f"model_name: {alias}" in config
        assert f'os.environ/{env_name}' in config

    assert "os.environ/AZURE_API_KEY" in config
    assert "your-azure" not in config


def test_aks_litellm_is_network_isolated_but_reachable_by_server_processes() -> None:
    policy = (REPO_ROOT / "k8s/base/security/network-policies.yaml").read_text()

    assert "name: allow-litellm-from-platform" in policy
    assert "name: allow-litellm-egress" in policy
    assert "- tesslate-backend" in policy
    assert "- tesslate-worker" in policy
    assert "- tesslate-gateway" in policy
    assert "port: 4000" in policy


def test_fuzzy_repair_defaults_to_the_central_litellm_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.tools.file_ops.fuzzy_editor import _default_repair_model_name

    monkeypatch.delenv("TESSLATE_REPAIR_MODEL", raising=False)
    monkeypatch.delenv("COMPACTION_SUMMARY_MODEL", raising=False)
    monkeypatch.setenv("LITELLM_DEFAULT_MODELS", "vibelab-fast,vibelab-default")

    assert _default_repair_model_name() == "vibelab-fast"

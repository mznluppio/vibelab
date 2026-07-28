"""Regression tests for the local non-Azure environment bootstrapper."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "setup-local-env.py"
EXAMPLE = REPO_ROOT / ".env.example"
AZURE_NAMES = (
    "AZURE_API_BASE",
    "AZURE_API_KEY",
    "AZURE_API_VERSION",
    "AZURE_AI_DEFAULT_DEPLOYMENT",
    "AZURE_AI_FAST_DEPLOYMENT",
    "AZURE_AI_REASONING_DEPLOYMENT",
)


def _parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    return values


def _setup(env_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--env", str(env_path), "--example", str(EXAMPLE)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_setup_creates_url_consistent_local_values_and_leaves_only_azure(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    result = _setup(env_path)
    values = _parse(env_path)

    assert "Local environment is ready." in result.stdout
    assert "Configured local values preserved:" in result.stdout
    assert all(name in result.stdout for name in AZURE_NAMES)
    assert values["SECRET_KEY"] != "your-secret-key-here-change-this-in-production"
    assert len(values["INTERNAL_API_SECRET"]) >= 64
    assert values["LITELLM_MASTER_KEY"].startswith("sk-")
    assert values["MARKETPLACE_STATIC_TOKENS"].endswith(
        ":admin.write:catalog.write:publish:submissions.read:submissions.write:"
        "yanks.write:yanks.appeal:reviews.write:telemetry.write"
    )
    assert values["DATABASE_URL"] == (
        f"postgresql+asyncpg://{values['POSTGRES_USER']}:{values['POSTGRES_PASSWORD']}"
        f"@postgres:5432/{values['POSTGRES_DB']}"
    )
    assert env_path.stat().st_mode & 0o777 == 0o600


def test_setup_is_idempotent_and_preserves_existing_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    _setup(env_path)
    before = _parse(env_path)
    _setup(env_path)

    assert _parse(env_path) == before


def test_setup_preserves_an_intentional_external_database_url(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "SECRET_KEY=already-real\nDATABASE_URL=postgresql+asyncpg://user:pass@db.example/test\n"
    )

    _setup(env_path)
    values = _parse(env_path)

    assert values["SECRET_KEY"] == "already-real"
    assert values["DATABASE_URL"] == "postgresql+asyncpg://user:pass@db.example/test"
    assert all(name in values for name in AZURE_NAMES)


def test_setup_repairs_an_invalid_orphaned_secret_value(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("LITELLM_MASTER_KEY=\norphaned-value\n")

    _setup(env_path)

    lines = env_path.read_text().splitlines()
    assert all(line != "orphaned-value" for line in lines)
    assert _parse(env_path)["LITELLM_MASTER_KEY"].startswith("sk-")


def test_azure_validator_rejects_example_placeholders_without_printing_values() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "AZURE_API_BASE": "https://your-resource.openai.azure.com",
            "AZURE_API_KEY": "your-azure-ai-api-key",
            "AZURE_API_VERSION": "2024-12-01-preview",
            "AZURE_AI_DEFAULT_DEPLOYMENT": "your-default-deployment",
            "AZURE_AI_FAST_DEPLOYMENT": "your-fast-deployment",
            "AZURE_AI_REASONING_DEPLOYMENT": "your-reasoning-deployment",
        }
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--validate-azure"],
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert all(name in result.stdout for name in AZURE_NAMES)
    assert "your-azure-ai-api-key" not in result.stdout


def test_runtime_validator_accepts_compose_provider_prefixed_models() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "LITELLM_MASTER_KEY": "sk-local-test-key",
            "AZURE_API_BASE": "https://example.openai.azure.com",
            "AZURE_API_KEY": "azure-test-key",
            "AZURE_API_VERSION": "operator-selected-version",
            "AZURE_AI_DEFAULT_MODEL": "azure/default-deployment",
            "AZURE_AI_FAST_MODEL": "azure/fast-deployment",
            "AZURE_AI_REASONING_MODEL": "azure/reasoning-deployment",
        }
    )
    for name in (
        "AZURE_AI_DEFAULT_DEPLOYMENT",
        "AZURE_AI_FAST_DEPLOYMENT",
        "AZURE_AI_REASONING_DEPLOYMENT",
    ):
        environment.pop(name, None)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--validate-azure"],
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "LiteLLM runtime configuration is complete."

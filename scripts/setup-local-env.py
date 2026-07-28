#!/usr/bin/env python3
"""Create or complete the ignored local Docker environment safely.

Only Azure AI Foundry inputs are intentionally left for an operator.  The
script is safe to re-run: existing non-placeholder values are never replaced,
and it never prints secret values.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit


REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
SENSITIVE_LOCAL_VARIABLES = (
    "SECRET_KEY",
    "INTERNAL_API_SECRET",
    "POSTGRES_PASSWORD",
    "MARKETPLACE_POSTGRES_PASSWORD",
    "LITELLM_MASTER_KEY",
    "MARKETPLACE_STATIC_TOKENS",
)
AZURE_VARIABLES = (
    "AZURE_API_BASE",
    "AZURE_API_KEY",
    "AZURE_API_VERSION",
    "AZURE_AI_DEFAULT_DEPLOYMENT",
    "AZURE_AI_FAST_DEPLOYMENT",
    "AZURE_AI_REASONING_DEPLOYMENT",
)
MARKETPLACE_SCOPES = (
    "admin.write:catalog.write:publish:submissions.read:submissions.write:"
    "yanks.write:yanks.appeal:reviews.write:telemetry.write"
)

EXAMPLE_PLACEHOLDERS = {
    "SECRET_KEY": {"your-secret-key-here-change-this-in-production", "change-this-in-production"},
    "INTERNAL_API_SECRET": {"dev-secret-changeme"},
    "POSTGRES_PASSWORD": {"dev_password_change_me"},
    "MARKETPLACE_POSTGRES_PASSWORD": {"replace-with-a-local-development-password"},
    "LITELLM_MASTER_KEY": {"your-litellm-master-key-here"},
    "MARKETPLACE_STATIC_TOKENS": {"replace-with-a-local-admin-token"},
    "AZURE_API_BASE": {"https://your-resource.openai.azure.com"},
    "AZURE_API_KEY": {"your-azure-ai-api-key"},
    # A sample API version must never be silently treated as the operator's
    # Azure choice: API support depends on their deployed models.
    "AZURE_API_VERSION": {"2024-12-01-preview"},
    "AZURE_AI_DEFAULT_DEPLOYMENT": {"your-default-deployment"},
    "AZURE_AI_FAST_DEPLOYMENT": {"your-fast-deployment"},
    "AZURE_AI_REASONING_DEPLOYMENT": {"your-reasoning-deployment"},
}


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_env(text: str) -> dict[str, str]:
    """Parse simple dotenv assignments while preserving the source separately."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = ENV_ASSIGNMENT.match(line)
        if match:
            values[match.group(1)] = _unquote(match.group(2))
    return values


def is_placeholder(name: str, value: str | None) -> bool:
    """Return whether a known dotenv value still needs local setup."""
    if value is None:
        return True
    normalized = value.strip()
    if not normalized:
        return True
    if normalized in EXAMPLE_PLACEHOLDERS.get(name, set()):
        return True
    if name == "MARKETPLACE_STATIC_TOKENS":
        return normalized.startswith("replace-with-a-local-admin-token")
    lowered = normalized.lower()
    return (
        lowered.startswith(("your-", "replace-with-", "example-"))
        or lowered in {"changeme", "change-me", "placeholder", "<required>"}
        or normalized.startswith("${")
    )


def azure_missing(values: dict[str, str]) -> list[str]:
    return [name for name in AZURE_VARIABLES if is_placeholder(name, values.get(name))]


def _provider_model_is_missing(value: str | None) -> bool:
    if value is None:
        return True
    normalized = value.strip()
    if normalized in {"", "azure/"}:
        return True
    return normalized.lower().startswith(("azure/your-", "azure/replace-with-", "azure/example-"))


def litellm_runtime_missing(values: dict[str, str]) -> list[str]:
    """Validate the exact environment passed to the private proxy container."""
    missing: list[str] = []
    if is_placeholder("LITELLM_MASTER_KEY", values.get("LITELLM_MASTER_KEY")):
        missing.append("LITELLM_MASTER_KEY")
    for name in ("AZURE_API_BASE", "AZURE_API_KEY", "AZURE_API_VERSION"):
        if is_placeholder(name, values.get(name)):
            missing.append(name)
    for alias in ("DEFAULT", "FAST", "REASONING"):
        deployment_name = f"AZURE_AI_{alias}_DEPLOYMENT"
        model_name = f"AZURE_AI_{alias}_MODEL"
        if is_placeholder(deployment_name, values.get(deployment_name)) and _provider_model_is_missing(
            values.get(model_name)
        ):
            missing.append(deployment_name)
    return missing


def _generate_value(name: str) -> str:
    if name == "SECRET_KEY":
        return secrets.token_urlsafe(48)
    if name == "INTERNAL_API_SECRET":
        return secrets.token_hex(32)
    if name in {"POSTGRES_PASSWORD", "MARKETPLACE_POSTGRES_PASSWORD"}:
        return secrets.token_urlsafe(32)
    if name == "LITELLM_MASTER_KEY":
        return f"sk-{secrets.token_urlsafe(32)}"
    if name == "MARKETPLACE_STATIC_TOKENS":
        return f"{secrets.token_urlsafe(32)}:{MARKETPLACE_SCOPES}"
    raise ValueError(f"Unsupported local value: {name}")


def _expected_database_url(values: dict[str, str]) -> str:
    user = values.get("POSTGRES_USER") or "tesslate_user"
    password = values["POSTGRES_PASSWORD"]
    database = values.get("POSTGRES_DB") or "tesslate_dev"
    return f"postgresql+asyncpg://{user}:{password}@postgres:5432/{database}"


def _local_database_url_is_inconsistent(value: str, expected: str) -> bool:
    """Only repair local Compose URLs; preserve intentional external URLs."""
    if is_placeholder("DATABASE_URL", value):
        return True
    try:
        parsed = urlsplit(value)
        expected_parsed = urlsplit(expected)
    except ValueError:
        return False
    if parsed.hostname != "postgres":
        return False
    return (
        parsed.scheme != expected_parsed.scheme
        or unquote(parsed.username or "") != unquote(expected_parsed.username or "")
        or unquote(parsed.password or "") != unquote(expected_parsed.password or "")
        or parsed.port != expected_parsed.port
        or parsed.path != expected_parsed.path
    )


def _replace_assignments(text: str, replacements: dict[str, str]) -> str:
    for name, value in replacements.items():
        line_pattern = re.compile(
            rf"^([ \t]*(?:export[ \t]+)?{re.escape(name)}[ \t]*=[ \t]*)[^\r\n]*(\r?\n|$)",
            re.MULTILINE,
        )
        if line_pattern.search(text):
            text = line_pattern.sub(lambda match: f"{match.group(1)}{value}{match.group(2)}", text)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += f"{name}={value}\n"
    return text


def _remove_orphaned_sensitive_values(text: str) -> str:
    """Repair the malformed ``KEY=`` + next-line-value form without guessing.

    A dotenv assignment cannot span lines. This narrowly removes a following
    unassigned line only when it immediately follows an empty required-secret
    assignment, which is otherwise invalid Compose dotenv syntax.
    """
    for name in SENSITIVE_LOCAL_VARIABLES:
        orphan_pattern = re.compile(
            rf"^([ \t]*(?:export[ \t]+)?{re.escape(name)}[ \t]*=[ \t]*\r?\n)"
            r"[^\r\n#=]+(?:\r?\n|$)",
            re.MULTILINE,
        )
        text = orphan_pattern.sub(r"\1", text)
    return text


def _write_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        path.chmod(0o600)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def prepare_local_env(env_path: Path, example_path: Path) -> tuple[list[str], list[str], bool]:
    example_content = example_path.read_text(encoding="utf-8")
    example_values = parse_env(example_content)
    if env_path.exists():
        content = _remove_orphaned_sensitive_values(env_path.read_text(encoding="utf-8"))
        created = False
    else:
        content = example_content
        created = True

    values = parse_env(content)
    # A pre-existing .env may predate newly required variables. Append only
    # absent assignments from the versioned template; existing lines and their
    # comments stay untouched.
    missing_template_values = {
        name: value for name, value in example_values.items() if name not in values
    }
    effective_source_values = {**example_values, **values}
    replacements: dict[str, str] = {}
    generated: list[str] = []
    for name in SENSITIVE_LOCAL_VARIABLES:
        if is_placeholder(name, effective_source_values.get(name)):
            replacements[name] = _generate_value(name)
            generated.append(name)

    effective_values = {**effective_source_values, **missing_template_values, **replacements}
    expected_database_url = _expected_database_url(effective_values)
    existing_database_url = effective_source_values.get("DATABASE_URL", "")
    if _local_database_url_is_inconsistent(existing_database_url, expected_database_url):
        replacements["DATABASE_URL"] = expected_database_url

    all_replacements = {**missing_template_values, **replacements}
    if all_replacements or created or content != env_path.read_text(encoding="utf-8"):
        _write_atomically(env_path, _replace_assignments(content, all_replacements))

    final_values = parse_env(env_path.read_text(encoding="utf-8"))
    return generated, azure_missing(final_values), created


def _print_missing_azure(missing: list[str]) -> None:
    if not missing:
        print("Azure AI Foundry configuration is complete.")
        return
    print("Azure AI Foundry variables still required:")
    for name in missing:
        print(f"- {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--example", type=Path, default=REPO_ROOT / ".env.example")
    parser.add_argument(
        "--validate-azure",
        action="store_true",
        help="Validate Azure variables from the current process environment without printing values.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Read dotenv values directly for validation; do not source the file as shell code.",
    )
    args = parser.parse_args()

    if args.validate_azure:
        runtime_values = (
            parse_env(args.env_file.read_text(encoding="utf-8"))
            if args.env_file is not None
            else dict(os.environ)
        )
        missing = litellm_runtime_missing(runtime_values)
        if missing:
            print("LiteLLM runtime configuration is incomplete. Missing:")
            for name in missing:
                print(f"- {name}")
        else:
            print("LiteLLM runtime configuration is complete.")
        return 1 if missing else 0

    generated, missing, created = prepare_local_env(args.env, args.example)
    print("Local environment is ready." if created else "Local environment is ready; existing values were preserved.")
    if generated:
        print("Generated local values:")
        for name in generated:
            print(f"- {name}")
    else:
        print("All required local values were already configured.")
    preserved = [name for name in SENSITIVE_LOCAL_VARIABLES if name not in generated]
    preserved.append("DATABASE_URL")
    if preserved:
        print("Configured local values preserved:")
        for name in preserved:
            print(f"- {name}")
    _print_missing_azure(missing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

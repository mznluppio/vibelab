"""
Integration test fixtures for real-database testing.

Uses TestClient with a real, disposable PostgreSQL database. Which database that
is gets decided in ``tests/conftest.py`` (via ``tests/_test_database.py``) before
any app import; this module only brings the chosen target up. So an unrelated
PostgreSQL listening on the default port — a developer's local install, another
project's container — is never mistaken for the test database, never adopted,
and never stopped or modified. Override with ``TEST_DATABASE_URL`` or
``TEST_POSTGRES_PORT``.
"""

import contextlib
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

# Add orchestrator to path (redundant if parent conftest already did this)
orchestrator_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(orchestrator_dir))


from tests._test_database import (
    TEST_DB_NAME,
    port_is_listening,
    probe_test_database,
    resolve_test_database_url,
)

# Resolution is idempotent and pins the port in the environment, so calling it
# here and from tests/conftest.py::pytest_configure yields the same URL. It has
# to happen at import time: conftests load before pytest_configure, and the app
# engine is frozen at its own import — see tests/_test_database.py. Fixtures
# below (migrations, seed helpers) read this.
TEST_DATABASE_URL = resolve_test_database_url()


@pytest.fixture(scope="session", autouse=True)
def test_db_container():
    """
    Bring up the test PostgreSQL the suite was configured to use.

    - ``TEST_DATABASE_URL`` set explicitly: used verbatim, and must already be
      reachable — nothing is started or stopped for a target we don't own.
    - Otherwise: reuse a genuine test database already on the port (CI service
      container, manually started compose), else start
      ``docker-compose.test.yml`` there and tear it down afterwards.

    An unrelated PostgreSQL is never adopted, stopped, or modified.
    """
    import subprocess
    import time

    repo_root = Path(__file__).parent.parent.parent.parent
    port = int(TEST_DATABASE_URL.rsplit(":", 1)[1].split("/")[0])

    ok, reason = probe_test_database(TEST_DATABASE_URL)
    if ok:
        # Already the real thing — reuse without touching its lifecycle.
        yield
        return

    if os.environ.get("TEST_DATABASE_URL"):
        raise RuntimeError(
            f"TEST_DATABASE_URL is set but is not a usable test database: {reason}\n"
            f"  URL: {TEST_DATABASE_URL}\n"
            "Point it at a disposable PostgreSQL whose database is named "
            f"{TEST_DB_NAME!r}, or unset it to let the suite start its own."
        )

    # Port taken by something that isn't our database: refuse rather than
    # adopt it. Only reachable when TEST_POSTGRES_PORT was set by hand —
    # auto-resolution already stepped aside from occupied ports.
    if port_is_listening(port):
        raise RuntimeError(
            f"TEST_POSTGRES_PORT={port} is occupied by a server that is not the "
            f"test database ({reason}).\n"
            "Free that port, choose another via TEST_POSTGRES_PORT, or set "
            "TEST_DATABASE_URL to an existing test database."
        )

    compose_env = {**os.environ, "TEST_POSTGRES_PORT": str(port)}
    result = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.test.yml", "up", "-d", "--wait"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=compose_env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to start test DB on port {port}: {result.stderr}\n"
            "If a stale container is holding the name or port, remove it with "
            "`docker compose -f docker-compose.test.yml down -v`."
        )

    last_reason = "not ready"
    for _ in range(30):
        ok, last_reason = probe_test_database(TEST_DATABASE_URL)
        if ok:
            break
        time.sleep(1)
    else:
        subprocess.run(
            ["docker", "compose", "-f", "docker-compose.test.yml", "down", "-v"],
            cwd=repo_root,
            capture_output=True,
            env=compose_env,
        )
        raise RuntimeError(
            f"Test postgres on port {port} did not become ready in 30s: {last_reason}"
        )

    yield

    # Tear down only the container we started.
    subprocess.run(
        ["docker", "compose", "-f", "docker-compose.test.yml", "down", "-v"],
        cwd=repo_root,
        capture_output=True,
        env=compose_env,
    )


@pytest.fixture(scope="session", autouse=True)
def setup_database(test_db_container):
    """
    Run database migrations once per test session.

    Uses alembic to bring the test database to latest schema.
    Depends on test_db_container to ensure postgres is running first.
    """
    import subprocess

    # Get directory where alembic.ini is located
    base_dir = Path(__file__).parent.parent.parent

    # Run alembic upgrade head — invoke via current python interpreter
    # (`sys.executable -m alembic`) so the venv's alembic is used regardless
    # of PATH state. Avoids FileNotFoundError when pytest is run via
    # `.venv/bin/python -m pytest` from a non-activated shell.
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=base_dir,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
    )

    if result.returncode != 0:
        raise RuntimeError(f"Alembic migration failed: {result.stderr}")

    yield


def _rebind_database_engine() -> None:
    """Drop + recreate the module-level ``app.database.engine`` so a new
    TestClient gets a fresh asyncpg connection pool bound to its own loop.

    ``app.database.engine`` is a module-level singleton. Each TestClient
    session-scope fixture (``tests/integration/conftest.py`` and
    ``tests/routers/conftest.py``) creates a new asyncio loop. After
    the first conftest's TestClient closes, the engine pool still
    holds asyncpg connections bound to the now-closed loop. Calling
    ``engine.dispose()`` releases the connections but leaves the engine
    object — which still has internal state from the dead loop. Building
    a brand-new engine via ``create_async_engine`` and rebinding the
    module-level globals is the only way to get a clean state.

    Idempotent: safe to call from any conftest's session fixture.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app import database as _db

    with contextlib.suppress(Exception):
        asyncio.new_event_loop().run_until_complete(_db.engine.dispose())

    settings = _db.settings
    new_engine = create_async_engine(
        settings.database_url,
        echo=False,
        future=True,
        **_db._build_engine_kwargs(settings.database_url),
    )
    _db.engine = new_engine
    _db.AsyncSessionLocal = async_sessionmaker(
        new_engine, class_=_db.AsyncSession, expire_on_commit=False
    )


@pytest.fixture(scope="session")
def api_client_session():
    """
    Unauthenticated TestClient for FastAPI (session-scoped).

    See ``_rebind_database_engine`` docstring for why we recreate the
    engine before every TestClient session — the short version is
    cross-conftest session-scoped fixtures share a process but not a
    loop, and asyncpg's connection pool can't tolerate that.
    """
    from app.main import app

    _rebind_database_engine()

    with TestClient(app, base_url="http://test") as client:
        yield client


@pytest.fixture
def api_client(api_client_session):
    """
    Per-test api_client that uses the session-scoped client.

    Clears headers between tests for isolation.
    """
    # Clear any auth headers from previous tests
    api_client_session.headers.pop("Authorization", None)
    return api_client_session


def _ensure_at_least_one_base(client) -> str:
    """Return an existing base id, or seed a free one and return that.

    The integration suite runs against a freshly-migrated Postgres with no
    seed data. The /api/marketplace/bases endpoint is read-only and the
    creator endpoint requires admin auth, so we insert directly via
    asyncpg from a fresh event loop to avoid touching the running
    asyncpg pool bound to the TestClient's loop.
    """
    response = client.get("/api/marketplace/bases")
    assert response.status_code == 200
    data = response.json()
    if data.get("bases") and len(data["bases"]) > 0:
        return data["bases"][0]["id"]

    import asyncio
    import uuid as _uuid

    import asyncpg

    base_id = _uuid.uuid4()
    slug = f"test-base-{_uuid.uuid4().hex[:8]}"
    sync_url = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

    async def _seed():
        conn = await asyncpg.connect(sync_url)
        try:
            await conn.execute(
                """
                INSERT INTO marketplace_bases
                    (id, name, slug, description, category, pricing_type,
                     price, is_active, source_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                base_id,
                "Test Base",
                slug,
                "Auto-seeded base for integration tests.",
                "fullstack",
                "free",
                0,
                True,
                _uuid.UUID("00000000-0000-0000-0000-000000000002"),
            )
        finally:
            await conn.close()

    asyncio.run(_seed())
    return str(base_id)


@pytest.fixture
def default_base_id(api_client_session, authenticated_client):
    """
    Get a default marketplace base ID and add it to user's library.

    Project creation requires the base to be in the user's library first.
    """
    client, _ = authenticated_client
    base_id = _ensure_at_least_one_base(client)
    # Add base to user's library (free bases can be added without purchase).
    client.post(f"/api/marketplace/bases/{base_id}/purchase")
    return base_id


@pytest.fixture
def authenticated_client(api_client_session):
    """
    Authenticated client with Bearer token.

    Returns: (client, user_data) tuple
    - client: TestClient with Authorization header set
    - user_data: dict with user fields (id, email, slug, etc.)
    """
    # Register a test user with unique email
    register_data = {
        "email": f"test-{uuid4().hex}@example.com",
        "password": "TestPassword123!",
        "name": "Integration Test User",
    }

    response = api_client_session.post("/api/auth/register", json=register_data)
    assert response.status_code == 201, f"Registration failed: {response.text}"
    user_data = response.json()

    # Login to get JWT token
    login_data = {
        "username": register_data["email"],  # fastapi-users uses "username" field for email
        "password": register_data["password"],
    }

    response = api_client_session.post(
        "/api/auth/jwt/login",
        data=login_data,  # form data, not JSON
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    token_data = response.json()

    # Set Authorization header
    api_client_session.headers["Authorization"] = f"Bearer {token_data['access_token']}"

    yield api_client_session, user_data

    # Cleanup: remove auth header after test
    api_client_session.headers.pop("Authorization", None)


@pytest.fixture(scope="function")
def mock_orchestrator():
    """
    Mock Docker/Kubernetes orchestrator and file operations for project tests.

    Integration tests focus on API and database, not actual container orchestration.
    Only applies to tests that explicitly request this fixture.
    """
    with (
        patch("app.services.orchestration.get_orchestrator") as mock_get_orch,
        patch("app.routers.projects.makedirs_async") as mock_makedirs,
        patch("app.routers.projects.walk_directory_async") as mock_walk,
        patch("app.routers.projects.read_file_async") as mock_read,
        patch("pathlib.Path.mkdir") as mock_mkdir,
    ):
        # Create a mock orchestrator
        mock_orch = AsyncMock()
        mock_orch.create_project = AsyncMock(return_value=True)
        mock_orch.start_project = AsyncMock(return_value=True)
        mock_orch.stop_project = AsyncMock(return_value=True)
        mock_orch.delete_project = AsyncMock(return_value=True)
        # list_tree / read_file / write_file are called by file-tree and file
        # operations tests. Return concrete values so FastAPI can serialize the
        # response without recursing through bare AsyncMock objects.
        mock_orch.list_tree = AsyncMock(return_value=[])
        mock_orch.read_file = AsyncMock(return_value="")
        mock_orch.write_file = AsyncMock(return_value=True)
        mock_orch.delete_file = AsyncMock(return_value=True)
        mock_orch.get_project_status = AsyncMock(
            return_value={"status": "inactive", "containers": {}}
        )

        mock_get_orch.return_value = mock_orch

        # Mock file operations
        mock_makedirs.return_value = AsyncMock()
        mock_walk.return_value = AsyncMock(return_value=[])
        mock_read.return_value = AsyncMock(return_value="")
        mock_mkdir.return_value = None

        yield mock_orch


@pytest.fixture(autouse=True, scope="session")
def mock_external_services():
    """
    Auto-mock external services to prevent real API calls during tests.

    Mocks:
    - Stripe (customer creation, subscriptions)
    - LiteLLM (user provisioning)
    - Discord (webhooks)
    - Email (SMTP)

    Session-scoped to maintain unique API key generation across all tests.
    """

    def mock_create_user_key(*args, **kwargs):
        """Generate unique API keys for each user using uuid."""
        unique_id = uuid4().hex[:8]
        return {
            "api_key": f"sk-test-litellm-{unique_id}",
            "litellm_user_id": f"litellm-user-{unique_id}",
        }

    def mock_create_stripe_customer(*args, **kwargs):
        """Generate unique Stripe customer IDs per call.

        Team.stripe_customer_id is UNIQUE; a constant fake id collides on
        the second user registration in the same DB.
        """
        return {"id": f"cus_test_{uuid4().hex[:16]}"}

    with (
        patch("app.services.stripe_service.stripe_service.create_customer") as mock_stripe,
        patch("app.services.litellm_service.litellm_service.create_user_key") as mock_litellm,
        patch(
            "app.services.discord_service.discord_service.send_signup_notification"
        ) as mock_discord,
        patch(
            "app.services.discord_service.discord_service.send_login_notification"
        ) as mock_discord_login,
    ):
        # Stripe mock — unique id per call (UNIQUE constraint on Team).
        mock_stripe.side_effect = mock_create_stripe_customer

        # LiteLLM mock - returns unique keys
        mock_litellm.side_effect = mock_create_user_key

        # Discord mocks (async)
        mock_discord.return_value = AsyncMock()
        mock_discord_login.return_value = AsyncMock()

        yield {
            "stripe": mock_stripe,
            "litellm": mock_litellm,
            "discord": mock_discord,
            "discord_login": mock_discord_login,
        }

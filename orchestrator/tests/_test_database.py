"""Resolve which PostgreSQL the test suite should use.

Lives outside any conftest because the answer is needed *before* the app is
imported. ``app/main.py`` does ``from .database import engine``, binding the
engine object at import time, so a URL chosen after import can never reach the
startup path — rebinding ``app.database.engine`` would leave ``app.main.engine``
pointing at the original. Resolution therefore happens in the root conftest's
``pytest_configure``, ahead of the first app import.

An open port proves nothing: a developer's local PostgreSQL or another project's
container can occupy the default one. Only a successful login to a database
named ``TEST_DB_NAME`` counts as the test database. An unrelated server is never
adopted, never stopped, and never modified.

Overrides:
  TEST_DATABASE_URL   full SQLAlchemy URL, used verbatim
  TEST_POSTGRES_PORT  host port to use (default 5433)
"""

from __future__ import annotations

import os
import socket

# Must match docker-compose.test.yml's postgres-test service.
TEST_DB_NAME = "tesslate_test"
TEST_DB_USER = "tesslate_test"
TEST_DB_PASSWORD = "testpass"
DEFAULT_TEST_DB_PORT = 5433


def build_test_database_url(port: int) -> str:
    return (
        f"postgresql+asyncpg://{TEST_DB_USER}:{TEST_DB_PASSWORD}"
        f"@localhost:{port}/{TEST_DB_NAME}"
    )


def asyncpg_dsn(url: str) -> str:
    """SQLAlchemy URL -> plain libpq DSN that ``asyncpg.connect`` accepts."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


def port_is_listening(port: int, host: str = "localhost", timeout: float = 2.0) -> bool:
    """True when *something* accepts TCP on the port — identity unknown."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_test_database(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    """Authenticate against ``url`` and confirm it really is the test database.

    Returns ``(ok, reason)``; ``reason`` is empty when ok.
    """
    import asyncio

    import asyncpg

    async def _check() -> tuple[bool, str]:
        try:
            conn = await asyncio.wait_for(asyncpg.connect(asyncpg_dsn(url)), timeout=timeout)
        except TimeoutError:
            return False, f"connection timed out after {timeout}s"
        except Exception as exc:  # auth failure, missing role/db, refused, ...
            return False, f"{type(exc).__name__}: {exc}"
        try:
            actual = await conn.fetchval("SELECT current_database()")
        finally:
            await conn.close()
        if actual != TEST_DB_NAME:
            return False, f"connected to database {actual!r}, expected {TEST_DB_NAME!r}"
        return True, ""

    try:
        return asyncio.run(_check())
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"{type(exc).__name__}: {exc}"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("localhost", 0))
        return int(sock.getsockname()[1])


def resolve_test_database_url() -> str:
    """Decide the test database URL and publish it to the environment.

    Sets ``DATABASE_URL`` (what the app reads) and ``TEST_POSTGRES_PORT`` (what
    docker-compose.test.yml binds), so the integration fixture can start a
    container on the very port already baked into the app's engine.

    Does not start, stop, or modify any server — see
    ``tests/integration/conftest.py`` for lifecycle management.
    """
    explicit_url = os.environ.get("TEST_DATABASE_URL")
    if explicit_url:
        os.environ["DATABASE_URL"] = explicit_url
        return explicit_url

    explicit_port = os.environ.get("TEST_POSTGRES_PORT")
    if explicit_port:
        port = int(explicit_port)
    else:
        port = DEFAULT_TEST_DB_PORT
        # Reuse the default port when it is free, or when a real test database
        # is already there (CI service container, manually started compose).
        # Step aside only when an unrelated server holds it.
        if port_is_listening(port):
            ok, _ = probe_test_database(build_test_database_url(port))
            if not ok:
                port = find_free_port()

    url = build_test_database_url(port)
    os.environ["DATABASE_URL"] = url
    os.environ["TEST_POSTGRES_PORT"] = str(port)
    return url


def get_test_database_url() -> str:
    """The resolved test database URL, resolving on first use if needed.

    Test modules must call this instead of hardcoding a URL: a literal
    ``localhost:5433`` silently connects to whatever holds that port — often a
    developer's own PostgreSQL — instead of the disposable test database.
    """
    return os.environ.get("DATABASE_URL") or resolve_test_database_url()


def get_test_database_port() -> int:
    """Host port of the resolved test database."""
    return int(get_test_database_url().rsplit(":", 1)[1].split("/")[0])


def sibling_database_url(db_name: str, *, driver: str = "postgresql+asyncpg") -> str:
    """URL for another database on the same server as the test database.

    A few suites need their own database (destructive alembic runs, uniqueness
    fixtures) but the same host, port, and credentials.
    """
    return f"{driver}://{TEST_DB_USER}:{TEST_DB_PASSWORD}@localhost:{get_test_database_port()}/{db_name}"

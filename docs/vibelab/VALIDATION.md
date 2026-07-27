# Validation

## Completed locally

- Docker Compose configuration and startup
- Traefik, PostgreSQL, Redis, orchestrator, worker, gateway, and frontend
- Alembic migrations and system seeds
- Registration and password login via the API
- Authenticated user access
- Empty-workspace project creation and persistence
- Frontend typecheck: `npm run typecheck` passed.
- Frontend lint: `npm run lint` passed with 52 pre-existing React hook warnings and no errors.
- Frontend test suite: `npm test -- --run` reported 39 files / 249 tests passed. Vitest also reports
  four pre-existing post-test requests to the fake `test` host; the command exits successfully.
- Frontend production build: `npm run build` passed. Vite reports its existing chunk-size and dynamic-import warnings.
- Post-rebranding service restart, health checks, and marketplace seed verification: passed.
- `Legrand Official` is active in PostgreSQL with the upstream-compatible
  `tesslate-official` handle and an intentionally local empty catalog.

## Requires configured internal services

- Selecting a synchronised marketplace base
- Starting a generated workspace and its embedded preview
- Agent chat generation or modification

These flows require an approved internal marketplace catalog and LiteLLM/model
configuration. They are intentionally not replaced with mocks or weakened
checks in VibeLab.

## Backend test environment

The production orchestrator image intentionally excludes pytest and development
dependencies. A dedicated test PostgreSQL instance was started and migrated
using the repository procedure. The targeted marketplace-sync suite ran 22
tests successfully with 10 skips, but has one upstream test failure and one
async fixture teardown error: the test instantiates an upstream exception with
an outdated signature and reuses an asyncpg connection across event loops on
CPython 3.13. Neither concerns the VibeLab seed change. The modified backend
modules were also compiled successfully with `py_compile`.

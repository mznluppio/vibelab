# Legrand Official marketplace

## Architecture

VibeLab uses the embedded `packages/tesslate-marketplace` package as its
self-hosted, internal federation hub. It is not a separate repository or a
submodule. The root Docker Compose stack starts two services on
`tesslate-network`:

- `marketplace-postgres`, an isolated PostgreSQL database persisted in
  `vibelab-marketplace-postgres-data`;
- `marketplace`, the `/v1` FastAPI hub, persisted in
  `vibelab-marketplace-data` for its hub ID, attestation key, signing secret,
  and local bundle store.

The hub is reachable to VibeLab only at `http://marketplace:8800`.
`LEGRAND_OFFICIAL_BASE_URL` is passed to both the orchestrator and ARQ worker.
The worker consumes `/v1/changes`, fetches item details, and updates the local
catalog cache. For application bundles, the worker (not the browser) downloads
the hub-signed URL, so `BUNDLE_BASE_URL` is also `http://marketplace:8800`.

The display identities are `VibeLab Marketplace` (OpenAPI) and `Legrand
Official` (hub/source/official creator). The historical `tesslate-official`
source handle, reserved UUIDs, `/v1` protocol, `X-Tesslate-Hub-*` headers,
package path, seed-owner handle, and existing migrations remain technical
compatibility identifiers.

## Start and synchronise

1. Copy `.env.example` to the untracked `.env` if needed, then set a local
   `MARKETPLACE_POSTGRES_PASSWORD` and a scoped
   `MARKETPLACE_STATIC_TOKENS` value. Do not commit either. The example
   documents the required token format; replace its placeholder before using
   the Swagger administration API.
2. Start the stack with `docker compose up --build -d`. The hub first runs its
   idempotent `scripts/init_db.py`, then serves `/v1`; it loads the packaged
   JSON seeds on startup.
3. Confirm `docker compose ps`, then query
   `docker compose exec marketplace curl -fsS http://localhost:8800/v1/manifest`.
4. Trigger the existing source-sync endpoint from an authenticated
   administrator, or wait for the worker's normal sync cadence. A successful
   full manifest-and-changes sync updates `last_synced_at` and clears an old
   `last_sync_error`; a failed sync retains the new error for diagnosis.

The root Compose configuration disables `pricing.read`, `pricing.write`, and
`pricing.checkout`. No Stripe credential is supplied and the orchestrator's
hub-checkout flag remains off, so the catalog is an internal install/library
catalog rather than a commerce surface.

The managed Next.js base is private. Set `BASE_CACHE_GIT_TOKEN` in the
untracked `.env` to a fine-grained GitHub token restricted to that repository
with **Contents: Read**. The token is only used for the backend's warm-cache
clone; it is not written to the marketplace record, project metadata, logs,
or cache manifest. A user-authenticated fallback clone uses that user's stored
Git provider credential instead.

## Manage official content

No administration UI is added. Use one of the existing routes:

1. Edit a packaged JSON definition in `packages/tesslate-marketplace/app/seeds/`
   (`bases.json`, `agents.json`, `skills_tesslate.json`, `mcp_servers.json`, or
   `themes.json`) and restart `marketplace`. The loader UPSERTs by
   `(kind, slug)`, emits changes, and deactivates seed-owned entries removed
   from a loaded file.
2. Use the existing Swagger UI/API endpoints with a token carrying the
   documented scopes. The service continues to expose its existing admin and
   publishing APIs; pricing and checkout capabilities are unavailable in the
   VibeLab deployment.

Add a Base with a stable `slug`, `kind: "base"`, a repository URL accessible to
the runtime, and a documented commercial-use licence. Add an Agent, Skill, MCP server, or Theme
to its corresponding seed file with its existing kind and free pricing shape.
Preserve third-party attribution fields; official entries inherit the visible
`Legrand Official` creator identity while retaining the internal seed owner
handle. Update an entry in place to publish a revision. Remove it from the
loaded seed file to emit a deactivation; do not delete historical migrations
or rewrite stable IDs.

## Seed and licence review

The initial synchronization includes the managed internal `Next.js 16` Base,
`VibeLab Default` Agent, `Testing Setup` Skill, `Microsoft Learn` MCP server,
and published themes. All packaged seeds are free.

Repository accessibility was checked for the official Next.js 16 Base at
`TesslateAI/Studio-NextJS-16-Base` (public `HEAD`
`16b5032cc10bf6703a3483d69ece0f9c466bc8a1`). Its GitHub licence endpoint and
`LICENSE` path did not provide an explicit licence at the time of this change.
Therefore its commercial-use approval is **pending**: the VibeLab-managed
variant at `mznluppio/vibelab-nextjs-16-base` is private, retains the upstream
provenance, and is restricted to internal validation. Obtain an explicit
licence before enabling it for a commercial deployment. Apply the same review
to every repository-backed community Base before enabling it; a public
repository alone is not approval.

## Validation checklist

Verify `/v1/manifest`, `/v1/changes`, and `/v1/items?kind=` for `base`,
`agent`, `skill`, `mcp_server`, and `theme`. Confirm `Legrand Official` in the
source metadata and `Next.js 16` in the cache after a successful source sync.
Then verify installing an Agent and Skill, browsing an MCP and Theme, and
restart the stack to confirm that the marketplace database and `/data` state
persist. Do not configure this source to use `marketplace.tesslate.com` or the
obsolete `local://legrand-official` path.

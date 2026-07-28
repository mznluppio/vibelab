# Marketplace branding and agent permissions

## Where the marketplace runs

`packages/tesslate-marketplace` is the existing FastAPI federation hub. It
implements the `/v1` protocol and has no graphical interface. Its seed JSON
is loaded by the hub and emitted through `/v1/changes`; the orchestrator
syncs that feed into its marketplace cache. The visible Marketplace, Library,
and Admin surfaces are the existing VibeLab frontend under `app/src/`.

## Branding applied

The hub default and its Kubernetes overlays now publish `Legrand Official`.
Swagger identifies the product as `VibeLab Marketplace`, and the official
`tesslate-agent` seed now displays as `VibeLab Default`. The existing source
seed and response projection use `Legrand Official` as the official creator.
The data migration `0122_vibelab_marketplace_display_branding` updates old
stored display values before the next federation synchronization.

The following protocol and cache identifiers intentionally remain unchanged:

- package and module paths containing `tesslate-marketplace`;
- `/v1`, `X-Tesslate-Hub-*`, `HUB_ID`, and the `TesslateAgent` runtime class;
- the `tesslate-official` handle, reserved source UUIDs, seed owner handle,
  tables, migration history, and the `tesslate-agent` slug.

## Permissions

Previously, the Library treated a `UserPurchasedAgent` installation as an
editing entitlement. The editor opened for every installed agent and PATCH
silently forked any open-source row. Skills, sub-agents, selected models, and
MCP assignments had additional mutation paths that did not authorize the
target agent.

`services/agent_edit_permissions.py` now centralizes the rule:

- official, built-in, system, and system-default agents are read-only for a
  standard user and return `403` for every definition mutation;
- a personal agent is editable only by its `created_by_user_id` or
  `forked_by_user_id` owner;
- a global administrator can manage protected rows through the backend and
  the existing Admin surfaces;
- `POST /agents/{id}/fork` remains the explicit customization path; PATCH
  never creates an implicit fork.

`GET /api/marketplace/my-agents` now returns origin metadata and `can_edit`.
Library and Connectors consume that value to hide editing and connector
assignment controls for installed official agents. Backend enforcement covers
PATCH/delete/publish/unpublish, model selection, sub-agent mutations, Skill
assignment, and MCP assignment.

## Remaining limits

Skills can be attached only to an editable personal agent; authoring and
publication of official skills still belongs to the federated hub. MCP
credentials remain per-user/team connector configuration, not marketplace
content. Themes have their own legacy mutation routes and are outside this
agent-specific policy. The official source now uses the reachable internal hub
documented in [LEGRAND-MARKETPLACE.md](LEGRAND-MARKETPLACE.md), rather than the
incomplete `local://legrand-official` ingestion path.

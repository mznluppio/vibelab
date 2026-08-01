# Teams Router

**File**: `orchestrator/app/routers/teams.py`

**Base path**: `/api/teams`

## Purpose

Team CRUD, memberships, invitations, project access control, and audit log. Backs the dual-scope RBAC (team role and optional project-level override) used across OpenSail.

## Endpoints

### Team CRUD

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/` | platform administrator | Create a team (caller becomes admin, 201). |
| GET | `/` | user | List teams the caller belongs to (with role). |
| GET | `/{team_slug}` | member | Team details. |
| PATCH | `/{team_slug}` | admin | Update team fields and non-admin Marketplace/Automations access. |
| DELETE | `/{team_slug}` | admin | Delete non-personal team (204). |
| POST | `/{team_slug}/switch` | member | Set the user's default/active team. |

### Members

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/{team_slug}/members` | member | List members with roles. |
| POST | `/{team_slug}/members/invite` | admin | Email invite (201, 50/day limit). |
| POST | `/{team_slug}/members/link` | admin | Generate a share link invite (201, max 10 active). |
| DELETE | `/{team_slug}/members/{user_id}` | admin | Remove member (204). |
| PATCH | `/{team_slug}/members/{user_id}` | admin | Change role (admin/editor/viewer). |
| POST | `/{team_slug}/leave` | member | Leave team. |

### Invitations

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/invitations/{token}` | public | Preview invite (name, team, expiry). |
| POST | `/invitations/{token}/accept` | user | Accept invite. |
| GET | `/{team_slug}/invitations` | admin | List pending invitations. |
| DELETE | `/{team_slug}/invitations/{invitation_id}` | admin | Revoke (204). |

### Project Access

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/{team_slug}/projects/{project_slug}/members` | member | List project members + roles. |
| POST | `/{team_slug}/projects/{project_slug}/members` | admin | Grant project access. |
| PATCH | `/{team_slug}/projects/{project_slug}/members/{user_id}` | admin | Change project role. |
| DELETE | `/{team_slug}/projects/{project_slug}/members/{user_id}` | admin | Revoke project access (204). |
| PATCH | `/{team_slug}/projects/{project_slug}/visibility` | admin | Toggle team/private. |

### Audit Log

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/{team_slug}/audit-log` | admin | Filterable team log. |
| GET | `/{team_slug}/projects/{project_slug}/audit-log` | member | Project-scoped log. |
| POST | `/{team_slug}/audit-log/export` | admin | CSV export. |

## Auth

- `POST /` additionally requires `User.is_superuser`; the sidebar hides this action for all other users.
- Team administrators can opt editors and viewers into Marketplace, Automations, Apps, and Library in Team Settings. Those settings default to disabled.
- Repository imports and prompt-menu connectors are independently configurable for non-administrators and default to enabled, preserving existing team behaviour. Repository restrictions are enforced both when creating an imported project and when cloning into an existing project.
- `current_active_user` plus role check via `check_team_permission` / `get_project_with_access`.
- Invite token preview is public; acceptance requires auth.
- All state changes append to `AuditLog`.

## Related

- Models: `Team`, `TeamMembership`, `ProjectMembership`, `TeamInvitation`, `AuditLog` in [models_team.py](../../../orchestrator/app/models_team.py).
- Schemas: [schemas_team.py](../../../orchestrator/app/schemas_team.py).
- Permission engine: [../../../orchestrator/app/permissions.py](../../../orchestrator/app/permissions.py).

# Platform team and workspace governance

VibeLab distinguishes three scopes. A platform administrator is a user with
`User.is_superuser`; they manage instance-wide Team policy. A Team administrator
has `TeamMembership.role=admin` and manages only their Team. A Workspace
administrator has an effective `ProjectMembership`/owner administrator role and
manages access to that Workspace.

## Team policy

In Admin Dashboard → User Management, platform administrators control two
persistent defaults, both disabled for enterprise deployments:

- **Automatically create personal teams** provisions a personal Team only for a
  newly registered user who has not joined an invited Team.
- **Allow users to create teams** controls `POST /api/teams` for users without
  an exception. Platform administrators are always allowed.

The user detail panel has a Team creation override: **Inherit platform policy**,
**Allowed**, or **Disabled**. The backend evaluates this policy for every API
request; hiding the sidebar action is only a user-interface convenience.

Existing personal Teams are deliberately retained. Nothing moves or deletes
their Workspaces. Administrators can inspect them with:

```sql
SELECT t.slug, t.name, COUNT(p.id) AS workspace_count
FROM teams t
LEFT JOIN projects p ON p.team_id = t.id
WHERE t.is_personal = true
GROUP BY t.id, t.slug, t.name
ORDER BY workspace_count, t.created_at;
```

## Invitations

Email invitations are accepted during registration before optional personal
Team provisioning. The invited Team becomes `user.default_team_id`. Token-based
links remain token-driven: after sign-in, the existing invite page accepts the
token, reuses/reactivates the membership when needed, and makes that Team
active. `GET /api/teams` is a read-only listing and never creates a Team.

## Workspaces

New Workspaces are private by default; existing Workspace visibility is not
changed. Team administrators and platform administrators can access every
Workspace in their Team. Editors and viewers can access a private Workspace
only when they own it or have an active `ProjectMembership`; Team-visible
Workspaces remain available to the whole Team according to their Team role.

The existing Project Access control lets a Workspace administrator switch
between **Private** and **Team visible**, add active Team members, choose
`admin`, `editor`, or `viewer`, change a role, and remove a member. The owner
cannot lose effective administrator access, and every access mutation is written
to the existing Team `AuditLog`.

When switching Teams, the client refetches the Workspace list from the
server. Direct Workspace routes use the existing project RBAC helper, so a
cached item cannot grant access to another Team's Workspace.

## Verification

Run focused checks from `orchestrator/`:

```bash
pytest -q tests/rbac/test_permissions.py tests/test_litellm_runtime_config.py
```

Then verify a platform administrator, Team administrator, editor, and viewer:

1. Disable personal Team and Team creation defaults.
2. Register through an invitation and confirm the invited Team is active.
3. Create two private Workspaces and grant each non-admin user access to only one.
4. Change one Workspace to Team visibility, then remove a member and retry its
   direct URL.

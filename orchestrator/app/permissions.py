"""
Centralized RBAC permission system for OpenSail.

Provides the Permission enum, role-to-permission mappings, and core access-check
functions used across all routers. This module is the single source of truth for
"who can do what" — routers call into these helpers instead of hand-rolling
owner_id comparisons.

See .claude/research/rbac-prd.md for the full RBAC specification.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from .models import Project
    from .models_auth import User
    from .models_team import TeamMembership

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Permission Enum
# ---------------------------------------------------------------------------


class Permission(StrEnum):
    """Every granular permission in the system. Values are dot-delimited for
    readability in logs and audit trails."""

    # Team-level
    TEAM_VIEW = "team.view"
    TEAM_EDIT = "team.edit"
    TEAM_DELETE = "team.delete"
    TEAM_INVITE = "team.invite"
    TEAM_REMOVE_MEMBER = "team.remove_member"
    TEAM_CHANGE_ROLE = "team.change_role"
    BILLING_VIEW = "billing.view"
    BILLING_MANAGE = "billing.manage"
    BILLING_USAGE = "billing.usage"

    # Project-level
    PROJECT_LIST = "project.list"
    PROJECT_CREATE = "project.create"
    PROJECT_VIEW = "project.view"
    PROJECT_EDIT = "project.edit"
    PROJECT_DELETE = "project.delete"
    PROJECT_SETTINGS = "project.settings"

    # File
    FILE_READ = "file.read"
    FILE_WRITE = "file.write"
    FILE_DELETE = "file.delete"

    # Container
    CONTAINER_VIEW = "container.view"
    CONTAINER_CREATE = "container.create"
    CONTAINER_EDIT = "container.edit"
    CONTAINER_DELETE = "container.delete"
    CONTAINER_START_STOP = "container.start_stop"

    # Chat / Agent
    CHAT_VIEW = "chat.view"
    CHAT_SEND = "chat.send"
    CHAT_DELETE = "chat.delete"

    # Deployment
    DEPLOYMENT_VIEW = "deployment.view"
    DEPLOYMENT_CREATE = "deployment.create"
    DEPLOYMENT_DELETE = "deployment.delete"

    # Git
    GIT_VIEW = "git.view"
    GIT_WRITE = "git.write"

    # Kanban
    KANBAN_VIEW = "kanban.view"
    KANBAN_EDIT = "kanban.edit"

    # Snapshot
    SNAPSHOT_VIEW = "snapshot.view"
    SNAPSHOT_CREATE = "snapshot.create"
    SNAPSHOT_RESTORE = "snapshot.restore"

    # Terminal
    TERMINAL_ACCESS = "terminal.access"

    # Credentials
    CREDENTIALS_VIEW = "credentials.view"
    CREDENTIALS_MANAGE = "credentials.manage"
    API_KEYS_MANAGE = "api_keys.manage"

    # Channel
    CHANNEL_VIEW = "channel.view"
    CHANNEL_MANAGE = "channel.manage"

    # MCP (legacy — kept for backward compat with older callers)
    MCP_VIEW = "mcp.view"
    MCP_MANAGE = "mcp.manage"

    # Connectors (issue #307 — user-identity-bound MCP connectors).
    # Install scope is user-first; project-scope overrides require PROJECT_EDIT
    # on the target project. No team-scope install is offered.
    CONNECTORS_MANAGE_USER = "connectors.manage_user"
    CONNECTORS_MANAGE_PROJECT = "connectors.manage_project"

    # Agent
    AGENT_VIEW = "agent.view"
    AGENT_MANAGE = "agent.manage"

    # Audit
    AUDIT_VIEW = "audit.view"
    AUDIT_EXPORT = "audit.export"

    # Public API
    MARKETPLACE_READ = "marketplace.read"
    MODELS_PROXY = "models.proxy"
    USAGE_READ = "usage.read"

    # Apps — typed action invocation against installed Tesslate Apps.
    # Required by the agent's ``invoke_app_action`` tool and by any future
    # external/automation surface that dispatches an app action. Phase 1 of
    # the OpenSail Automation Runtime introduces this scope; Phase 2 layers
    # per-contract ``allow_apps`` enforcement on top.
    APP_INVOKE = "app.invoke"

    # Desktop / External (public-api extensions)
    DESKTOP_PAIR = "desktop.pair"
    AGENTS_READ = "agents.read"
    AGENTS_HANDOFF = "agents.handoff"
    PROJECTS_SYNC = "projects.sync"
    K8S_PROJECTS = "k8s.projects"
    MARKETPLACE_INSTALL = "marketplace.install"


# ---------------------------------------------------------------------------
# Role → Permission mapping
# ---------------------------------------------------------------------------

_ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

_ADMIN_ONLY: frozenset[Permission] = frozenset(
    {
        Permission.TEAM_EDIT,
        Permission.TEAM_DELETE,
        Permission.TEAM_INVITE,
        Permission.TEAM_REMOVE_MEMBER,
        Permission.TEAM_CHANGE_ROLE,
        Permission.BILLING_MANAGE,
        Permission.PROJECT_DELETE,
        Permission.CONTAINER_DELETE,
        Permission.DEPLOYMENT_DELETE,
        Permission.API_KEYS_MANAGE,
        Permission.AUDIT_VIEW,
        Permission.AUDIT_EXPORT,
    }
)

# Explicit viewer allowlist. Do NOT auto-derive from ".view" suffix — that
# accidentally grants sensitive read permissions like AUDIT_VIEW. Every
# permission listed here is intentionally safe for read-only role.
_VIEWER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.TEAM_VIEW,
        Permission.BILLING_VIEW,
        Permission.PROJECT_LIST,
        Permission.PROJECT_VIEW,
        Permission.FILE_READ,
        Permission.CONTAINER_VIEW,
        Permission.CHAT_VIEW,
        Permission.DEPLOYMENT_VIEW,
        Permission.GIT_VIEW,
        Permission.KANBAN_VIEW,
        Permission.SNAPSHOT_VIEW,
        Permission.CREDENTIALS_VIEW,
        Permission.CHANNEL_VIEW,
        Permission.MCP_VIEW,
        # Viewers may install connectors for their own personal use. They
        # cannot touch projects they only view (PROJECT_EDIT gate still applies
        # to project-scope overrides).
        Permission.CONNECTORS_MANAGE_USER,
        Permission.AGENT_VIEW,
        Permission.MARKETPLACE_READ,
        Permission.MODELS_PROXY,
        Permission.USAGE_READ,
        Permission.AGENTS_READ,
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "admin": _ALL_PERMISSIONS,
    "editor": _ALL_PERMISSIONS - _ADMIN_ONLY,
    "viewer": _VIEWER_PERMISSIONS,
}


def has_permission(role: str, permission: Permission) -> bool:
    """Return True if *role* grants *permission*."""
    perms = ROLE_PERMISSIONS.get(role)
    if perms is None:
        return False
    return permission in perms


# ---------------------------------------------------------------------------
# Scope labels for API key scope selector UI
# ---------------------------------------------------------------------------

SCOPE_LABELS: dict[str, dict[str, str]] = {
    # Team-level
    Permission.TEAM_VIEW: {"label": "Team — View", "category": "Team"},
    Permission.TEAM_EDIT: {"label": "Team — Edit settings", "category": "Team"},
    Permission.TEAM_DELETE: {"label": "Team — Delete", "category": "Team"},
    Permission.TEAM_INVITE: {"label": "Team — Invite members", "category": "Team"},
    Permission.TEAM_REMOVE_MEMBER: {"label": "Team — Remove members", "category": "Team"},
    Permission.TEAM_CHANGE_ROLE: {"label": "Team — Change roles", "category": "Team"},
    Permission.BILLING_VIEW: {"label": "Billing — View", "category": "Billing"},
    Permission.BILLING_MANAGE: {"label": "Billing — Manage", "category": "Billing"},
    Permission.BILLING_USAGE: {"label": "Billing — View usage", "category": "Billing"},
    # Project-level
    Permission.PROJECT_LIST: {"label": "Projects — List", "category": "Projects"},
    Permission.PROJECT_CREATE: {"label": "Projects — Create", "category": "Projects"},
    Permission.PROJECT_VIEW: {"label": "Projects — View", "category": "Projects"},
    Permission.PROJECT_EDIT: {"label": "Projects — Edit", "category": "Projects"},
    Permission.PROJECT_DELETE: {"label": "Projects — Delete", "category": "Projects"},
    Permission.PROJECT_SETTINGS: {"label": "Projects — Settings", "category": "Projects"},
    # File
    Permission.FILE_READ: {"label": "Files — Read", "category": "Files"},
    Permission.FILE_WRITE: {"label": "Files — Write", "category": "Files"},
    Permission.FILE_DELETE: {"label": "Files — Delete", "category": "Files"},
    # Container
    Permission.CONTAINER_VIEW: {"label": "Containers — View", "category": "Containers"},
    Permission.CONTAINER_CREATE: {"label": "Containers — Create", "category": "Containers"},
    Permission.CONTAINER_EDIT: {"label": "Containers — Edit", "category": "Containers"},
    Permission.CONTAINER_DELETE: {"label": "Containers — Delete", "category": "Containers"},
    Permission.CONTAINER_START_STOP: {"label": "Containers — Start/Stop", "category": "Containers"},
    # Chat / Agent
    Permission.CHAT_VIEW: {"label": "Chat — View messages", "category": "Chat"},
    Permission.CHAT_SEND: {"label": "Chat — Send messages", "category": "Chat"},
    Permission.CHAT_DELETE: {"label": "Chat — Delete", "category": "Chat"},
    # Deployment
    Permission.DEPLOYMENT_VIEW: {"label": "Deployments — View", "category": "Deployments"},
    Permission.DEPLOYMENT_CREATE: {"label": "Deployments — Create", "category": "Deployments"},
    Permission.DEPLOYMENT_DELETE: {"label": "Deployments — Delete", "category": "Deployments"},
    # Git
    Permission.GIT_VIEW: {"label": "Git — View", "category": "Git"},
    Permission.GIT_WRITE: {"label": "Git — Write", "category": "Git"},
    # Kanban
    Permission.KANBAN_VIEW: {"label": "Kanban — View", "category": "Kanban"},
    Permission.KANBAN_EDIT: {"label": "Kanban — Edit", "category": "Kanban"},
    # Snapshot
    Permission.SNAPSHOT_VIEW: {"label": "Snapshots — View", "category": "Snapshots"},
    Permission.SNAPSHOT_CREATE: {"label": "Snapshots — Create", "category": "Snapshots"},
    Permission.SNAPSHOT_RESTORE: {"label": "Snapshots — Restore", "category": "Snapshots"},
    # Terminal
    Permission.TERMINAL_ACCESS: {"label": "Terminal — Access", "category": "Terminal"},
    # Credentials
    Permission.CREDENTIALS_VIEW: {"label": "Credentials — View", "category": "Credentials"},
    Permission.CREDENTIALS_MANAGE: {"label": "Credentials — Manage", "category": "Credentials"},
    Permission.API_KEYS_MANAGE: {"label": "API Keys — Manage", "category": "Credentials"},
    # Channel
    Permission.CHANNEL_VIEW: {"label": "Channels — View", "category": "Channels"},
    Permission.CHANNEL_MANAGE: {"label": "Channels — Manage", "category": "Channels"},
    # MCP
    Permission.MCP_VIEW: {"label": "MCP — View", "category": "MCP"},
    Permission.MCP_MANAGE: {"label": "MCP — Manage", "category": "MCP"},
    # Agent
    Permission.AGENT_VIEW: {"label": "Agents — View", "category": "Agents"},
    Permission.AGENT_MANAGE: {"label": "Agents — Manage", "category": "Agents"},
    # Audit
    Permission.AUDIT_VIEW: {"label": "Audit Log — View", "category": "Audit"},
    Permission.AUDIT_EXPORT: {"label": "Audit Log — Export", "category": "Audit"},
    # Public API
    Permission.MARKETPLACE_READ: {"label": "Marketplace — Read catalog", "category": "Marketplace"},
    Permission.MODELS_PROXY: {"label": "Models — Proxy completions", "category": "Models"},
    Permission.USAGE_READ: {"label": "Usage — View credits & usage", "category": "Usage"},
    # Desktop / external extensions
    Permission.DESKTOP_PAIR: {"label": "Desktop — Pair device", "category": "Desktop"},
    Permission.AGENTS_READ: {"label": "Agents — List & inspect tasks", "category": "Agents"},
    Permission.AGENTS_HANDOFF: {"label": "Agents — Handoff sessions", "category": "Agents"},
    Permission.PROJECTS_SYNC: {"label": "Projects — Sync push/pull", "category": "Projects"},
    Permission.K8S_PROJECTS: {"label": "K8s — Manage cloud projects", "category": "Kubernetes"},
    Permission.MARKETPLACE_INSTALL: {
        "label": "Marketplace — Install items",
        "category": "Marketplace",
    },
    # Apps
    Permission.APP_INVOKE: {
        "label": "Apps — Invoke installed app actions",
        "category": "Apps",
    },
}


# ---------------------------------------------------------------------------
# Core access-check functions
# ---------------------------------------------------------------------------


async def get_team_membership(
    db: AsyncSession,
    team_id: UUID,
    user_id: UUID,
) -> TeamMembership | None:
    """Return the user's *active* membership row in *team_id*, or ``None``."""
    from .models_team import TeamMembership

    result = await db.execute(
        select(TeamMembership).where(
            and_(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user_id,
                TeamMembership.is_active.is_(True),
            )
        )
    )
    return result.scalar_one_or_none()


async def get_platform_settings(
    db: AsyncSession,
    *,
    create: bool = False,
):
    """Return the singleton platform governance row.

    A missing row is treated as the secure enterprise default (both flags
    disabled).  Normal authorization checks stay read-only; only the admin
    write surface requests creation, which keeps ordinary requests from
    unexpectedly provisioning data.
    """
    from .models_team import PlatformSettings

    result = await db.execute(select(PlatformSettings).where(PlatformSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is not None or not create:
        return settings or PlatformSettings(
            id=1,
            automatically_create_personal_teams=False,
            allow_user_team_creation=False,
        )

    settings = PlatformSettings(id=1)
    db.add(settings)
    await db.flush()
    return settings


async def can_create_team(db: AsyncSession, user: User) -> bool:
    """Resolve the server-authoritative team creation capability."""
    if getattr(user, "is_superuser", False):
        return True

    override = getattr(user, "can_create_teams_override", None)
    if override is not None:
        return bool(override)

    settings = await get_platform_settings(db)
    return bool(settings.allow_user_team_creation)


async def can_create_workspace(db: AsyncSession, user: User) -> bool:
    """Resolve the server-authoritative Workspace creation capability.

    Same precedence as :func:`can_create_team`: superuser, then the
    per-user administrator override, then the platform default.
    """
    if getattr(user, "is_superuser", False):
        return True

    override = getattr(user, "can_create_workspaces_override", None)
    if override is not None:
        return bool(override)

    settings = await get_platform_settings(db)
    return bool(settings.allow_user_workspace_creation)


async def require_workspace_creation(db: AsyncSession, user: User) -> None:
    """Raise ``HTTPException(403)`` unless *user* may create a Workspace.

    Every Workspace creation path — empty, from a Base, ZIP / Git import,
    clone, duplicate, Marketplace install or fork, Assist to Build, and the
    direct API — must funnel through this check.  Internal plumbing that
    mints a hidden system Workspace (agent tool scope, automations) is
    deliberately exempt: it is not a user-visible Workspace.
    """
    if await can_create_workspace(db, user):
        return
    raise HTTPException(
        status_code=403,
        detail="Workspace creation is disabled for your account. Contact a platform administrator.",
    )


async def require_agent_task_access(
    task_id: str,
    user_id: UUID,
    db: AsyncSession | None = None,
    permission: Permission = Permission.CHAT_VIEW,
):
    """Authorize access to a running agent task's event stream.

    Agent event streams are keyed by ``task_id`` alone, so anything that
    subscribes to one must first establish that the task belongs to the caller
    — and, when the task is bound to a Workspace and a session is available,
    that the caller still has access to that Workspace (so revoking access
    also cuts the live stream).

    Answers 404 in every failure case: the existence of another user's task is
    itself information.
    """
    from .services.task_manager import get_task_manager

    task = await get_task_manager().get_task_async(task_id)
    if task is None or str(task.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail="Task not found")

    project_id = (task.metadata or {}).get("project_id") if task.metadata else None
    if db is not None and project_id:
        # Raises 404/403 with the same semantics as any other Workspace read.
        await get_project_with_access(db, str(project_id), user_id, permission)

    return task


async def check_team_permission(
    db: AsyncSession,
    team_id: UUID,
    user_id: UUID,
    permission: Permission,
) -> TeamMembership:
    """Verify the user holds *permission* in the given team.

    Returns the ``TeamMembership`` row on success.
    Raises ``HTTPException(403)`` when the check fails.

    Platform superusers (``is_superuser=True``) bypass all checks.
    """
    # --- superuser fast-path ---
    from .models_auth import User

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user and user.is_superuser:
        # Still need a membership object for callers that use it. Fetch if exists,
        # otherwise synthesize a lightweight stand-in is not worth it — just fetch.
        membership = await get_team_membership(db, team_id, user_id)
        if membership is not None:
            return membership
        # Superuser without membership: create a transient object so callers
        # that inspect .role see "admin".
        from .models_team import TeamMembership

        return TeamMembership(
            team_id=team_id,
            user_id=user_id,
            role="admin",
            is_active=True,
        )

    membership = await get_team_membership(db, team_id, user_id)
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this team")

    if not has_permission(membership.role, permission):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{membership.role}' does not have permission '{permission.value}'",
        )

    return membership


async def require_team_feature_access(
    db: AsyncSession,
    user: User,
    *,
    setting_name: str,
    feature_name: str,
    team_id: UUID | None = None,
) -> None:
    """Require access to an opt-in team feature for a non-administrator.

    Team feature settings deliberately complement the existing role system:
    team admins (and platform superusers) always retain access, while editors
    and viewers need the active team's explicit opt-in.  Users without a
    default team are allowed for backwards compatibility with databases that
    predate personal-team provisioning.
    """
    if getattr(user, "is_superuser", False):
        return

    team_id = team_id or getattr(user, "default_team_id", None)
    if team_id is None:
        return

    from .models_team import Team

    team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if team is None:
        # Do not turn a stale legacy team reference into an application-wide
        # lockout. Normal team switching repairs this state.
        return

    membership = await get_team_membership(db, team.id, user.id)
    if membership is not None and membership.role == "admin":
        return
    if membership is not None and bool(getattr(team, setting_name, False)):
        return

    raise HTTPException(
        status_code=403,
        detail=f"{feature_name} is restricted to team administrators",
    )


async def require_active_team_administrator(db: AsyncSession, user: User) -> None:
    """Require an administrator role in the user's active team.

    This is intentionally narrower than feature access: technical provider and
    marketplace-source configuration must never become available just because
    the team has opened the end-user Marketplace catalog.
    """
    if getattr(user, "is_superuser", False):
        return

    team_id = getattr(user, "default_team_id", None)
    if team_id is None:
        raise HTTPException(status_code=403, detail="Team administrator access is required")

    membership = await get_team_membership(db, team_id, user.id)
    if membership is None or membership.role != "admin":
        raise HTTPException(status_code=403, detail="Team administrator access is required")


async def get_effective_project_role(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
) -> str | None:
    """Resolve the effective role a user holds on a project.

    Dual-scope resolution logic:
    1. Check team membership → team_role.
       a. No team membership → check project_memberships only.
       b. Has team membership →
          - team_role == "admin" → return "admin" (admins see everything).
          - Has project_membership → return project_role (override).
          - No project_membership + visibility == "private" → ``None``.
          - No project_membership + visibility == "team" → return team_role.
    """
    # --- superuser fast-path ---
    from .models_auth import User
    from .models_team import ProjectMembership

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user and user.is_superuser:
        return "admin"

    team_membership: TeamMembership | None = None
    if project.team_id is not None:
        team_membership = await get_team_membership(db, project.team_id, user_id)

    # Fetch project-level override (if any)
    proj_membership_result = await db.execute(
        select(ProjectMembership).where(
            and_(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user_id,
                ProjectMembership.is_active.is_(True),
            )
        )
    )
    proj_membership: ProjectMembership | None = proj_membership_result.scalar_one_or_none()

    if team_membership is None:
        # (1a) No team membership — project-level membership is the only path
        if proj_membership is not None:
            return proj_membership.role
        # Legacy compat: owner_id still grants admin
        if project.owner_id == user_id:
            return "admin"
        return None

    # (1b) Has team membership
    if team_membership.role == "admin":
        return "admin"

    if proj_membership is not None:
        return proj_membership.role

    visibility = getattr(project, "visibility", "team") or "team"
    if visibility == "private":
        # Legacy compat: owner always has access
        if project.owner_id == user_id:
            return "admin"
        return None

    # visibility == "team" — inherit team role
    return team_membership.role


def accessible_project_ids(user: User):
    """Return a subquery of the project ids *user* may read.

    The SQL counterpart of :func:`get_effective_project_role`, for endpoints
    that list rows belonging to many projects at once. Filtering must happen in
    the query — a Python-side filter after the fact still loads and counts rows
    the caller cannot see, and a client-side one shows them.

    A superuser matches every project. Everyone else matches a project when they
    own it (legacy compat), hold an explicit project membership, administer its
    team, or the project is team-visible inside a team they actively belong to.
    """
    from .models import Project
    from .models_team import ProjectMembership, TeamMembership

    if getattr(user, "is_superuser", False):
        return select(Project.id)

    own_memberships = select(ProjectMembership.project_id).where(
        and_(
            ProjectMembership.user_id == user.id,
            ProjectMembership.is_active.is_(True),
        )
    )
    admin_team_ids = select(TeamMembership.team_id).where(
        and_(
            TeamMembership.user_id == user.id,
            TeamMembership.is_active.is_(True),
            TeamMembership.role == "admin",
        )
    )
    member_team_ids = select(TeamMembership.team_id).where(
        and_(
            TeamMembership.user_id == user.id,
            TeamMembership.is_active.is_(True),
        )
    )

    return select(Project.id).where(
        or_(
            Project.owner_id == user.id,
            Project.id.in_(own_memberships),
            Project.team_id.in_(admin_team_ids),
            and_(
                Project.team_id.in_(member_team_ids),
                Project.visibility == "team",
            ),
        )
    )


async def get_project_with_access(
    db: AsyncSession,
    project_slug: str,
    user_id: UUID,
    permission: Permission = Permission.PROJECT_VIEW,
) -> tuple:
    """Fetch a project and verify the caller holds *permission* on it.

    This is the **single replacement** for the 25+ scattered ``owner_id`` checks.

    Returns ``(project, effective_role)`` on success.
    Raises:
        HTTPException(404) — project not found.
        HTTPException(403) — user lacks *permission*.
    """
    from .models import Project

    # --- resolve project by UUID or slug ---
    try:
        project_id = UUID(project_slug)
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
    except ValueError:
        result = await db.execute(select(Project).where(Project.slug == project_slug))
        project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    effective_role = await get_effective_project_role(db, project, user_id)

    if effective_role is None:
        # Don't leak existence — 404 for users with zero access
        raise HTTPException(status_code=404, detail="Project not found")

    # A workspace creator remains responsible for the lifecycle of their own
    # workspace. Project deletion is otherwise team-admin-only: this narrow
    # exception never grants an editor the ability to delete a colleague's
    # workspace.
    is_project_owner_deleting_own_workspace = (
        permission == Permission.PROJECT_DELETE and project.owner_id == user_id
    )
    if not has_permission(effective_role, permission) and not is_project_owner_deleting_own_workspace:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{effective_role}' does not have permission '{permission.value}'",
        )

    return project, effective_role

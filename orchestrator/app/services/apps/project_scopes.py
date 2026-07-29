"""Project-vs-App boundary helpers.

Installed app runtimes (`Project.project_kind == PROJECT_KIND_APP_RUNTIME`)
must never appear in the Projects dashboard — they live in the Apps
Dashboard (`/apps/installed`). Every query that returns a collection of
Projects to a user MUST route through `exclude_app_instances_clause()` to
preserve that invariant.

Lookups by Project.id / Project.slug are fine as-is; those are scoped by a
specific identifier, not by collection.
"""

from __future__ import annotations

from sqlalchemy.sql import ColumnElement

from ...models import PROJECT_KIND_APP_RUNTIME, Project


def exclude_app_instances_clause() -> ColumnElement[bool]:
    """Return a WHERE clause that filters out installed-app runtime projects.

    Keeps projects whose `project_kind` is `'workspace'` (regular user
    project) or `'app_source'` (creator studio draft). Excludes
    `'app_runtime'` (installed app runtime mounts, shown in /apps instead).
    """
    return Project.project_kind != PROJECT_KIND_APP_RUNTIME


def only_app_instances_clause() -> ColumnElement[bool]:
    """WHERE clause matching ONLY installed-app runtime projects."""
    return Project.project_kind == PROJECT_KIND_APP_RUNTIME


# Internal system Workspaces. These are plumbing, not user Workspaces: they
# exist purely so project-scoped agent tools (file I/O, bash, credentials) and
# scheduled automations always resolve a valid scope. They are minted lazily by
# `services.lazy_chat_workspace` / `services.automations.lazy_workspace`, are
# exempt from the platform Workspace-creation policy for that reason, and must
# never surface in a user-facing Workspace collection.
INTERNAL_WORKSPACE_CHAT_NAME = "~workspace~"
INTERNAL_WORKSPACE_AUTOMATIONS_NAME = "~automations~"
INTERNAL_WORKSPACE_NAMES: tuple[str, ...] = (
    INTERNAL_WORKSPACE_CHAT_NAME,
    INTERNAL_WORKSPACE_AUTOMATIONS_NAME,
)


def exclude_internal_workspaces_clause() -> ColumnElement[bool]:
    """WHERE clause filtering out lazily-minted internal system Workspaces.

    Pair with `exclude_app_instances_clause()` on every query that returns a
    Workspace collection to a user, so no Workspace the user never asked for
    appears in their list.
    """
    return Project.name.notin_(INTERNAL_WORKSPACE_NAMES)

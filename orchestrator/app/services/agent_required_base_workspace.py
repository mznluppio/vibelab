"""Provision the project required by a direct chat agent, when needed.

Standalone chats start on a lightweight per-user ``~workspace~`` so ordinary
assistant conversations do not incur a project/template setup. Build agents
may declare ``config.required_base`` instead. This module turns that
declaration into a real project before their model gets file or project tools,
while deliberately never replacing a user-selected project.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ..models import PROJECT_KIND_WORKSPACE, Chat, Container, MarketplaceBase, Project

DEFAULT_CHAT_WORKSPACE_NAME = "~workspace~"
_SETUP_WAIT_SECONDS = 240


class RequiredBaseWorkspaceError(RuntimeError):
    """The current chat is linked to a real project with the wrong base."""


@dataclass(frozen=True)
class RequiredBaseWorkspaceResult:
    """Resolved chat project and whether this turn provisioned it."""

    project: Project
    base: MarketplaceBase
    created: bool
    setup_task_id: str | None = None


async def resolve_required_base(
    db, required_base_config: Any
) -> MarketplaceBase | None:
    """Resolve an optional agent Base reference against the active catalog."""
    if not isinstance(required_base_config, dict):
        return None

    base_id = required_base_config.get("id")
    base_slug = required_base_config.get("slug")
    base: MarketplaceBase | None = None
    if base_id:
        try:
            base = await db.get(MarketplaceBase, UUID(str(base_id)))
        except (TypeError, ValueError):
            return None
    elif isinstance(base_slug, str) and base_slug:
        result = await db.execute(
            select(MarketplaceBase)
            .where(
                MarketplaceBase.slug == base_slug,
                MarketplaceBase.is_active.is_(True),
                MarketplaceBase.deleted_upstream.is_(False),
            )
            .limit(1)
        )
        base = result.scalar_one_or_none()

    if base is None or not base.is_active or base.deleted_upstream:
        return None
    return base


async def project_uses_base(db, project: Project, base_id: UUID) -> bool:
    """Return whether a project was created from, or contains, a Base."""
    source_base = (project.settings or {}).get("source_base")
    if isinstance(source_base, dict) and str(source_base.get("id")) == str(base_id):
        return True

    result = await db.execute(
        select(Container.id)
        .where(Container.project_id == project.id, Container.base_id == base_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


def is_default_chat_workspace(project: Project, user_id: UUID) -> bool:
    """Identify the disposable chat attachment, never an arbitrary project."""
    return (
        project.owner_id == user_id
        and project.name == DEFAULT_CHAT_WORKSPACE_NAME
        and project.project_kind == PROJECT_KIND_WORKSPACE
        and project.created_via == "empty"
    )


async def _wait_for_project_setup(task_id: str) -> None:
    """Wait asynchronously until the existing project setup pipeline is ready."""
    from .task_manager import TaskStatus, get_task_manager

    task_manager = get_task_manager()
    for _ in range(_SETUP_WAIT_SECONDS):
        task = await task_manager.get_task_async(task_id)
        if task and task.status == TaskStatus.COMPLETED:
            return
        if task and task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            raise RuntimeError(task.error or "Base setup did not complete")
        await asyncio.sleep(1)
    raise TimeoutError("Timed out while preparing the required Base")


async def create_project_from_required_base(
    db,
    *,
    user_id: UUID,
    base: MarketplaceBase,
    name: str,
) -> Project:
    """Create a project through the shared project-create pipeline."""
    from ..models_auth import User
    from ..routers.projects import create_project_from_payload
    from ..schemas import ProjectCreate

    user = await db.get(User, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")

    result = await create_project_from_payload(
        ProjectCreate(name=name, source_type="base", base_id=base.id),
        current_user=user,
        db=db,
    )
    project = result["project"]
    if result["task_id"]:
        await _wait_for_project_setup(result["task_id"])
        await db.refresh(project)
    return project


async def begin_project_from_required_base(
    db,
    *,
    user_id: UUID,
    base: MarketplaceBase,
    name: str,
) -> tuple[Project, str | None]:
    """Start the normal Base setup pipeline without waiting for it.

    The setup task already owns filesystem/template materialisation.  Agent
    workers must not spend their execution slot polling it; callers can defer
    their own task until the returned task reaches a terminal state.
    """
    from ..models_auth import User
    from ..routers.projects import create_project_from_payload
    from ..schemas import ProjectCreate

    user = await db.get(User, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")

    result = await create_project_from_payload(
        ProjectCreate(name=name, source_type="base", base_id=base.id),
        current_user=user,
        db=db,
    )
    return result["project"], result.get("task_id")


async def ensure_chat_project_for_required_base(
    db,
    *,
    user_id: UUID,
    chat_id: UUID,
    required_base_config: Any,
    project_name: str | None = None,
    wait_for_setup: bool = True,
) -> RequiredBaseWorkspaceResult | None:
    """Ensure a direct chat has a project matching its agent's required Base."""
    if not required_base_config:
        return None

    base = await resolve_required_base(db, required_base_config)
    if base is None:
        raise RequiredBaseWorkspaceError("The agent's required Base is no longer available")

    chat = await db.get(Chat, chat_id)
    if chat is None:
        raise RequiredBaseWorkspaceError(f"Chat {chat_id} not found")

    project = await db.get(Project, chat.project_id) if chat.project_id else None
    if project is not None and await project_uses_base(db, project, base.id):
        return RequiredBaseWorkspaceResult(project=project, base=base, created=False)

    if project is not None and not is_default_chat_workspace(project, user_id):
        raise RequiredBaseWorkspaceError(
            f"This chat is connected to '{project.name}', which does not use the required "
            f"{base.name} Base. Connect a matching project instead."
        )

    name = (project_name or "").strip() or f"New {base.name} project"
    if wait_for_setup:
        created = await create_project_from_required_base(
            db, user_id=user_id, base=base, name=name
        )
        setup_task_id = None
    else:
        created, setup_task_id = await begin_project_from_required_base(
            db, user_id=user_id, base=base, name=name
        )
    chat.project_id = created.id
    await db.commit()
    await db.refresh(created)
    return RequiredBaseWorkspaceResult(
        project=created,
        base=base,
        created=True,
        setup_task_id=setup_task_id,
    )


__all__ = [
    "DEFAULT_CHAT_WORKSPACE_NAME",
    "RequiredBaseWorkspaceError",
    "RequiredBaseWorkspaceResult",
    "create_project_from_required_base",
    "begin_project_from_required_base",
    "ensure_chat_project_for_required_base",
    "is_default_chat_workspace",
    "project_uses_base",
    "resolve_required_base",
]

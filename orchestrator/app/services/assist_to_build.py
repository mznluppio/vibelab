"""Server-side safety policy for the fixed Assist to Build chat workflow."""

from __future__ import annotations

from typing import Any
from sqlalchemy import or_, select

ASSIST_TO_BUILD_AGENT_SLUG = "assist-to-build"
ASSIST_TO_BUILD_REVIEW_TOOL = "request_assist_to_build_review"

# This is deliberately an allow-list. New tools, MCP bridges, app actions, and
# shell aliases remain denied until TO-BE has been explicitly approved.
PRE_BUILD_ALLOWED_TOOLS = frozenset(
    {
        "read_file",
        "read_many_files",
        "view_image",
        "glob",
        "grep",
        "list_dir",
        "git_log",
        "git_status",
        "git_diff",
        "git_blame",
        "get_project_info",
        "memory_read",
        "memory_write",
        "todo_read",
        "todo_write",
        "save_plan",
        "update_plan",
        "web_fetch",
        "web_search",
        "load_skill",
        ASSIST_TO_BUILD_REVIEW_TOOL,
    }
)

# The marketplace declaration is the maximal capability envelope.  The model
# only sees the pre-build subset until TO-BE approval; ``block_pre_build_tool``
# remains the execution-time backstop for stale or hallucinated calls.
ASSIST_BUILD_TOOLS = PRE_BUILD_ALLOWED_TOOLS | frozenset(
    {
        "write_file",
        "patch_file",
        "multi_edit",
        "apply_patch",
        "bash_exec",
        "shell_open",
        "shell_exec",
        "write_stdin",
        "read_background_output",
        "list_background_processes",
        "apply_setup_config",
        "project_start",
        "project_restart",
        "project_control",
    }
)


def model_visible_tools(context: dict[str, Any]) -> frozenset[str] | None:
    """Return the Assist-only model capability slice for this iteration."""
    if not is_assist_to_build_context(context):
        return None
    return ASSIST_BUILD_TOOLS if is_build_unlocked(context) else PRE_BUILD_ALLOWED_TOOLS


async def ensure_assist_build_workspace(context: dict[str, Any]) -> dict[str, Any]:
    """Create and attach the configured Base using the existing project pipeline.

    Discovery deliberately remains project-less. This helper is called only
    once TO-BE has been approved, so it never leaves an empty default workspace
    attached to an Assist conversation.
    """
    from ..models import Chat, MarketplaceAgent, MarketplaceBase, Project, UserPurchasedBase
    from ..models_auth import User
    from ..routers.projects import create_project_from_payload
    from ..schemas import ProjectCreate

    db = context.get("db")
    user_id = context.get("user_id")
    chat_id = context.get("chat_id")
    if db is None or not user_id or not chat_id:
        raise RuntimeError("missing Assist workspace context")

    chat = await db.get(Chat, chat_id)
    if chat is None:
        raise RuntimeError("chat unavailable")
    if chat.project_id:
        project = await db.get(Project, chat.project_id)
        if project is None:
            raise RuntimeError("attached workspace unavailable")
    else:
        agent = await db.get(MarketplaceAgent, context.get("agent_id"))
        config = agent.config if agent and isinstance(agent.config, dict) else {}
        base_slug = config.get("default_base_slug")
        if not isinstance(base_slug, str) or not base_slug:
            raise RuntimeError("starter base is not configured")
        user = await db.get(User, user_id)
        if user is None:
            raise RuntimeError("user unavailable")
        ownership = [UserPurchasedBase.user_id == user.id]
        if user.default_team_id:
            ownership.append(UserPurchasedBase.team_id == user.default_team_id)
        base = await db.scalar(
            select(MarketplaceBase)
            .join(UserPurchasedBase, UserPurchasedBase.base_id == MarketplaceBase.id)
            .where(
                MarketplaceBase.slug == base_slug,
                MarketplaceBase.is_active.is_(True),
                UserPurchasedBase.is_active.is_(True),
                or_(*ownership),
            )
            .limit(1)
        )
        if base is None:
            raise RuntimeError("configured starter base is unavailable")
        created = await create_project_from_payload(
            ProjectCreate(name="VibeLab application", source_type="base", base_id=base.id),
            current_user=user,
            db=db,
        )
        project = created["project"]
        chat.project_id = project.id
        await db.commit()
        await db.refresh(project)

    context.update(
        {
            "project_id": project.id,
            "project_slug": project.slug,
            "volume_id": project.volume_id,
            "compute_tier": project.compute_tier,
            "environment_status": project.environment_status,
            "container_id": None,
            "container_name": None,
            "container_directory": None,
        }
    )
    return {"project_id": str(project.id), "project_slug": project.slug}


def is_assist_to_build_context(context: dict[str, Any]) -> bool:
    workflow = context.get("assist_to_build_workflow")
    return isinstance(workflow, dict) and workflow.get("workflow") == "assist_to_build"


def is_build_unlocked(context: dict[str, Any]) -> bool:
    workflow = context.get("assist_to_build_workflow")
    return isinstance(workflow, dict) and workflow.get("to_be_approved") is True


def merge_workflow_metadata(
    metadata: dict[str, Any] | None, workflow_context: dict[str, Any] | None
) -> dict[str, Any]:
    """Preserve Assist to Build review history while snapshotting its live state."""
    merged_metadata = dict(metadata or {})
    if (
        not isinstance(workflow_context, dict)
        or workflow_context.get("workflow") != "assist_to_build"
    ):
        return merged_metadata

    existing = merged_metadata.get("assist_to_build_workflow")
    workflow = dict(existing) if isinstance(existing, dict) else {}
    checkpoints = list(workflow.get("checkpoints") or [])
    workflow.update({key: value for key, value in workflow_context.items() if key != "checkpoints"})
    workflow["checkpoints"] = checkpoints
    merged_metadata["assist_to_build_workflow"] = workflow
    return merged_metadata


def block_pre_build_tool(tool_name: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Return a registry-compatible denial before any edit-mode handling."""
    if not is_assist_to_build_context(context) or is_build_unlocked(context):
        return None
    if tool_name in PRE_BUILD_ALLOWED_TOOLS:
        return None
    return {
        "success": False,
        "tool": tool_name,
        "error": (
            "Assist to Build is in discovery/review mode. "
            "Only read, research, planning, memory, and process-review tools are allowed "
            "until the TO-BE checkpoint is approved."
        ),
        "workflow_guard": "assist_to_build_pre_build",
    }

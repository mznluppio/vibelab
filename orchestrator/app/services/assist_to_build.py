"""Server-side safety policy for the fixed Assist to Build chat workflow."""

from __future__ import annotations

from typing import Any

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


def is_assist_to_build_context(context: dict[str, Any]) -> bool:
    workflow = context.get("assist_to_build_workflow")
    return isinstance(workflow, dict) and workflow.get("workflow") == "assist_to_build"


def is_build_unlocked(context: dict[str, Any]) -> bool:
    workflow = context.get("assist_to_build_workflow")
    return isinstance(workflow, dict) and workflow.get("to_be_approved") is True


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

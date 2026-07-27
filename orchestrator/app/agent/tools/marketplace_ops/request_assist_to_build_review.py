"""Pause an Assist to Build run at an AS-IS or TO-BE process checkpoint."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from ....models import Message
from ..approval_manager import get_pending_input_manager
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)

_STAGES = {"as_is", "to_be"}
_RESPONSES = {
    "as_is": {"approve_as_is", "request_changes"},
    "to_be": {"approve_to_be_and_build", "request_changes"},
}


async def _persist_checkpoint(context: dict[str, Any], checkpoint: dict[str, Any]) -> None:
    """Attach workflow history to the in-flight assistant message when available."""
    db = context.get("db")
    message_id = context.get("assistant_message_id")
    if db is None or not message_id:
        return
    try:
        message_uuid = message_id if isinstance(message_id, UUID) else UUID(str(message_id))
        message = (await db.execute(select(Message).where(Message.id == message_uuid))).scalar_one_or_none()
        if message is None:
            return
        metadata = dict(message.message_metadata or {})
        workflow = dict(metadata.get("assist_to_build_workflow") or {"workflow": "assist_to_build"})
        checkpoints = list(workflow.get("checkpoints") or [])
        checkpoints.append(checkpoint)
        workflow.update({"stage": checkpoint["stage"], "checkpoints": checkpoints})
        metadata["assist_to_build_workflow"] = workflow
        message.message_metadata = metadata
        await db.commit()
    except Exception:
        logger.exception("Unable to persist Assist to Build checkpoint")


async def request_assist_to_build_review_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    workflow = context.get("assist_to_build_workflow")
    if not isinstance(workflow, dict) or workflow.get("workflow") != "assist_to_build":
        return error_output(message="request_assist_to_build_review is only available to Assist to Build")

    stage = params.get("stage")
    if stage not in _STAGES:
        return error_output(message="stage must be 'as_is' or 'to_be'")
    if stage == "to_be" and not workflow.get("as_is_approved"):
        return error_output(message="AS-IS must be approved before requesting TO-BE approval")

    title = str(params.get("title") or ("Validate AS-IS process" if stage == "as_is" else "Validate TO-BE process"))
    summary_markdown = str(params.get("summary_markdown") or "")
    if not summary_markdown.strip():
        return error_output(message="summary_markdown is required")

    payload = {
        "stage": stage,
        "title": title,
        "summary_markdown": summary_markdown,
        "mermaid": str(params.get("mermaid") or "") or None,
        "assumptions": list(params.get("assumptions") or []),
        "risks": list(params.get("risks") or []),
        "requirements": list(params.get("requirements") or []),
        "actions": (
            ["approve_as_is", "request_changes"]
            if stage == "as_is"
            else ["approve_to_be_and_build", "request_changes"]
        ),
    }
    session_id = str(context.get("chat_id") or context.get("session_id") or "unknown")
    input_id = str(uuid4())
    manager = get_pending_input_manager()
    request = await manager.create_input_request(
        input_id=input_id,
        kind="assist_to_build_review",
        session_id=session_id,
        metadata=payload,
        ttl=600,
    )
    await _persist_checkpoint(context, {**payload, "approval_id": input_id, "response": None})

    pubsub = context.get("pubsub")
    task_id = context.get("task_id")
    if pubsub is not None and task_id:
        await pubsub.publish_agent_event(
            task_id,
            {
                "type": "approval_required",
                "data": {
                    "approval_id": input_id,
                    "kind": "assist_to_build_review",
                    "stage": stage,
                    "summary": payload,
                    "session_id": session_id,
                },
            },
        )

    response_data = await manager.await_input(input_id, timeout=600)
    comment = response_data.get("comment") if isinstance(response_data, dict) else None
    response = response_data.get("response") if isinstance(response_data, dict) else response_data
    if not isinstance(response, str) or response not in _RESPONSES[stage]:
        return error_output(message="Assist to Build review was cancelled or timed out", stage=stage)

    if response == "approve_as_is":
        workflow["as_is_approved"] = True
        workflow["stage"] = "to_be"
    elif response == "approve_to_be_and_build":
        workflow["to_be_approved"] = True
        workflow["stage"] = "build"
    else:
        workflow["stage"] = stage
    await _persist_checkpoint(context, {**payload, "approval_id": input_id, "response": response, "comment": comment})
    return success_output(
        message=(
            "AS-IS approved; prepare the TO-BE proposal."
            if response == "approve_as_is"
            else "TO-BE approved; the normal project editing policy is now restored."
            if response == "approve_to_be_and_build"
            else f"Revise only the {stage.replace('_', '-').upper()} checkpoint and request review again."
        ),
        stage=stage,
        outcome=response,
        approval_id=input_id,
        comment=comment,
    )


def register_request_assist_to_build_review_tool(registry) -> None:
    registry.register(
        Tool(
            name="request_assist_to_build_review",
            description="Show the required AS-IS or TO-BE process checkpoint and wait for the user's response.",
            category=ToolCategory.PLANNING,
            parameters={
                "type": "object",
                "properties": {
                    "stage": {"type": "string", "enum": ["as_is", "to_be"]},
                    "title": {"type": "string"},
                    "summary_markdown": {"type": "string"},
                    "mermaid": {"type": "string"},
                    "assumptions": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "requirements": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["stage", "summary_markdown"],
            },
            executor=request_assist_to_build_review_executor,
        )
    )

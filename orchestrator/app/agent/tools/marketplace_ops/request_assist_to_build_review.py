"""Pause an Assist to Build run at an AS-IS or TO-BE process checkpoint."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from ....models import Message
from ....services.assist_to_build import merge_workflow_metadata
from ..approval_manager import get_pending_input_manager
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)

_STAGES = {"as_is", "to_be"}
_RESPONSES = {
    "as_is": {"approve_as_is", "request_changes"},
    "to_be": {"approve_to_be_and_build", "request_changes"},
}
_DIAGRAM_PRESETS = {"technical-dark", "editorial-comparison", "business-process"}
_DIAGRAM_DIRECTIONS = {"LR", "RL", "TB", "BT"}
_DIAGRAM_NODE_TYPES = {
    "start", "end", "step", "decision", "actor", "system", "tool", "action", "output", "note"
}
_DIAGRAM_ICONS = {"app", "user", "bot", "database", "tool", "message", "shield", "check", "sparkle", "globe"}
_ROOT_KEYS = {"title", "subtitle", "preset", "direction", "nodes", "edges", "groups", "annotations"}
_NODE_KEYS = {"id", "type", "label", "description", "icon", "groupId", "emphasis"}
_EDGE_KEYS = {"source", "target", "label", "variant", "animated"}
_GROUP_KEYS = {"id", "label", "description", "variant"}
_ANNOTATION_KEYS = {"id", "nodeId", "label", "tone"}
_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")

# This is the tool-facing form of the same deliberately small contract that
# ``_validate_workflow_diagram`` persists and VibeLabDiagram renders.  Keep
# it explicit: a bare ``object`` schema caused models to fall back to the
# legacy ``type/process/from`` diagram shape.
_WORKFLOW_DIAGRAM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "preset", "direction", "nodes", "edges"],
    "properties": {
        "title": {"type": "string", "description": "Short diagram title (1-120 characters)."},
        "subtitle": {"type": "string", "description": "Optional context (1-180 characters)."},
        "preset": {"type": "string", "enum": sorted(_DIAGRAM_PRESETS)},
        "direction": {"type": "string", "enum": sorted(_DIAGRAM_DIRECTIONS)},
        "nodes": {
            "type": "array",
            "minItems": 3,
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "type", "label"],
                "properties": {
                    "id": {"type": "string", "description": "Unique slug-like node identifier."},
                    "type": {"type": "string", "enum": sorted(_DIAGRAM_NODE_TYPES)},
                    "label": {"type": "string", "description": "Short visible node label."},
                    "description": {"type": "string"},
                    "icon": {"type": "string", "enum": sorted(_DIAGRAM_ICONS)},
                    "groupId": {"type": "string"},
                    "emphasis": {"type": "boolean"},
                },
            },
        },
        "edges": {
            "type": "array",
            "minItems": 1,
            "maxItems": 60,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source", "target"],
                "properties": {
                    "source": {"type": "string", "description": "Source node id (never `from`)."},
                    "target": {"type": "string", "description": "Target node id (never `to`)."},
                    "label": {"type": "string"},
                    "variant": {"type": "string", "enum": ["solid", "dashed", "dotted"]},
                    "animated": {"type": "boolean"},
                },
            },
        },
        "groups": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "label"],
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "description": {"type": "string"},
                    "variant": {"type": "string", "enum": ["default", "muted", "highlight"]},
                },
            },
        },
        "annotations": {
            "type": "array",
            "maxItems": 30,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "nodeId", "label"],
                "properties": {
                    "id": {"type": "string"},
                    "nodeId": {"type": "string"},
                    "label": {"type": "string"},
                    "tone": {"type": "string", "enum": ["info", "success", "warning"]},
                },
            },
        },
    },
}

_WORKFLOW_DIAGRAM_EXAMPLE = {
    "title": "Current status reporting",
    "preset": "business-process",
    "direction": "LR",
    "nodes": [
        {"id": "monitor", "type": "system", "label": "Monitor service"},
        {"id": "incident", "type": "decision", "label": "Incident detected?"},
        {"id": "notify", "type": "action", "label": "Notify employees"},
    ],
    "edges": [
        {"source": "monitor", "target": "incident"},
        {"source": "incident", "target": "notify", "label": "Yes"},
    ],
}


def _is_safe_text(value: Any, maximum: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum and not any(
        char in value for char in "<>`"
    )


def _has_banned_diagram_content(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(token in lowered for token in ("javascript:", "<script", "<svg", "</"))
    if isinstance(value, list):
        return any(_has_banned_diagram_content(item) for item in value)
    if not isinstance(value, dict):
        return False
    banned_keys = {
        "style", "classname", "css", "color", "background", "position", "x", "y", "width",
        "height", "html", "svg", "javascript", "url", "callback",
    }
    return any(key.lower() in banned_keys or _has_banned_diagram_content(item) for key, item in value.items())


def _validate_workflow_diagram(diagram: Any) -> str | None:
    """Strict server counterpart to the presentation-safe VibeLab diagram contract."""
    if not isinstance(diagram, dict):
        return f"diagram: expected an object, received {type(diagram).__name__}"
    if set(diagram) - _ROOT_KEYS or _has_banned_diagram_content(diagram):
        unsupported = sorted(set(diagram) - _ROOT_KEYS)
        if unsupported:
            return f"diagram: unsupported keys {unsupported}; allowed keys are {sorted(_ROOT_KEYS)}"
        return "diagram: unsupported presentation content"
    nodes = diagram.get("nodes")
    edges = diagram.get("edges")
    groups = diagram.get("groups", [])
    annotations = diagram.get("annotations", [])
    if (
        not _is_safe_text(diagram.get("title"), 120)
        or not isinstance(diagram.get("preset"), str)
        or diagram["preset"] not in _DIAGRAM_PRESETS
        or not isinstance(diagram.get("direction"), str)
        or diagram["direction"] not in _DIAGRAM_DIRECTIONS
        or not isinstance(nodes, list)
        or not isinstance(edges, list)
        or not isinstance(groups, list)
        or not isinstance(annotations, list)
    ):
        return "diagram: expected title, preset, direction, nodes and edges using the VibeLab schema"
    if "subtitle" in diagram and not _is_safe_text(diagram["subtitle"], 180):
        return "diagram subtitle is invalid"
    if not 3 <= len(nodes) <= 12 or not edges or len(edges) > 60 or len(groups) > 12 or len(annotations) > 30:
        return "diagram.nodes: expected 3 to 12 nodes and diagram.edges: expected at least one connection"

    node_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict) or set(node) - _NODE_KEYS:
            return "diagram.nodes: expected objects with only id, type, label, description, icon, groupId and emphasis"
        node_id = node.get("id")
        if (
            not isinstance(node_id, str)
            or not _SAFE_ID.fullmatch(node_id)
            or not _is_safe_text(node.get("label"), 80)
            or node.get("type") not in _DIAGRAM_NODE_TYPES
            or ("description" in node and not _is_safe_text(node["description"], 180))
            or ("icon" in node and node["icon"] not in _DIAGRAM_ICONS)
            or ("groupId" in node and not isinstance(node["groupId"], str))
            or ("emphasis" in node and not isinstance(node["emphasis"], bool))
            or node_id in node_ids
        ):
            return f"diagram.nodes[{len(node_ids)}]: expected a valid id, VibeLab node type and short label"
        node_ids.add(node_id)

    for edge in edges:
        if not isinstance(edge, dict) or set(edge) - _EDGE_KEYS:
            return "diagram.edges: expected objects with source and target (never from/to)"
        if (
            edge.get("source") not in node_ids
            or edge.get("target") not in node_ids
            or ("label" in edge and not _is_safe_text(edge["label"], 80))
            or ("variant" in edge and edge["variant"] not in {"solid", "dashed", "dotted"})
            or ("animated" in edge and not isinstance(edge["animated"], bool))
        ):
            return "diagram.edges: expected source and target to reference existing node ids"

    group_ids = set()
    for group in groups:
        if (
            not isinstance(group, dict)
            or set(group) - _GROUP_KEYS
            or not isinstance(group.get("id"), str)
            or not _SAFE_ID.fullmatch(group["id"])
        ):
            return "diagram.groups: expected objects with id and label"
        if group["id"] in group_ids or not _is_safe_text(group.get("label"), 80):
            return "diagram.groups: expected unique valid group ids and labels"
        if ("description" in group and not _is_safe_text(group["description"], 180)) or (
            "variant" in group and group["variant"] not in {"default", "muted", "highlight"}
        ):
            return "diagram.groups: expected an optional valid description and variant"
        group_ids.add(group["id"])
    if any(node.get("groupId") not in group_ids for node in nodes if "groupId" in node):
        return "diagram.nodes[].groupId: expected a group id declared in diagram.groups"

    for annotation in annotations:
        if not isinstance(annotation, dict) or set(annotation) - _ANNOTATION_KEYS:
            return "diagram.annotations: expected objects with id, nodeId and label"
        if (
            not _is_safe_text(annotation.get("id"), 64)
            or annotation.get("nodeId") not in node_ids
            or not _is_safe_text(annotation.get("label"), 80)
            or ("tone" in annotation and annotation["tone"] not in {"info", "success", "warning"})
        ):
            return "diagram.annotations: expected nodeId to reference an existing node"
    return None


def _validate_string_list(value: Any, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return f"{path}: expected an array of strings"
    return None


async def _persist_checkpoint(context: dict[str, Any], checkpoint: dict[str, Any]) -> None:
    """Attach workflow history to the in-flight assistant message when available."""
    db = context.get("db")
    message_id = context.get("assistant_message_id")
    if db is None or not message_id:
        return
    try:
        message_uuid = message_id if isinstance(message_id, UUID) else UUID(str(message_id))
        message = (
            await db.execute(select(Message).where(Message.id == message_uuid))
        ).scalar_one_or_none()
        if message is None:
            return
        metadata = merge_workflow_metadata(
            message.message_metadata,
            context.get("assist_to_build_workflow"),
        )
        workflow = dict(metadata["assist_to_build_workflow"])
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
        return error_output(
            message="request_assist_to_build_review is only available to Assist to Build"
        )

    stage = params.get("stage")
    if stage not in _STAGES:
        return error_output(message="stage must be 'as_is' or 'to_be'")
    if stage == "to_be" and not workflow.get("as_is_approved"):
        return error_output(message="AS-IS must be approved before requesting TO-BE approval")

    title = str(
        params.get("title")
        or ("Validate AS-IS process" if stage == "as_is" else "Validate TO-BE process")
    )
    summary_markdown = str(params.get("summary_markdown") or "")
    if not summary_markdown.strip():
        return error_output(message="summary_markdown is required")
    diagram_error = _validate_workflow_diagram(params.get("diagram"))
    if diagram_error:
        return error_output(
            message=(
                f"Validation failed at {diagram_error}. Return the complete {stage.replace('_', '-').upper()} "
                "artifact with a valid diagram matching this exact tool schema. Keep summary_markdown, "
                "assumptions, risks and requirements unchanged unless this validation requires a change."
            ),
            suggestion=(
                "Use title, preset, direction, nodes and edges; nodes use id/type/label and edges use "
                "source/target. Do not send legacy type/process/data/from/to fields."
            ),
            stage=stage,
        )
    for field_name in ("assumptions", "risks", "requirements"):
        field_error = _validate_string_list(params.get(field_name), field_name)
        if field_error:
            return error_output(
                message=(
                    f"Validation failed at {field_error}. Return the complete {stage.replace('_', '-').upper()} "
                    "artifact and keep every valid field unchanged."
                ),
                stage=stage,
            )

    payload = {
        "stage": stage,
        "title": title,
        "summary_markdown": summary_markdown,
        "diagram": params["diagram"],
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
    await manager.create_input_request(
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
        return error_output(
            message="Assist to Build review was cancelled or timed out", stage=stage
        )

    if response == "approve_as_is":
        workflow["as_is_approved"] = True
        workflow["stage"] = "to_be"
    elif response == "approve_to_be_and_build":
        workflow["to_be_approved"] = True
        workflow["stage"] = "build"
    else:
        workflow["stage"] = stage
    await _persist_checkpoint(
        context, {**payload, "approval_id": input_id, "response": response, "comment": comment}
    )
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
            description=(
                "Show the required AS-IS or TO-BE process checkpoint and wait for the user's response. "
                "diagram is a strict VibeLab workflow object: title, preset, direction, 3-12 nodes and "
                "at least one edge are required. Nodes use id/type/label; edges use source/target. "
                "Unknown fields, coordinates, styles, CSS, HTML, SVG, JavaScript and legacy type/process/data/from/to fields are forbidden."
            ),
            category=ToolCategory.PLANNING,
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "stage": {"type": "string", "enum": ["as_is", "to_be"]},
                    "title": {"type": "string"},
                    "summary_markdown": {"type": "string"},
                    "diagram": _WORKFLOW_DIAGRAM_SCHEMA,
                    "assumptions": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "requirements": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["stage", "summary_markdown", "diagram"],
            },
            executor=request_assist_to_build_review_executor,
            examples=[
                "Valid diagram: " + json.dumps(_WORKFLOW_DIAGRAM_EXAMPLE),
            ],
            # The checkpoint payload and final review outcome are JSON-clean.
            state_serializable=True,
            # The DB-backed approval wait owns no socket, PTY, or process handle.
            holds_external_state=False,
        )
    )

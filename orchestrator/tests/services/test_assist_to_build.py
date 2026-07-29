"""Unit coverage for the fixed Assist to Build process gates."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.tools.marketplace_ops import request_assist_to_build_review as review_tool
from app.agent.tools.registry import ToolRegistry
from app.services.assist_to_build import block_pre_build_tool, merge_workflow_metadata


def _workflow(**extra):
    return {
        "assist_to_build_workflow": {
            "workflow": "assist_to_build",
            "stage": "discovery",
            "as_is_approved": False,
            "to_be_approved": False,
            **extra,
        }
    }


def _diagram():
    return {
        "title": "Current workflow",
        "preset": "business-process",
        "direction": "LR",
        "nodes": [
            {"id": "start", "type": "start", "label": "Request"},
            {"id": "review", "type": "step", "label": "Manual review"},
            {"id": "end", "type": "end", "label": "Complete"},
        ],
        "edges": [
            {"source": "start", "target": "review"},
            {"source": "review", "target": "end"},
        ],
    }


def test_pre_build_guard_blocks_mutation_even_in_allow_mode():
    context = {**_workflow(), "edit_mode": "allow"}
    denied = block_pre_build_tool("write_file", context)
    assert denied and denied["workflow_guard"] == "assist_to_build_pre_build"
    assert block_pre_build_tool("read_file", context) is None
    assert block_pre_build_tool("mcp__unknown__mutate", context) is not None


def test_assist_to_build_review_tool_declares_checkpoint_annotations():
    registry = ToolRegistry()
    review_tool.register_request_assist_to_build_review_tool(registry)

    tool = registry.get("request_assist_to_build_review")
    assert tool is not None
    assert tool.state_serializable is True
    assert tool.holds_external_state is False
    diagram_schema = tool.parameters["properties"]["diagram"]
    assert diagram_schema["required"] == ["title", "preset", "direction", "nodes", "edges"]
    assert diagram_schema["additionalProperties"] is False
    assert diagram_schema["properties"]["nodes"]["items"]["required"] == ["id", "type", "label"]
    assert diagram_schema["properties"]["edges"]["items"]["required"] == ["source", "target"]
    assert "source/target" in tool.description
    assert "legacy type/process/data/from/to" in tool.description


@pytest.mark.asyncio
async def test_assist_to_build_runtime_only_exposes_declared_tools():
    from app.worker import _create_agent_runner

    agent_model = SimpleNamespace(
        slug="assist-to-build",
        system_prompt="Assist to Build",
        tools=["read_file", "request_assist_to_build_review"],
        tool_configs=None,
        config=None,
    )
    runner = await _create_agent_runner(
        agent_model=agent_model,
        model_adapter=None,
        tools_override=None,
        settings=SimpleNamespace(compaction_summary_model=""),
    )

    assert runner.tools.get("request_assist_to_build_review") is not None
    assert runner.tools.get("request_workspace") is None


def test_pre_build_guard_releases_only_after_to_be_approval():
    context = _workflow(to_be_approved=True, stage="build")
    assert block_pre_build_tool("write_file", context) is None


def test_workflow_metadata_keeps_checkpoints_and_final_approval_state():
    context = _workflow(as_is_approved=True, to_be_approved=True, stage="build")
    metadata = merge_workflow_metadata(
        {
            "agent_mode": True,
            "assist_to_build_workflow": {
                "workflow": "assist_to_build",
                "stage": "as_is",
                "checkpoints": [{"stage": "as_is", "approval_id": "review-1"}],
            },
        },
        context["assist_to_build_workflow"],
    )

    workflow = metadata["assist_to_build_workflow"]
    assert workflow["stage"] == "build"
    assert workflow["as_is_approved"] is True
    assert workflow["to_be_approved"] is True
    assert workflow["checkpoints"] == [{"stage": "as_is", "approval_id": "review-1"}]


class _FakeManager:
    def __init__(self, response: str):
        self.response = response
        self.created: dict | None = None

    async def create_input_request(self, **kwargs):
        self.created = kwargs
        return object()

    async def await_input(self, input_id: str, timeout: float):
        assert input_id == self.created["input_id"]
        assert timeout == 600
        return self.response


class _FakePubSub:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def publish_agent_event(self, task_id: str, event: dict):
        self.events.append((task_id, event))


@pytest.mark.asyncio
async def test_as_is_review_emits_existing_approval_envelope_and_resumes(monkeypatch):
    manager = _FakeManager("approve_as_is")
    pubsub = _FakePubSub()
    monkeypatch.setattr(review_tool, "get_pending_input_manager", lambda: manager)
    context = {**_workflow(), "chat_id": "chat-1", "task_id": "task-1", "pubsub": pubsub}

    result = await review_tool.request_assist_to_build_review_executor(
        {"stage": "as_is", "summary_markdown": "Current process", "diagram": _diagram()},
        context,
    )

    assert result["success"] is True
    assert result["outcome"] == "approve_as_is"
    assert context["assist_to_build_workflow"]["as_is_approved"] is True
    assert pubsub.events[0][1]["data"]["kind"] == "assist_to_build_review"
    assert pubsub.events[0][1]["data"]["summary"]["stage"] == "as_is"
    assert pubsub.events[0][1]["data"]["summary"]["diagram"] == _diagram()


@pytest.mark.asyncio
async def test_as_is_review_rejects_missing_or_invalid_required_diagram(monkeypatch):
    manager = _FakeManager("approve_as_is")
    monkeypatch.setattr(review_tool, "get_pending_input_manager", lambda: manager)
    context = _workflow()

    missing = await review_tool.request_assist_to_build_review_executor(
        {"stage": "as_is", "summary_markdown": "Current process"}, context
    )
    assert missing["success"] is False
    assert "Validation failed at diagram:" in missing["message"]

    invalid = await review_tool.request_assist_to_build_review_executor(
        {"stage": "as_is", "summary_markdown": "Current process", "diagram": {"title": "No flow"}},
        context,
    )
    assert invalid["success"] is False
    assert "Validation failed at diagram:" in invalid["message"]


@pytest.mark.asyncio
async def test_as_is_review_returns_a_precise_repair_instruction_for_legacy_diagrams(monkeypatch):
    manager = _FakeManager("approve_as_is")
    monkeypatch.setattr(review_tool, "get_pending_input_manager", lambda: manager)
    context = _workflow()

    result = await review_tool.request_assist_to_build_review_executor(
        {
            "stage": "as_is",
            "summary_markdown": "Current process",
            "diagram": {
                "type": "business-process",
                "title": "Legacy flow",
                "nodes": [],
                "edges": [],
            },
        },
        context,
    )

    assert result["success"] is False
    assert "diagram: unsupported keys ['type']" in result["message"]
    assert "complete AS-IS artifact" in result["message"]
    assert "source/target" in result["suggestion"]


@pytest.mark.asyncio
async def test_as_is_review_rejects_non_string_artifact_lists(monkeypatch):
    manager = _FakeManager("approve_as_is")
    monkeypatch.setattr(review_tool, "get_pending_input_manager", lambda: manager)

    result = await review_tool.request_assist_to_build_review_executor(
        {
            "stage": "as_is",
            "summary_markdown": "Current process",
            "diagram": _diagram(),
            "risks": [{"name": "legacy object"}],
        },
        _workflow(),
    )

    assert result["success"] is False
    assert "risks: expected an array of strings" in result["message"]


@pytest.mark.asyncio
async def test_to_be_review_unlocks_build_and_request_changes_does_not(monkeypatch):
    manager = _FakeManager({"response": "request_changes", "comment": "Clarify the handoff"})
    monkeypatch.setattr(review_tool, "get_pending_input_manager", lambda: manager)
    context = _workflow(as_is_approved=True, stage="to_be")
    first = await review_tool.request_assist_to_build_review_executor(
        {"stage": "to_be", "summary_markdown": "Future process", "diagram": _diagram()}, context
    )
    assert first["outcome"] == "request_changes"
    assert first["comment"] == "Clarify the handoff"
    assert block_pre_build_tool("write_file", context) is not None

    manager.response = "approve_to_be_and_build"
    second = await review_tool.request_assist_to_build_review_executor(
        {"stage": "to_be", "summary_markdown": "Revised future process", "diagram": _diagram()}, context
    )
    assert second["outcome"] == "approve_to_be_and_build"
    assert block_pre_build_tool("write_file", context) is None

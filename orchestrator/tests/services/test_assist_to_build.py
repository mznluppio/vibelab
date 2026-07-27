"""Unit coverage for the fixed Assist to Build process gates."""

from __future__ import annotations

import pytest

from app.agent.tools.marketplace_ops import request_assist_to_build_review as review_tool
from app.services.assist_to_build import block_pre_build_tool


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


def test_pre_build_guard_blocks_mutation_even_in_allow_mode():
    context = {**_workflow(), "edit_mode": "allow"}
    denied = block_pre_build_tool("write_file", context)
    assert denied and denied["workflow_guard"] == "assist_to_build_pre_build"
    assert block_pre_build_tool("read_file", context) is None
    assert block_pre_build_tool("mcp__unknown__mutate", context) is not None


def test_pre_build_guard_releases_only_after_to_be_approval():
    context = _workflow(to_be_approved=True, stage="build")
    assert block_pre_build_tool("write_file", context) is None


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
        {"stage": "as_is", "summary_markdown": "Current process", "mermaid": "flowchart LR\nA-->B"},
        context,
    )

    assert result["success"] is True
    assert result["outcome"] == "approve_as_is"
    assert context["assist_to_build_workflow"]["as_is_approved"] is True
    assert pubsub.events[0][1]["data"]["kind"] == "assist_to_build_review"
    assert pubsub.events[0][1]["data"]["summary"]["stage"] == "as_is"


@pytest.mark.asyncio
async def test_to_be_review_unlocks_build_and_request_changes_does_not(monkeypatch):
    manager = _FakeManager({"response": "request_changes", "comment": "Clarify the handoff"})
    monkeypatch.setattr(review_tool, "get_pending_input_manager", lambda: manager)
    context = _workflow(as_is_approved=True, stage="to_be")
    first = await review_tool.request_assist_to_build_review_executor(
        {"stage": "to_be", "summary_markdown": "Future process"}, context
    )
    assert first["outcome"] == "request_changes"
    assert first["comment"] == "Clarify the handoff"
    assert block_pre_build_tool("write_file", context) is not None

    manager.response = "approve_to_be_and_build"
    second = await review_tool.request_assist_to_build_review_executor(
        {"stage": "to_be", "summary_markdown": "Revised future process"}, context
    )
    assert second["outcome"] == "approve_to_be_and_build"
    assert block_pre_build_tool("write_file", context) is None

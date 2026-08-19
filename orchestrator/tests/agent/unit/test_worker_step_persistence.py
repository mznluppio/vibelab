from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.agent_task import AgentTaskPayload
from app.worker import (
    _defer_agent_task_for_chat_lock,
    _persist_agent_step,
    _schedule_preview_validation_repair,
    _schedule_interrupted_agent_resume,
)


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_step_persistence_stops_when_placeholder_is_already_gone():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    persisted = await _persist_agent_step(
        db,
        message_id=uuid4(),
        chat_id=uuid4(),
        step_index=0,
        step_data={"iteration": 1},
    )

    assert persisted is False
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_step_persistence_recovers_concurrent_placeholder_deletion():
    message_id = uuid4()
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[_scalar_result(message_id), _scalar_result(None)]
    )
    db.commit = AsyncMock(
        side_effect=IntegrityError("INSERT agent_steps", {}, Exception("fk"))
    )
    db.rollback = AsyncMock()

    persisted = await _persist_agent_step(
        db,
        message_id=message_id,
        chat_id=uuid4(),
        step_index=1,
        step_data={"iteration": 2},
    )

    assert persisted is False
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_step_persistence_reraises_other_integrity_errors_after_rollback():
    message_id = uuid4()
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[_scalar_result(message_id), _scalar_result(message_id)]
    )
    error = IntegrityError("INSERT agent_steps", {}, Exception("other"))
    db.commit = AsyncMock(side_effect=error)
    db.rollback = AsyncMock()

    with pytest.raises(IntegrityError):
        await _persist_agent_step(
            db,
            message_id=message_id,
            chat_id=uuid4(),
            step_index=2,
            step_data={"iteration": 3},
        )

    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_overlapping_chat_task_is_deferred_without_terminal_error(monkeypatch):
    queue = MagicMock()
    queue.enqueue = AsyncMock(return_value="job-id")
    monkeypatch.setattr(
        "app.services.task_queue.get_task_queue",
        lambda: queue,
    )
    pubsub = MagicMock()
    payload = AgentTaskPayload(
        task_id="task-new",
        user_id=str(uuid4()),
        chat_id=str(uuid4()),
        message="continue",
    )

    deferred = await _defer_agent_task_for_chat_lock(payload, pubsub, "task-old")

    assert deferred is True
    assert payload.chat_lock_retry_count == 1
    queued_payload = queue.enqueue.await_args.args[1]
    assert queued_payload["task_id"] == "task-new"
    assert queued_payload["chat_lock_retry_count"] == 1
    assert queue.enqueue.await_args.kwargs["_defer_by"] == 2.0


@pytest.mark.asyncio
async def test_interrupted_task_is_resumed_once_from_fresh_workspace_state(monkeypatch):
    queue = MagicMock()
    queue.enqueue = AsyncMock(return_value="job-id")
    manager = MagicMock()
    manager.reset_task_for_retry = AsyncMock()
    monkeypatch.setattr("app.services.task_queue.get_task_queue", lambda: queue)
    monkeypatch.setattr("app.services.task_manager.get_task_manager", lambda: manager)

    pubsub = MagicMock()
    pubsub.is_cancelled = AsyncMock(return_value=False)
    pubsub.publish_agent_event = AsyncMock()
    payload = AgentTaskPayload(
        task_id="task-interrupted",
        user_id=str(uuid4()),
        chat_id=str(uuid4()),
        message="Build the status page",
        chat_history=[{"role": "user", "content": "stale"}],
        project_context={"stale": True},
    )

    scheduled = await _schedule_interrupted_agent_resume(payload, pubsub)

    assert scheduled is True
    assert payload.resume_attempt == 1
    assert payload.chat_history == []
    assert payload.project_context == {}
    assert "Platform recovery" in payload.message
    manager.reset_task_for_retry.assert_awaited_once()
    assert queue.enqueue.await_args.args[0] == "execute_agent_task"
    assert queue.enqueue.await_args.args[1]["task_id"] == "task-interrupted"
    assert queue.enqueue.await_args.kwargs["_defer_by"] == 1

    assert await _schedule_interrupted_agent_resume(payload, pubsub) is False


@pytest.mark.asyncio
async def test_preview_validation_failure_resumes_task_once_with_diagnostic(monkeypatch):
    queue = MagicMock()
    queue.enqueue = AsyncMock(return_value="job-id")
    manager = MagicMock()
    manager.reset_task_for_retry = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr("app.services.task_queue.get_task_queue", lambda: queue)
    monkeypatch.setattr("app.services.task_manager.get_task_manager", lambda: manager)

    payload = AgentTaskPayload(
        task_id="task-validation-repair",
        user_id=str(uuid4()),
        chat_id=str(uuid4()),
        message="Build the equipment lending tool",
        chat_history=[{"role": "user", "content": "stale"}],
        project_context={"stale": True},
    )
    preview = {
        "agent_payload": payload.to_dict(),
        "preview_repair_attempt": 0,
    }

    scheduled = await _schedule_preview_validation_repair(
        preview, "bun run check:ui failed: class selector missing"
    )

    assert scheduled is True
    manager.reset_task_for_retry.assert_awaited_once()
    queued_payload = queue.enqueue.await_args.args[1]
    assert queued_payload["task_id"] == payload.task_id
    assert queued_payload["preview_repair_attempt"] == 1
    assert queued_payload["chat_history"] == []
    assert queued_payload["project_context"] == {}
    assert "Platform validation repair" in queued_payload["message"]
    assert "class selector missing" in queued_payload["message"]
    assert queue.enqueue.await_args.kwargs["_defer_by"] == 1

    preview["preview_repair_attempt"] = 1
    assert await _schedule_preview_validation_repair(preview, "still failing") is False

"""
ARQ Worker for Agent Task Execution

Runs agent tasks asynchronously, decoupled from the API pod's HTTP lifecycle.
Events are published to Redis Streams for real-time streaming back to clients.
Progressive step persistence ensures completed work survives crashes.

Usage:
    # Run as standalone worker process (uses same Docker image as backend)
    arq app.worker.WorkerSettings

    # Or via command line
    python -m arq app.worker.WorkerSettings
"""

import asyncio
import contextlib
import logging
import os
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

from arq.connections import RedisSettings

from .services import (
    k8s_auth as _k8s_auth,  # noqa: F401 — applies BearerToken monkey-patch at import time
)
from .services.apps.app_invocations import invoke_app_instance_task
from .services.apps.settlement_worker import settle_spend_batch as settle_spend_batch_cron
from .services.config_sync import ensure_config_synced
from .services.marketplace_sync import (
    marketplace_sync_periodic_cron,
    marketplace_yanks_fast_cron,
)

logger = logging.getLogger(__name__)

# A short-lived Redis heartbeat lets the API fail fast when an ARQ worker is
# unavailable instead of accepting a chat turn that will remain queued forever.
_WORKER_HEARTBEAT_KEY = "tesslate:worker:heartbeat"
_WORKER_HEARTBEAT_TTL_SECONDS = 15
_WORKER_HEARTBEAT_INTERVAL_SECONDS = 5

# Agents may opt into automatically bringing a project online after they have
# changed application files.  Keeping this opt-in avoids starting a project
# after a discovery-only chat, while making build agents reliable by default.
_PROJECT_MUTATION_TOOLS = frozenset(
    {
        "write_file",
        "patch_file",
        "multi_edit",
        "apply_patch",
        "apply_setup_config",
    }
)


async def _persist_agent_step(
    db,
    *,
    message_id: UUID,
    chat_id: UUID,
    step_index: int,
    step_data: dict,
) -> bool:
    """Persist one progressive step without poisoning the worker session.

    A chat or its in-progress assistant placeholder can be deleted while a
    task is still unwinding (for example when the user starts over).  In that
    case the FK target is gone and the task must stop cleanly instead of
    leaving the shared SQLAlchemy session in ``PendingRollbackError`` for all
    subsequent tools and finalisation work.

    Returns ``False`` when the placeholder vanished.  Other integrity errors
    remain real failures and are re-raised after restoring the transaction.
    """
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from .models import AgentStep, Message

    placeholder_id = (
        await db.execute(select(Message.id).where(Message.id == message_id))
    ).scalar_one_or_none()
    if placeholder_id is None:
        return False

    db.add(
        AgentStep(
            message_id=message_id,
            chat_id=chat_id,
            step_index=step_index,
            step_data=step_data,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent delete can win between the SELECT and INSERT.  Always
        # recover the session before inspecting the cause or propagating it.
        await db.rollback()
        placeholder_id = (
            await db.execute(select(Message.id).where(Message.id == message_id))
        ).scalar_one_or_none()
        if placeholder_id is None:
            return False
        raise
    return True


def _derive_execution_profile(project, containers: list[dict], chat_history: list[dict]) -> str:
    """Classify execution from persisted project state, never user text.

    The profile only changes platform guidance.  It does not constrain tools
    or iterations, so a broad follow-up feature can still complete normally.
    """
    if project is None or not containers:
        return "new_project"

    has_prior_assistant_turn = any(
        isinstance(entry, dict) and entry.get("role") == "assistant"
        for entry in chat_history
    )
    if not has_prior_assistant_turn:
        return "new_project"

    if project.environment_status == "active" and any(
        container.get("ready") or container.get("status") == "running"
        for container in containers
        if isinstance(container, dict)
    ):
        return "running_project"
    return "existing_project"


async def _start_project_after_agent_build(project, user_id: UUID, db) -> bool:
    """Start an opted-in build agent's project once its files are ready.

    ``start_project`` is idempotent in both orchestration modes.  We only call
    it when a project has actual containers, so discovery-only workspaces and
    non-application chats remain untouched.
    """
    from sqlalchemy import select

    from .models import Container, ContainerConnection
    from .services.orchestration import get_orchestrator

    # Source-of-truth refresh: fold any edits to .tesslate/config.json into
    # the Container graph before we can start anything.
    await ensure_config_synced(db, project, user_id)

    containers = list(
        (
            await db.execute(select(Container).where(Container.project_id == project.id))
        ).scalars()
    )
    if not containers:
        return False

    connections = list(
        (
            await db.execute(
                select(ContainerConnection).where(ContainerConnection.project_id == project.id)
            )
        ).scalars()
    )
    await asyncio.wait_for(
        get_orchestrator().start_project(project, containers, connections, user_id, db),
        timeout=90,
    )
    return True


async def start_project_preview_task(ctx: dict, preview: dict) -> None:
    """Start or verify one project preview outside the agent loop.

    This job owns runtime readiness after a confirmed project mutation.  It
    shares the orchestration interface across Docker, Kubernetes and local
    mode, and reports back to the originating agent stream without keeping a
    model turn or chat lock alive.
    """
    from sqlalchemy import select

    from .database import AsyncSessionLocal
    from .models import Container, ContainerConnection, Project
    from .services.orchestration import get_orchestrator

    task_id = str(preview["agent_task_id"])
    preview_task_id = str(preview["preview_task_id"])
    project_id = UUID(str(preview["project_id"]))
    user_id = UUID(str(preview["user_id"]))
    restart_required = bool(preview.get("restart_required"))

    from .services.pubsub import get_pubsub

    pubsub = get_pubsub()
    try:
        async with AsyncSessionLocal() as db:
            project = (
                await db.execute(select(Project).where(Project.id == project_id))
            ).scalar_one_or_none()
            if project is None:
                raise RuntimeError("Project no longer exists")

            # Source-of-truth refresh: fold any edits to .tesslate/config.json
            # into the Container graph before rendering manifests. This also
            # materialises containers for projects whose setup did not sync.
            await ensure_config_synced(db, project, user_id)

            containers = list(
                (
                    await db.execute(select(Container).where(Container.project_id == project.id))
                ).scalars()
            )
            if not containers:
                raise RuntimeError("Project has no configured application containers")
            connections = list(
                (
                    await db.execute(
                        select(ContainerConnection).where(
                            ContainerConnection.project_id == project.id
                        )
                    )
                ).scalars()
            )
            orchestrator = get_orchestrator()
            application_containers = [
                container
                for container in containers
                if getattr(container, "container_type", "base") != "service"
            ]
            if not application_containers:
                application_containers = containers

            # A source-compaction marker is never valid application code. This
            # catches legacy projects as well as any future regression before
            # we advertise a broken preview as ready.
            for file_path in preview.get("mutation_paths", []) or []:
                if not isinstance(file_path, str) or not file_path:
                    continue
                content = await orchestrator.read_file(
                    user_id=user_id,
                    project_id=str(project.id),
                    container_name=application_containers[0].name,
                    file_path=file_path,
                    project_slug=project.slug,
                    subdir=None,
                )
                if isinstance(content, str) and content.strip().startswith("[completed source omitted:"):
                    settings = dict(project.settings or {})
                    settings["agent_artifact_integrity"] = {
                        "status": "repair_required",
                        "file_path": file_path,
                        "reason": "compacted_source_marker",
                    }
                    project.settings = settings
                    await db.commit()
                    raise RuntimeError(
                        f"Project repair required: '{file_path}' contains a compacted source marker."
                    )

            status = await orchestrator.get_project_status(project.slug, project.id)
            runtime = status.get("containers", {}) if isinstance(status, dict) else {}
            running = any(
                isinstance(info, dict) and info.get("running")
                for info in runtime.values()
            )
            if not running:
                await orchestrator.start_project(project, containers, connections, user_id, db)
            elif restart_required:
                await orchestrator.restart_project(project, containers, connections, user_id, db)

            last_results: list[dict] = []
            for _ in range(30):
                last_results = [
                    await orchestrator.probe_container_http(
                        project.slug,
                        project.id,
                        container.id,
                        container.name,
                        container.effective_port,
                    )
                    for container in application_containers
                ]
                if last_results and all(result.get("healthy") for result in last_results):
                    from .services.preview_validation import run_preview_validation

                    validation_results = []
                    for container in application_containers:
                        validation = await run_preview_validation(
                            orchestrator,
                            user_id=user_id,
                            project_id=project.id,
                            project_slug=project.slug,
                            container_name=container.name,
                        )
                        validation_results.append(
                            {
                                "container": container.name,
                                "status": validation.status,
                                "command": validation.command,
                                "output": validation.output,
                            }
                        )

                    failed_validation = next(
                        (
                            result
                            for result in validation_results
                            if result["status"] == "failed"
                        ),
                        None,
                    )
                    validation_status = (
                        "failed"
                        if failed_validation
                        else (
                            "passed"
                            if any(result["status"] == "passed" for result in validation_results)
                            else "skipped"
                        )
                    )
                    settings = dict(project.settings or {})
                    settings["preview_validation"] = {
                        "status": validation_status,
                        "results": validation_results,
                    }
                    project.settings = settings
                    if failed_validation:
                        await db.commit()
                        raise RuntimeError(
                            "Post-preview UI validation failed for "
                            f"{failed_validation['container']}: "
                            f"{failed_validation['output'] or 'check:ui failed'}"
                        )

                    for container in application_containers:
                        container.status = "running"
                    project.environment_status = "active"
                    await db.commit()
                    if pubsub:
                        if any(result["status"] != "skipped" for result in validation_results):
                            await pubsub.publish_agent_event(
                                task_id,
                                {
                                    "type": "preview_validation",
                                    "data": {
                                        "task_id": task_id,
                                        "preview_task_id": preview_task_id,
                                        "project_id": str(project.id),
                                        "results": validation_results,
                                    },
                                },
                            )
                        await pubsub.publish_agent_event(
                            task_id,
                            {
                                "type": "preview_ready",
                                "data": {
                                    "task_id": task_id,
                                    "preview_task_id": preview_task_id,
                                    "project_id": str(project.id),
                                    "urls": [result.get("url") for result in last_results if result.get("url")],
                                },
                            },
                        )
                        await pubsub.publish_agent_event(
                            task_id,
                            {"type": "done", "data": {"task_id": task_id, "status": "completed"}},
                        )
                    await _update_task_status_redis(task_id, "completed")
                    automation_run_id = preview.get("automation_run_id")
                    if automation_run_id:
                        await _finalize_automation_run(
                            UUID(str(automation_run_id)),
                            status="succeeded",
                            raw_output={
                                "task_id": task_id,
                                "project_id": str(project.id),
                                "preview_task_id": preview_task_id,
                            },
                        )
                    return
                await asyncio.sleep(2)

            for container in application_containers:
                container.status = "error"
            project.environment_status = "error"
            await db.commit()
            raise RuntimeError(
                "Preview did not become ready within 60 seconds: "
                + "; ".join(str(result.get("error") or result.get("status_code")) for result in last_results)
            )
    except Exception as exc:
        logger.warning("[PREVIEW] lifecycle failed for %s: %s", project_id, exc, exc_info=True)
        if pubsub:
            await pubsub.publish_agent_event(
                task_id,
                {
                    "type": "preview_failed",
                    "data": {
                        "task_id": task_id,
                        "preview_task_id": preview_task_id,
                        "project_id": str(project_id),
                        "message": str(exc),
                    },
                },
            )
            await pubsub.publish_agent_event(
                task_id,
                {
                    "type": "done",
                    "data": {"task_id": task_id, "status": "failed", "error": str(exc)},
                },
            )
        await _update_task_status_redis(task_id, "failed", error=str(exc))
        automation_run_id = preview.get("automation_run_id")
        if automation_run_id:
            with contextlib.suppress(Exception):
                await _finalize_automation_run(
                    UUID(str(automation_run_id)),
                    status="failed",
                    raw_output={
                        "task_id": task_id,
                        "project_id": str(project_id),
                        "preview_task_id": preview_task_id,
                        "error": str(exc)[:1000],
                    },
                )


async def _write_worker_heartbeat() -> None:
    """Refresh the worker liveness marker without affecting job execution."""
    from .services.cache_service import get_redis_client

    redis = await get_redis_client()
    if redis is not None:
        await redis.set(_WORKER_HEARTBEAT_KEY, "1", ex=_WORKER_HEARTBEAT_TTL_SECONDS)


async def _worker_heartbeat_loop() -> None:
    """Keep the ARQ worker's liveness marker fresh for API-side preflight."""
    while True:
        try:
            await _write_worker_heartbeat()
        except Exception:
            # A temporary cache failure must never take down the worker.
            logger.warning("[WORKER] Failed to refresh worker heartbeat", exc_info=True)
        await asyncio.sleep(_WORKER_HEARTBEAT_INTERVAL_SECONDS)


def _convert_uuids_to_strings(obj):
    """Recursively convert UUID objects to strings in nested data structures."""
    if isinstance(obj, UUID):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: _convert_uuids_to_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_uuids_to_strings(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(_convert_uuids_to_strings(item) for item in obj)
    else:
        return obj


def _seed_text_for_title(user_message: str, attachments: list[dict] | None) -> str:
    """Pick the best available text to seed title generation from.

    If the user typed something, use that. Otherwise reach into attachments —
    pasted-text content, then a file-reference path, then an image label — so
    paste-only / image-only turns still produce a meaningful title.
    """
    if user_message and user_message.strip():
        return user_message.strip()
    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        att_type = att.get("type")
        if att_type == "pasted_text":
            body = (att.get("content") or "").strip()
            if body:
                label = att.get("label") or "Pasted text"
                return f"{label}: {body}"
        elif att_type == "file_reference":
            fp = att.get("file_path")
            if fp:
                return f"Discuss file {fp}"
        elif att_type == "image":
            label = att.get("label") or att.get("mime_type") or "image"
            return f"Review attached {label}"
    return ""


def _fallback_title(seed: str) -> str:
    """Truncation fallback when the LLM title step is empty/errors.

    Takes the first meaningful line of ``seed`` and trims it. Always returns
    a non-empty string (the caller guards on ``seed`` being empty already).
    """
    first_line = next((line for line in seed.splitlines() if line.strip()), seed)
    trimmed = first_line.strip()[:60].rstrip()
    return trimmed or "New chat"


async def _auto_title_chat(
    chat,
    model_adapter,
    user_message: str,
    db,
    attachments: list[dict] | None = None,
    assistant_response: str = "",
) -> None:
    """Generate and set a chat title after the first agent turn. Non-blocking.

    Design: we "fork" the conversation — replay what the user sent plus the
    agent's first reply to an independent LLM call, then append a synthetic
    "Generate a concise title" user turn. This gives the titling model full
    context (instead of guessing from a bare "hiii") while leaving the main
    chat history untouched. If the LLM call is empty or errors, we fall back
    to a truncated seed so chats never stay "Untitled" forever.
    """
    if not chat or chat.title:
        return
    seed_user = _seed_text_for_title(user_message, attachments)
    if not seed_user and not assistant_response:
        logger.info(
            f"[WORKER] Auto-title skipped for chat {chat.id}: no seed text "
            f"(empty message, no usable attachments, and no assistant reply yet)"
        )
        return

    logger.info(
        f"[WORKER] Auto-titling chat {chat.id} via forked session "
        f"(message={bool(user_message)}, attachments={len(attachments or [])}, "
        f"assistant_response_chars={len(assistant_response or '')})"
    )

    fork: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You generate concise chat session titles. Read the "
                "conversation and produce a 3-6 word title. Return ONLY "
                "the title — no quotes, no punctuation, no prefixes like "
                "'Title:'. Examples: 'Login page with OAuth', "
                "'Fix navbar responsive layout', 'Add dark mode toggle'."
            ),
        }
    ]
    if seed_user:
        fork.append({"role": "user", "content": seed_user[:500]})
    if assistant_response:
        fork.append({"role": "assistant", "content": assistant_response[:1000]})
    fork.append(
        {
            "role": "user",
            "content": "Generate a title for this chat session.",
        }
    )

    title_text = ""
    try:
        async for chunk in model_adapter.chat(fork, max_tokens=20):
            title_text += chunk
        title_text = title_text.strip().strip("\"'")[:100]
    except Exception as e:
        logger.warning(f"[WORKER] Auto-title LLM call failed for chat {chat.id}: {e}")
        title_text = ""

    if not title_text:
        fallback_seed = seed_user or assistant_response or "New chat"
        title_text = _fallback_title(fallback_seed)
        logger.info(f"[WORKER] Auto-title fallback used for chat {chat.id}: {title_text!r}")

    try:
        chat.title = title_text
        await db.commit()
        logger.info(f"[WORKER] Auto-titled chat {chat.id}: {title_text}")
    except Exception as e:
        logger.warning(f"[WORKER] Auto-title commit failed for chat {chat.id}: {e}")


async def _create_agent_checkpoint(volume_id: str, summary: str) -> None:
    """Fire-and-forget CAS checkpoint after agent task completion.

    Creates a labeled snapshot so the user can restore to any agent run.
    Failures are logged but never propagated — agent completion is not
    contingent on snapshot success.
    """
    try:
        from .config import get_settings
        from .services.hub_client import HubClient

        settings = get_settings()
        if not settings.volume_hub_address:
            return
        label = f"agent: {summary[:80]}"
        async with HubClient(settings.volume_hub_address) as client:
            await client.create_snapshot(volume_id, label, timeout=30.0)
        logger.info("[WORKER] Agent checkpoint created: volume=%s", volume_id)
    except Exception as e:
        logger.warning("[WORKER] Agent checkpoint failed (non-fatal): %s", e)


def _build_step_dict(step_data: dict, _convert_uuids_to_strings) -> dict:
    """Build a normalized step dict from raw agent step data."""
    return {
        "iteration": step_data.get("iteration"),
        "thought": step_data.get("thought"),
        "tool_calls": [
            {
                "name": tc.get("name"),
                "parameters": _convert_uuids_to_strings(tc.get("parameters", {})),
                "result": _convert_uuids_to_strings(
                    step_data.get("tool_results", [])[idx]
                    if idx < len(step_data.get("tool_results", []))
                    else {}
                ),
            }
            for idx, tc in enumerate(step_data.get("tool_calls", []))
        ],
        "response_text": step_data.get("response_text", ""),
        "is_complete": step_data.get("is_complete", False),
        "timestamp": step_data.get("timestamp", ""),
    }


async def _heartbeat_lock(pubsub, chat_id: str, task_id: str):
    """Extend the chat lock every 10 seconds until cancelled.

    When the lock is lost (stolen or expired), signals cancellation
    via Redis so the agent loop stops at the next iteration check.
    """
    try:
        while True:
            await asyncio.sleep(10)
            extended = await pubsub.extend_chat_lock(chat_id, task_id)
            if not extended:
                logger.warning(
                    f"[WORKER] Lost chat lock for {chat_id}, "
                    f"task {task_id} — signalling cancellation"
                )
                await pubsub.request_cancellation(task_id)
                break
    except asyncio.CancelledError:
        pass


_CHAT_LOCK_RETRY_DELAY_SECONDS = 2.0
_CHAT_LOCK_MAX_WAIT_SECONDS = 600.0
_WORKSPACE_SETUP_RETRY_DELAY_SECONDS = 2.0
_WORKSPACE_SETUP_MAX_WAIT_SECONDS = 240.0


async def _defer_agent_task_for_chat_lock(payload, pubsub, holding_task: str | None) -> bool:
    """Requeue an overlapping chat turn without tying up a worker slot.

    A previous turn can still own the chat lock while it persists its final
    message or starts the preview.  Rejecting the next turn in that small
    window used to leave its TaskManager entry stuck in ``running``.  Reusing
    the same task id also keeps the existing SSE subscription valid.

    Returns ``True`` when the task was deferred, or ``False`` after publishing
    an explicit terminal failure once the global wait budget is exhausted.
    """
    retry_count = max(0, int(getattr(payload, "chat_lock_retry_count", 0) or 0))
    waited_seconds = retry_count * _CHAT_LOCK_RETRY_DELAY_SECONDS
    if waited_seconds >= _CHAT_LOCK_MAX_WAIT_SECONDS:
        error = (
            "This conversation is still busy with another agent task. "
            "Please retry once that task has finished."
        )
        await _publish_error(pubsub, payload.task_id, error)
        await _update_task_status_redis(payload.task_id, "failed", error=error)
        logger.warning(
            "[WORKER] Chat lock wait exhausted: task=%s chat=%s holder=%s",
            payload.task_id,
            payload.chat_id,
            holding_task,
        )
        return False

    from .services.task_queue import get_task_queue

    payload.chat_lock_retry_count = retry_count + 1
    await get_task_queue().enqueue(
        "execute_agent_task",
        payload.to_dict(),
        _defer_by=_CHAT_LOCK_RETRY_DELAY_SECONDS,
    )
    logger.info(
        "[WORKER] Deferred overlapping chat task: task=%s chat=%s holder=%s retry=%d",
        payload.task_id,
        payload.chat_id,
        holding_task,
        payload.chat_lock_retry_count,
    )
    return True


async def _defer_agent_task_for_workspace_setup(payload, pubsub) -> bool:
    """Yield the worker slot while a required Base is being materialised.

    Returns ``True`` when the caller must return (deferred or terminal
    failure), and ``False`` only when the project setup is complete.
    """
    setup_task_id = getattr(payload, "workspace_setup_task_id", None)
    if not setup_task_id:
        return False

    from .services.task_manager import TaskStatus, get_task_manager

    setup_task = await get_task_manager().get_task_async(setup_task_id)
    if setup_task and setup_task.status == TaskStatus.COMPLETED:
        payload.workspace_setup_task_id = None
        return False

    if setup_task and setup_task.status in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
        error = setup_task.error or "The required Base could not be prepared."
        await _publish_error(pubsub, payload.task_id, error)
        await _update_task_status_redis(payload.task_id, "failed", error=error)
        return True

    retry_count = max(0, int(getattr(payload, "workspace_setup_retry_count", 0) or 0))
    if retry_count * _WORKSPACE_SETUP_RETRY_DELAY_SECONDS >= _WORKSPACE_SETUP_MAX_WAIT_SECONDS:
        error = "Timed out while preparing the agent's required Base."
        await _publish_error(pubsub, payload.task_id, error)
        await _update_task_status_redis(payload.task_id, "failed", error=error)
        return True

    if pubsub:
        await pubsub.publish_agent_event(
            payload.task_id,
            {
                "type": "workspace_preparing",
                "data": {
                    "task_id": payload.task_id,
                    "chat_id": payload.chat_id,
                    "project_id": payload.project_id,
                    "setup_task_id": setup_task_id,
                },
            },
        )

    from .services.task_queue import get_task_queue

    payload.workspace_setup_retry_count = retry_count + 1
    await get_task_queue().enqueue(
        "execute_agent_task",
        payload.to_dict(),
        _defer_by=_WORKSPACE_SETUP_RETRY_DELAY_SECONDS,
    )
    return True


async def _schedule_interrupted_agent_resume(payload, pubsub) -> bool:
    """Queue one idempotent recovery after an infrastructure interruption.

    A user cancellation is always terminal. For a worker timeout or eviction,
    completed AgentStep rows and verified file hashes are already durable, so
    the recovery starts from the real workspace rather than replaying writes.
    """
    if int(getattr(payload, "resume_attempt", 0) or 0) >= 1:
        return False
    # Ticket execution has its own checkout/approval state machine. Do not
    # silently replay it with a ticket that may already be terminal.
    if getattr(payload, "agent_task_id", None):
        return False
    if pubsub is not None and await pubsub.is_cancelled(payload.task_id):
        return False

    from .services.task_manager import get_task_manager
    from .services.task_queue import get_task_queue

    payload.resume_attempt = int(getattr(payload, "resume_attempt", 0) or 0) + 1
    payload.resume_reason = "worker_interrupted"
    # Force the resumed worker to reload the compact current history and
    # workspace state; the original queued snapshot is stale after mutations.
    payload.chat_history = []
    payload.project_context = {}
    payload.message = (
        f"{payload.message}\n\n"
        "[Platform recovery] The previous worker was interrupted after partial work. "
        "Inspect the current project and AgentStep results, keep files whose current "
        "contents are correct, repair only missing or invalid artifacts, validate the "
        "application, then finish the original request."
    )

    await get_task_manager().reset_task_for_retry(
        payload.task_id,
        metadata_updates={
            "resume_attempt": payload.resume_attempt,
            "resume_reason": payload.resume_reason,
        },
    )
    await get_task_queue().enqueue("execute_agent_task", payload.to_dict(), _defer_by=1)
    if pubsub:
        await pubsub.publish_agent_event(
            payload.task_id,
            {
                "type": "resuming",
                "data": {
                    "task_id": payload.task_id,
                    "attempt": payload.resume_attempt,
                    "reason": payload.resume_reason,
                },
            },
        )
    logger.info("[WORKER] Scheduled recovery task=%s attempt=%s", payload.task_id, payload.resume_attempt)
    return True


async def _contract_gate_hook(tool_name, parameters, context, tool):
    """Pre-execute hook bridging the submodule registry into ContractGate.

    The orchestrator's automation contract gate lives in-tree (it touches
    ``automation_runs``, billing tables, etc., which the submodule must
    not depend on). The submodule registry exposes a ``pre_execute_hook``
    seam so we can wedge the gate in without duplicating its logic.

    Returns ``None`` for non-automation invocations (no contract in
    context) so chat sessions are unaffected, or a tool-result envelope
    when the gate denies the call (same shape as the in-tree path).
    """
    from .agent.tools.registry import check_contract_gate

    return await check_contract_gate(
        tool_name=tool_name,
        parameters=parameters,
        context=context,
        tool=tool,
    )


def _build_submodule_registry(in_tree_registry, approval_handler=None):
    """Transfer tools from an in-tree ToolRegistry to a submodule ToolRegistry.

    Both registries store tools in a ``_tools`` dict keyed by tool name. The
    in-tree Tool objects are structurally identical to the submodule's Tool
    (same dataclass fields), so they can be registered directly without
    conversion. Category comparisons are string-name-based at execution time.

    ``approval_handler`` is an optional async callable injected into the
    submodule registry so the orchestrator's interactive approval flow (Redis
    pub/sub + frontend dialog) is used instead of the env-var-based fallback.

    The submodule registry's ``pre_execute_hook`` is wired to
    ``_contract_gate_hook`` so automation runs enforce ``allowed_tools`` /
    ``allowed_mcps`` / ``allowed_skills`` / ``max_compute_tier`` /
    ``max_spend_per_run_usd`` — without this the in-tree ContractGate is
    dead code on every automation dispatch (TC-04 Bug #22).
    """
    try:
        from tesslate_agent.agent.tools.registry import ToolRegistry as SubmoduleRegistry

        async def _pre_execute_hook(tool_name, parameters, context, tool):
            return await _contract_gate_hook(tool_name, parameters, context, tool)

        sub = SubmoduleRegistry(
            approval_handler=approval_handler,
            pre_execute_hook=_pre_execute_hook,
        )
        for tool in in_tree_registry._tools.values():
            sub.register(tool)
        return sub
    except Exception as exc:
        logger.warning("[WORKER] Submodule registry build failed: %s", exc)
        return None


async def _create_agent_runner(
    agent_model, model_adapter, tools_override, settings, approval_handler=None
):
    """Return an object with a ``.run(message, context)`` async-generator method.

    Uses the submodule's TesslateAgent runner via TesslateAgentAdapter.
    Satisfies the ``run(message, context)`` interface.
    """
    from .services.tesslate_agent_adapter import TesslateAgentAdapter

    if tools_override is not None:
        sub_registry = _build_submodule_registry(
            tools_override,
            approval_handler=approval_handler,
        )
    else:
        from .agent.tools.registry import create_scoped_tool_registry, get_tool_registry

        declared_tools = getattr(agent_model, "tools", None)
        tool_configs = getattr(agent_model, "tool_configs", None)
        # Marketplace agents declare their exact capability set. Respect it at
        # runtime instead of advertising the global registry to the model.
        in_tree_registry = (
            create_scoped_tool_registry(declared_tools, tool_configs)
            if isinstance(declared_tools, list)
            else get_tool_registry()
        )

        sub_registry = _build_submodule_registry(
            in_tree_registry,
            approval_handler=approval_handler,
        )

    if sub_registry is None:
        raise RuntimeError("tesslate-agent submodule is unavailable; cannot create agent runner")

    # Build compaction model adapter from agent config.
    compaction_adapter = None
    agent_config = getattr(agent_model, "config", None) or {}
    compaction_model_name = (
        agent_config.get("compaction_model", "") or settings.compaction_summary_model
    )
    if compaction_model_name and model_adapter and hasattr(model_adapter, "client"):
        try:
            from .services.model_adapters import OpenAIAdapter, resolve_model_name

            compaction_adapter = OpenAIAdapter(
                model_name=resolve_model_name(compaction_model_name),
                client=model_adapter.client,
                temperature=0.3,
            )
        except Exception as ca_err:
            logger.warning("[WORKER] Compaction adapter failed (non-fatal): %s", ca_err)

    adapter = TesslateAgentAdapter(
        system_prompt=agent_model.system_prompt,
        tools=sub_registry,
        model=model_adapter,
        compaction_adapter=compaction_adapter,
    )
    return adapter


# ---------------------------------------------------------------------------
# AutomationRun lifecycle helpers
#
# When ``execute_agent_task`` runs as the async tail of an ``agent.run``
# automation action, the dispatcher (services/automations/dispatcher.py)
# leaves the run row at ``status="running"`` with a fresh heartbeat. The
# worker owns the rest of the lifecycle:
#
#   1. ``_heartbeat_automation_run`` keeps ``heartbeat_at`` fresh on a 30s
#      cadence so ``services.automations.heartbeat_sweep`` (90s timeout)
#      does not reap a still-working run.
#   2. ``_finalize_automation_run`` writes the terminal status when the
#      agent finishes (``succeeded``), crashes (``failed``), or pauses
#      for a tool approval (``waiting_approval``). The WHERE clause guards
#      against stomping a state set elsewhere (user cancellation, Phase 2
#      contract-breach pause, racing dispatcher writeback).
#
# Both helpers open their own ``AsyncSessionLocal`` so they don't share
# the long-lived session the agent loop uses (which can sit on a
# transaction for tens of seconds during model round-trips).
# ---------------------------------------------------------------------------


_AUTOMATION_RUN_NON_TERMINAL = ("queued", "preflight", "running")


async def _heartbeat_automation_run(
    automation_run_id: UUID,
    *,
    interval_s: float = 30.0,
) -> None:
    """Refresh ``AutomationRun.heartbeat_at`` while the agent loop runs.

    The dispatcher writes one heartbeat at handoff; without periodic
    refresh, runs that exceed 90s wall time (long Notion API calls,
    slow Tier-0 LLM round-trips) get reaped mid-flight by
    ``heartbeat_sweep``. The WHERE-clause guard ensures we only refresh
    rows still in flight — once status has flipped to a terminal or
    paused state somewhere else, an extra heartbeat would mask that
    transition.
    """
    from sqlalchemy import update as _sa_update

    from .database import AsyncSessionLocal
    from .models_automations import AutomationRun

    while True:
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            raise
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    _sa_update(AutomationRun)
                    .where(AutomationRun.id == automation_run_id)
                    .where(AutomationRun.status == "running")
                    .values(heartbeat_at=datetime.now(tz=UTC))
                )
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            # heartbeat_sweep is the safety net; one missed write is fine.
            logger.exception(
                "[WORKER] heartbeat write failed for automation_run=%s",
                automation_run_id,
            )


async def _finalize_automation_run(
    automation_run_id: UUID,
    *,
    status: str,
    raw_output: dict,
) -> None:
    """Write the terminal/paused row for an automation_run.

    Guarded by ``WHERE status IN ('queued','preflight','running')`` so
    we don't overwrite a state owned by another path:
      * ``cancelled``     — user cancellation
      * ``waiting_approval`` — Phase 2 contract-breach pause
      * ``succeeded``/``failed``/``expired`` — already terminal

    For tool-approval pauses (``ApprovalRequired`` raised mid-loop) the
    caller passes ``status="waiting_approval"``; the same guard lets
    the existing approval-resume path replay through ``status="running"``
    without conflict.
    """
    from sqlalchemy import update as _sa_update

    from .database import AsyncSessionLocal
    from .models_automations import AutomationRun

    now = datetime.now(tz=UTC)
    automation_id_for_event: UUID | None = None
    try:
        async with AsyncSessionLocal() as db:
            # Re-read the row so we can carry automation_id into the
            # workflow_event fan-out below.
            row = (
                await db.execute(
                    _sa_update(AutomationRun)
                    .where(AutomationRun.id == automation_run_id)
                    .where(AutomationRun.status.in_(_AUTOMATION_RUN_NON_TERMINAL))
                    .values(
                        status=status,
                        ended_at=now,
                        heartbeat_at=now,
                        raw_output=raw_output,
                    )
                    .returning(AutomationRun.automation_id)
                )
            ).first()
            if row is not None:
                automation_id_for_event = row[0]
            await db.commit()
    except Exception:
        logger.exception(
            "[WORKER] failed to write terminal automation_run state (run=%s status=%s)",
            automation_run_id,
            status,
        )

    # G5 (#469): fan out workflow_event subscribers (e.g. per-workflow
    # doctor) when a tier-2 async agent run lands on a terminal status.
    # The synchronous dispatcher path goes through `_finalize_failure` /
    # `_finalize_success`; this is the async equivalent. Best-effort.
    if automation_id_for_event is not None and status in (
        "failed",
        "failed_preflight",
        "timed_out",
        "expired",
    ):
        try:
            from .services.workflows.event_log import emit_run_finished

            async with AsyncSessionLocal() as db2:
                await emit_run_finished(
                    db2,
                    run_id=automation_run_id,
                    automation_id=automation_id_for_event,
                    status=status,
                )
        except Exception:
            logger.debug(
                "[WORKER] emit_run_finished failed run=%s status=%s",
                automation_run_id,
                status,
                exc_info=True,
            )


async def execute_agent_task(ctx: dict, payload_dict: dict):
    """
    Execute an agent task in the worker process.

    This function:
    1. Deserializes the task payload
    2. Acquires per-project lock (if enabled)
    3. Creates placeholder Message in DB before agent loop
    4. Runs agent.run() — INSERTs AgentStep rows progressively
    5. Finalizes the Message with summary metadata on completion
    6. Publishes events to Redis Streams for live SSE relay
    7. Enqueues webhook callback if configured
    8. Cleans up bash sessions and releases lock
    """
    from sqlalchemy import select

    from .config import get_settings
    from .database import AsyncSessionLocal
    from .models import (
        Chat,
        Container,
        MarketplaceAgent,
        Message,
        Project,
        User,
        UserPurchasedAgent,
    )
    from .services.agent_context import (
        _build_cross_platform_context,
        _build_tesslate_context,
        _get_chat_history,
        _resolve_container_name,
    )
    from .services.agent_task import AgentTaskPayload
    from .services.model_adapters import create_model_adapter
    from .services.pubsub import get_pubsub

    settings = get_settings()
    payload = AgentTaskPayload.from_dict(payload_dict)
    # ARQ retries a job when the worker process itself disappears, a path that
    # cannot run our CancelledError handler. Treat its single configured retry
    # as the same idempotent recovery contract as a timeout-driven requeue.
    try:
        arq_attempt = int(ctx.get("job_try", 1) or 1)
    except (TypeError, ValueError):
        arq_attempt = 1
    if arq_attempt > 1 and payload.resume_attempt == 0:
        payload.resume_attempt = 1
        payload.resume_reason = "worker_retry"
        payload.chat_history = []
        payload.project_context = {}
        payload.message = (
            f"{payload.message}\n\n"
            "[Platform recovery] Resume from the actual workspace state after an interrupted "
            "worker. Preserve correct files and repair only missing or invalid artifacts."
        )
    pubsub = get_pubsub()
    task_id = payload.task_id
    project_id = payload.project_id
    task_started_at = time.monotonic()
    agent_loop_started_at: float | None = None
    heartbeat_task = None
    lock_acquired = False
    lock_stolen = False
    message_id = None
    # Ticket tracking — set when payload carries an agent_task_id and the claim succeeds
    claimed_ticket_id: UUID | None = None
    # Automation-run lifecycle — set when the dispatcher enqueued us.
    # The worker owns the row's terminal write; the heartbeat task keeps
    # heartbeat_sweep from reaping a long-running agent loop.
    auto_run_id: UUID | None = (
        UUID(payload.automation_run_id) if payload.automation_run_id else None
    )
    auto_run_hb_task: asyncio.Task | None = None
    # Counters captured during the agent loop and consumed by the
    # success-path finalize. Defaults are conservative so the early-return
    # branches (project-missing, ticket-already-claimed, etc.) still produce
    # a valid raw_output payload.
    iterations = 0
    tool_calls_made = 0
    event_count = 0
    completion_reason: str | None = None
    session_id: str | None = None
    chat = None

    logger.info(f"[WORKER] Starting agent task {task_id} for project {project_id}")

    # Queued retries and external callers do not necessarily pass through the
    # browser route that marks a task running. Make worker pickup authoritative.
    with contextlib.suppress(Exception):
        from .services.task_manager import TaskStatus, get_task_manager

        await get_task_manager().update_task_status(task_id, TaskStatus.RUNNING)

    # Phase 1 traceability: log the automation context if the dispatcher
    # enqueued us. Phase 2 wires ContractGate enforcement; here we just
    # surface the binding so logs/dashboards can correlate runs.
    if payload.automation_run_id:
        logger.info(
            "[WORKER] task=%s bound to automation_run=%s automation=%s "
            "trigger_kind=%s trigger_event=%s contract_keys=%s",
            task_id,
            payload.automation_run_id,
            payload.automation_id,
            payload.trigger_kind,
            payload.trigger_event_id,
            list((payload.contract or {}).keys()),
        )

    # Spawn the automation-run heartbeat as soon as we know we're bound.
    # Doing it before the early-return branches (project-missing, ticket
    # claim races) is fine — the outer ``finally`` cancels it cleanly even
    # if we never reach the agent loop.
    if auto_run_id is not None:
        auto_run_hb_task = asyncio.create_task(_heartbeat_automation_run(auto_run_id))

    async with AsyncSessionLocal() as db:
        try:
            # 0. Atomic ticket checkout (desktop multi-agent orchestration)
            # If payload carries a ticket ID, claim it from "queued" → "running".
            # If the claim fails (another worker already picked it up), skip silently.
            if payload.agent_task_id:
                from .services.agent_tickets import checkout_ticket_by_id

                claimed = await checkout_ticket_by_id(
                    db,
                    ticket_id=UUID(payload.agent_task_id),
                    worker_id=task_id,
                )
                if not claimed:
                    logger.info(
                        "[WORKER] Ticket %s already running — skipping duplicate pickup",
                        payload.agent_task_id,
                    )
                    return
                claimed_ticket_id = UUID(payload.agent_task_id)

            # 1. Load project (optional for standalone chats)
            project = None
            if project_id:
                result = await db.execute(select(Project).where(Project.id == UUID(project_id)))
                project = result.scalar_one_or_none()
                if not project:
                    await _publish_error(pubsub, task_id, "Project not found")
                    return

            # 2. Acquire per-chat lock (allows concurrent agents across sessions)
            project_settings = (project.settings or {}) if project else {}
            agent_lock_enabled = project_settings.get("agent_lock_enabled", True)
            chat_id = payload.chat_id

            if agent_lock_enabled and pubsub:
                # `acquire_chat_lock` now takes over cancelled zombie holders
                # atomically (Lua script) — no retry loop needed. Fails only
                # if a LIVE task is running in this chat.
                lock_acquired = await pubsub.acquire_chat_lock(chat_id, task_id)
                if not lock_acquired:
                    holding_task = await pubsub.get_chat_lock(chat_id)
                    await _defer_agent_task_for_chat_lock(
                        payload,
                        pubsub,
                        holding_task,
                    )
                    return
                # Start heartbeat to extend lock every 10s
                heartbeat_task = asyncio.create_task(_heartbeat_lock(pubsub, chat_id, task_id))

            # 3. Load agent model
            #
            # Resolution rules:
            #   * Automation-driven runs (``auto_run_id`` set by the
            #     dispatcher) MUST carry an explicit, valid ``agent_id``.
            #     The route-level validator (``_replace_actions``) already
            #     refuses to save an automation without one — this branch
            #     is the run-time safety net for legacy rows that predate
            #     the validator + a defense-in-depth team-scope check.
            #     A miss writes a terminal ``failed`` row with a typed
            #     ``raw_output.error`` so the run doesn't hang at
            #     ``running`` forever (TC-03 Bug #20d).
            #   * Chat / ticket / external-agent paths keep the legacy
            #     "first active IterativeAgent" fallback for unauthenticated
            #     paths that don't carry an agent_id. The fallback is
            #     SUPPRESSED for automation runs because it silently runs
            #     the wrong agent on the user's behalf (TC-03 Bug #20e).
            from .services.marketplace_agent_scope import (
                AgentScopeError,
                resolve_agent_in_user_scope,
            )

            agent_model: MarketplaceAgent | None = None
            agent_load_error: str | None = None
            agent_load_reason: str | None = None
            try:
                if payload.agent_id:
                    try:
                        requested_agent_id = UUID(payload.agent_id)
                    except (TypeError, ValueError) as exc:
                        # Pre-validator rows could carry a non-UUID string.
                        # Don't leak the ValueError — surface a typed error
                        # the dispatcher / UI can render.
                        raise AgentScopeError(
                            AgentScopeError.REASON_NOT_FOUND,
                            f"agent_id {payload.agent_id!r} is not a valid UUID",
                        ) from exc

                    if auto_run_id is not None:
                        # Automation context — apply the same scope check
                        # the assign-time path uses, so a stale or
                        # cross-team agent_id can't reach the agent loop.
                        owner = (
                            await db.execute(select(User).where(User.id == UUID(payload.user_id)))
                        ).scalar_one_or_none()
                        if owner is None:
                            raise AgentScopeError(
                                AgentScopeError.REASON_NOT_FOUND,
                                f"user {payload.user_id} no longer exists",
                            )
                        agent_model = await resolve_agent_in_user_scope(
                            db, agent_id=requested_agent_id, user=owner
                        )
                    else:
                        # Chat / ticket path — existence + active + correct
                        # item_type are still required (a skill UUID can't
                        # run an agent loop without crashing on a None tool
                        # list) but library scope is enforced upstream.
                        from .services.marketplace_agent_scope import (
                            RUNNABLE_AGENT_ITEM_TYPE,
                        )

                        result = await db.execute(
                            select(MarketplaceAgent).where(
                                MarketplaceAgent.id == requested_agent_id,
                                MarketplaceAgent.is_active.is_(True),
                                MarketplaceAgent.item_type == RUNNABLE_AGENT_ITEM_TYPE,
                            )
                        )
                        agent_model = result.scalar_one_or_none()
                        if agent_model is None:
                            raise AgentScopeError(
                                AgentScopeError.REASON_NOT_FOUND,
                                f"agent {requested_agent_id} is not loadable "
                                "(missing, inactive, or wrong item_type)",
                            )
                elif auto_run_id is not None:
                    # Automation run with no agent_id at all — historically
                    # this silently fell through to "first active
                    # IterativeAgent". That ran the wrong agent on the
                    # user's behalf without warning. Refuse instead.
                    raise AgentScopeError(
                        AgentScopeError.REASON_NOT_FOUND,
                        "automation run is missing agent_id — automations "
                        "must bind an explicit agent at assign time",
                    )
                else:
                    # Legacy chat fallback: pick the first active
                    # IterativeAgent. Kept for unauthenticated entrypoints
                    # that historically depended on it.
                    from .services.marketplace_agent_scope import (
                        RUNNABLE_AGENT_ITEM_TYPE,
                    )

                    result = await db.execute(
                        select(MarketplaceAgent)
                        .where(
                            MarketplaceAgent.is_active.is_(True),
                            MarketplaceAgent.agent_type == "IterativeAgent",
                            MarketplaceAgent.item_type == RUNNABLE_AGENT_ITEM_TYPE,
                        )
                        .limit(1)
                    )
                    agent_model = result.scalar_one_or_none()
                    if agent_model is None:
                        raise AgentScopeError(
                            AgentScopeError.REASON_NOT_FOUND,
                            "no active IterativeAgent registered",
                        )
            except AgentScopeError as exc:
                agent_load_error = str(exc)
                agent_load_reason = exc.reason
                agent_model = None

            if agent_model is None:
                # Publish the error so the chat surface / SSE can render
                # it — same call we made before this fix.
                await _publish_error(pubsub, task_id, f"No agent found: {agent_load_error}")
                # Critically, write the terminal automation_runs row when
                # this was an automation-driven run. Without this the row
                # sat at ``status='running'`` indefinitely (TC-03 Bug #20d).
                if auto_run_id is not None:
                    await _finalize_automation_run(
                        auto_run_id,
                        status="failed",
                        raw_output={
                            "task_id": task_id,
                            "error": agent_load_error,
                            "error_type": "agent_load_failed",
                            "reason": agent_load_reason,
                            "agent_id": payload.agent_id,
                        },
                    )
                return

            # 3a. A build agent can declare a required marketplace Base. A
            # standalone chat is initially attached to the user's lightweight
            # ``~workspace~`` so normal conversations do not provision an app.
            # Before this agent sees any project tools, replace only that
            # disposable attachment with a project created through the normal
            # Base pipeline. Never overwrite a user-selected real project.
            is_direct_chat_run = (
                auto_run_id is None
                and payload.parent_task_id is None
                and payload.channel_type is None
            )
            required_base_config = (agent_model.config or {}).get("required_base")
            if is_direct_chat_run and required_base_config:
                from .services.agent_required_base_workspace import (
                    RequiredBaseWorkspaceError,
                    ensure_chat_project_for_required_base,
                )

                setup_just_completed = bool(payload.workspace_setup_task_id)
                if await _defer_agent_task_for_workspace_setup(payload, pubsub):
                    return

                try:
                    required_workspace = await ensure_chat_project_for_required_base(
                        db,
                        user_id=UUID(payload.user_id),
                        chat_id=UUID(payload.chat_id),
                        required_base_config=required_base_config,
                        wait_for_setup=False,
                    )
                except RequiredBaseWorkspaceError as exc:
                    await _publish_error(pubsub, task_id, str(exc))
                    return
                except Exception as exc:
                    logger.exception(
                        "[WORKER] Required Base setup failed for agent=%s chat=%s",
                        agent_model.slug,
                        payload.chat_id,
                    )
                    await _publish_error(
                        pubsub,
                        task_id,
                        f"Failed to prepare the agent's required Base: {exc}",
                    )
                    return

                if required_workspace is not None:
                    project = required_workspace.project
                    project_id = str(project.id)
                    payload.project_id = project_id
                    payload.project_slug = project.slug
                    # A container from the former generic workspace cannot be
                    # valid for the newly-created Base project.
                    payload.container_id = None
                    payload.container_name = None
                    payload.container_directory = None
                    payload.project_context = {}
                    await _update_task_metadata_redis(
                        task_id,
                        {
                            "project_id": str(project.id),
                            "project_slug": project.slug,
                        },
                    )

                    if required_workspace.setup_task_id:
                        payload.workspace_setup_task_id = required_workspace.setup_task_id
                        payload.workspace_setup_retry_count = 0
                        if pubsub:
                            await pubsub.publish_agent_event(
                                task_id,
                                {
                                    "type": "workspace_preparing",
                                    "data": {
                                        "task_id": task_id,
                                        "chat_id": str(payload.chat_id),
                                        "project_id": str(project.id),
                                        "project_name": project.name,
                                        "project_slug": project.slug,
                                        "required_base_name": required_workspace.base.name,
                                        "setup_task_id": required_workspace.setup_task_id,
                                        "automatic": True,
                                    },
                                },
                            )
                        await _defer_agent_task_for_workspace_setup(payload, pubsub)
                        return

                    if (required_workspace.created or setup_just_completed) and pubsub:
                        await pubsub.publish_agent_event(
                            task_id,
                            {
                                "type": "workspace_ready",
                                "data": {
                                    "chat_id": str(payload.chat_id),
                                    "project_id": str(project.id),
                                    "project_name": project.name,
                                    "project_slug": project.slug,
                                    "required_base_name": required_workspace.base.name,
                                    "automatic": True,
                                },
                            },
                        )
                        # Backward compatibility for existing consumers that
                        # already know how to switch a chat's project.
                        await pubsub.publish_agent_event(
                            task_id,
                            {
                                "type": "workspace_attach_resumed",
                                "data": {
                                    "chat_id": str(payload.chat_id),
                                    "project_id": str(project.id),
                                    "project_name": project.name,
                                    "project_slug": project.slug,
                                    "required_base_name": required_workspace.base.name,
                                    "automatic": True,
                                },
                            },
                        )
                        logger.info(
                            "[WORKER] Auto-created project=%s from required base=%s "
                            "for chat=%s",
                            project.id,
                            required_workspace.base.slug,
                            payload.chat_id,
                        )

            # 3b. Persist agent identity for the audit / spend rollups.
            #
            # The dispatcher's preflight does NOT yet write an
            # ``invocation_subjects`` row (the full Phase-2 resolver has
            # dependencies on budget allocation that aren't wired yet).
            # Without a row, ``invocation_subjects`` is empty for every
            # automation run — the only trace of which agent executed
            # lives on the editable ``automation_actions.config.agent_id``
            # JSON field, so a post-run PATCH can rewrite history
            # (TC-03 Bug #19). Insert one here keyed off the loaded
            # ``agent_model`` so the run row is permanently joinable to
            # the agent that actually ran. Defaults match the existing
            # ``invocation_subject.PayerPolicy.INSTALLER`` /
            # ``CreditSource.OPENSAIL_CREDITS`` decision tree — the
            # full payer-policy resolver will replace this stub when
            # it lands without changing the public API surface.
            if auto_run_id is not None:
                from .models_automations import InvocationSubject
                from .services.automations.invocation_subject import (
                    CreditSource,
                    PayerPolicy,
                )

                # Idempotent — the worker may be re-entered after an
                # approval pause, and a duplicate INSERT would orphan the
                # audit chain. SELECT-then-INSERT is fine: the only writer
                # for this row at runtime is this branch (the dispatcher's
                # preflight stub leaves ``agent_id=NULL``; we'd just
                # update it).
                existing_subject_id = (
                    await db.execute(
                        select(InvocationSubject.id)
                        .where(InvocationSubject.automation_run_id == auto_run_id)
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if existing_subject_id is None:
                    db.add(
                        InvocationSubject(
                            automation_run_id=auto_run_id,
                            invoking_user_id=UUID(payload.user_id),
                            team_id=UUID(payload.team_id) if payload.team_id else None,
                            agent_id=agent_model.id,
                            payer_policy=PayerPolicy.INSTALLER.value,
                            credit_source=CreditSource.OPENSAIL_CREDITS.value,
                        )
                    )
                else:
                    from sqlalchemy import update as _sa_update

                    await db.execute(
                        _sa_update(InvocationSubject)
                        .where(InvocationSubject.id == existing_subject_id)
                        .where(InvocationSubject.agent_id.is_(None))
                        .values(agent_id=agent_model.id)
                    )
                await db.commit()

            # 4. Get model name
            model_name = payload.model_name
            if not model_name:
                user_id = UUID(payload.user_id)
                # ``.first()`` (not ``scalar_one_or_none``) — a user can
                # legitimately have one row per team for the same agent,
                # and any one of them carries the same ``selected_model``
                # we care about here. Crashing on duplicates would block
                # all delegated agent runs.
                result = await db.execute(
                    select(UserPurchasedAgent)
                    .where(
                        UserPurchasedAgent.user_id == user_id,
                        UserPurchasedAgent.agent_id == agent_model.id,
                    )
                    .limit(1)
                )
                user_purchase = result.scalars().first()
                model_name = (
                    user_purchase.selected_model
                    if user_purchase and user_purchase.selected_model
                    else agent_model.model or settings.default_model
                )

            # Perform the same team-aware guard in the worker as every
            # dispatch path eventually reaches here (chat, external API,
            # automations and channels).  It protects a new run before its
            # first provider call; the per-response path below protects each
            # following call as usage accrues.
            try:
                from .models_team import Team
                from .services.credit_service import check_credits

                owner_result = await db.execute(
                    select(User).where(User.id == UUID(payload.user_id))
                )
                billing_user = owner_result.scalar_one_or_none()
                if billing_user is not None:
                    raw_team_id = (
                        getattr(project, "team_id", None)
                        or payload.team_id
                        or billing_user.default_team_id
                    )
                    billing_team = None
                    if raw_team_id:
                        team_result = await db.execute(
                            select(Team).where(Team.id == UUID(str(raw_team_id)))
                        )
                        billing_team = team_result.scalar_one_or_none()
                    can_run, credit_error = await check_credits(
                        billing_user,
                        model_name,
                        team=billing_team,
                        db=db,
                    )
                    if not can_run:
                        await _publish_error(pubsub, task_id, credit_error)
                        return
            except Exception:
                # A temporary read failure must not turn into a stuck agent
                # task.  The durable per-response debit remains the source of
                # truth and will log any ledger failure separately.
                logger.warning(
                    "[WORKER] Credit preflight unavailable for task=%s; continuing to "
                    "the per-response ledger",
                    task_id,
                    exc_info=True,
                )

            # 5. Create model adapter
            model_adapter = await create_model_adapter(
                model_name=model_name,
                user_id=UUID(payload.user_id),
                db=db,
            )

            # 6. Create view-scoped tool registry if needed
            tools_override = None
            if payload.view_context:
                from .agent.tools.view_context import ViewContext
                from .agent.tools.view_scoped_factory import create_view_scoped_registry

                view_context_str = (
                    payload.view_context.get("view")
                    if isinstance(payload.view_context, dict)
                    else payload.view_context
                )
                if view_context_str:
                    view_context = ViewContext.from_string(view_context_str)
                    tools_override = create_view_scoped_registry(
                        view_context=view_context,
                        project_id=UUID(project_id),
                        container_id=(UUID(payload.container_id) if payload.container_id else None),
                        base_tool_names=(
                            agent_model.tools if isinstance(getattr(agent_model, "tools", None), list) else None
                        ),
                    )

            # 7. Create agent via adapter (submodule runner)
            #
            # Build an async approval handler that suspends until the user
            # responds via the frontend dialog (Allow / Deny).  This replaces
            # the submodule's env-var ApprovalManager (which defaults to
            # "allow" and never shows the user anything) with the orchestrator's
            # PendingUserInputManager backed by Redis pub/sub.
            from .agent.tools.approval_manager import (
                get_pending_input_manager,
                wait_for_approval_or_cancel,
            )

            _pending_mgr = get_pending_input_manager()

            async def _approval_handler(tool_name: str, parameters: dict, session_id: str) -> str:
                # Already approved for this session (user clicked "Allow All").
                if _pending_mgr.is_tool_approved(session_id, tool_name):
                    return "allow_once"

                approval_id, request = await _pending_mgr.request_approval(
                    tool_name, parameters, session_id
                )
                logger.info(
                    "[WORKER] Approval gate opened for %s (approval_id=%s)",
                    tool_name,
                    approval_id,
                )

                # Notify the frontend so it can show the approval dialog.
                # Serialize UUIDs in parameters so the event is JSON-safe.
                if pubsub:
                    await pubsub.publish_agent_event(
                        task_id,
                        {
                            "type": "approval_required",
                            "data": {
                                "approval_id": approval_id,
                                "tool": tool_name,
                                "parameters": _convert_uuids_to_strings(parameters),
                                "session_id": str(session_id),
                            },
                        },
                    )

                # Block until the user approves/denies or the task is cancelled.
                response = await wait_for_approval_or_cancel(
                    request, task_id=task_id, timeout_seconds=300.0
                )
                logger.info("[WORKER] Approval resolved for %s: %s", tool_name, response)
                return response or "stop"

            agent_run_obj = await _create_agent_runner(
                agent_model=agent_model,
                model_adapter=model_adapter,
                tools_override=tools_override,
                settings=settings,
                approval_handler=_approval_handler,
            )

            # Plumb ``contract.max_iterations`` onto the agent runner so the
            # cap declared on the automation actually fires. Mirrors the
            # ``chat.py:1146`` pattern. Without this the submodule defaults
            # to ``DEFAULT_MAX_ITERATIONS=0`` (unlimited) and a runaway
            # tool-call loop only stops at the worker timeout (TC-04 Bug #27).
            _max_iter = (payload.contract or {}).get("max_iterations") if payload.contract else None
            if _max_iter is not None:
                try:
                    _max_iter_int = int(_max_iter)
                except (TypeError, ValueError):
                    _max_iter_int = None
                if _max_iter_int is not None and _max_iter_int > 0:
                    inner = getattr(agent_run_obj, "inner", None)
                    if inner is not None and hasattr(inner, "max_iterations"):
                        inner.max_iterations = _max_iter_int
                        logger.info(
                            "[WORKER] Applied contract.max_iterations=%d to agent runner",
                            _max_iter_int,
                        )

            # 7b. Load MCP tools for this user/agent and inject into tool registry
            mcp_context: dict | None = None
            try:
                from .services.mcp.manager import get_mcp_manager

                mcp_mgr = get_mcp_manager()
                mcp_context = await mcp_mgr.get_user_mcp_context(
                    user_id=payload.user_id,
                    db=db,
                    agent_id=str(agent_model.id),
                    team_id=payload.team_id or None,
                    project_id=payload.project_id or None,
                )
                mcp_tools = mcp_context.get("tools", [])
                if mcp_tools:
                    tools_registry = getattr(agent_run_obj, "tools", None)
                    if tools_registry:
                        for mcp_tool in mcp_tools:
                            tools_registry.register(mcp_tool)
                        logger.info(
                            "[WORKER] Registered %d MCP tools for agent '%s'",
                            len(mcp_tools),
                            agent_model.slug,
                        )

                # Surface connectors that failed discovery (stale OAuth, 401,
                # etc.) — without this, the agent silently gets an empty tool
                # list for Notion/Linear/etc and confabulates "I don't have
                # access" when the user knows they attached it. The UI shows
                # a red dot via the `needs_reauth` flag; this log gives us a
                # breadcrumb when debugging reports like "agent says it can't
                # reach X."
                unavailable = mcp_context.get("unavailable_servers", [])
                if unavailable:
                    logger.warning(
                        "[WORKER] %d MCP connector(s) unavailable for agent '%s': %s",
                        len(unavailable),
                        agent_model.slug,
                        ", ".join(
                            f"{u.get('server_slug')}({u.get('reason')})" for u in unavailable
                        ),
                    )
            except Exception as mcp_err:
                logger.warning("[WORKER] MCP context loading failed (non-fatal): %s", mcp_err)

            # 7c. @-mention extras (per-turn only; never modify the agent record)
            #
            # Three independent paths, each gated on its own list being
            # non-empty so plain chats see zero added prompt content / tools:
            #
            #   - mention_mcp_config_ids -> register additional MCP tools
            #     for this turn, deduped against any MCPs the agent already
            #     has assigned via AgentMcpAssignment (so we don't double-pay
            #     tool-schema tokens).
            #
            #   - mention_agent_ids     -> register the call_agent tool so
            #     the calling agent can delegate one turn to another
            #     configured marketplace agent. This is the multi-agent
            #     layer; the in-process subagent tools (`task` etc.) in the
            #     tesslate-agent submodule are a separate, complementary
            #     mechanism and are unaffected here.
            #
            #   - mention_app_instance_ids -> append a lean hint block to
            #     the user's message body telling the agent which installed
            #     apps + actions are available. Does NOT touch the system
            #     prompt or the tool registry, so it preserves prompt-cache
            #     hits on the (stable) system message; the user message is
            #     turn-unique anyway.
            tools_registry = getattr(agent_run_obj, "tools", None)

            if payload.mention_mcp_config_ids and tools_registry is not None:
                try:
                    from .services.mcp.manager import get_mcp_manager

                    mcp_mgr = get_mcp_manager()
                    already_loaded_ma_ids: set[str] = set()
                    if mcp_context and mcp_context.get("mcp_configs"):
                        for cfg in mcp_context["mcp_configs"].values():
                            ma_id = (cfg.get("server") or {}).get("marketplace_agent_id")
                            if ma_id:
                                already_loaded_ma_ids.add(str(ma_id))

                    extra_ctx = await mcp_mgr.get_extra_configs(
                        list(payload.mention_mcp_config_ids),
                        payload.user_id,
                        db,
                        exclude_marketplace_agent_ids=already_loaded_ma_ids,
                    )
                    extra_tools = extra_ctx.get("tools", [])
                    if extra_tools:
                        for extra_tool in extra_tools:
                            tools_registry.register(extra_tool)
                        logger.info(
                            "[WORKER] @mcp: registered %d extra MCP tool(s) "
                            "for this turn (agent='%s')",
                            len(extra_tools),
                            agent_model.slug,
                        )
                    # Merge extra mcp_configs so executors can reconnect.
                    if extra_ctx.get("mcp_configs"):
                        merged = dict((mcp_context or {}).get("mcp_configs") or {})
                        merged.update(extra_ctx["mcp_configs"])
                        # Ensure context dict reflects the merge (built later
                        # may re-read mcp_context; keep both authoritative).
                        if mcp_context is not None:
                            mcp_context["mcp_configs"] = merged
                except Exception as extra_err:
                    logger.warning(
                        "[WORKER] @mcp extras failed (non-fatal): %s",
                        extra_err,
                    )

            if payload.mention_agent_ids and tools_registry is not None:
                try:
                    from sqlalchemy import select as _sa_select

                    from .agent.tools.agent_ops import register_call_agent_tool

                    auth_uuids: list[UUID] = []
                    for raw in payload.mention_agent_ids:
                        try:
                            auth_uuids.append(UUID(str(raw)))
                        except (TypeError, ValueError):
                            continue

                    authorized_agents: list[dict[str, str]] = []
                    if auth_uuids:
                        ag_result = await db.execute(
                            _sa_select(MarketplaceAgent).where(MarketplaceAgent.id.in_(auth_uuids))
                        )
                        for ag in ag_result.scalars().all():
                            authorized_agents.append(
                                {
                                    "id": str(ag.id),
                                    "slug": ag.slug or "",
                                    "name": getattr(ag, "name", "") or "",
                                }
                            )

                    if authorized_agents:
                        register_call_agent_tool(
                            tools_registry, authorized_agents=authorized_agents
                        )
                        logger.info(
                            "[WORKER] @agent: registered call_agent with "
                            "%d authorized delegate(s) for agent '%s'",
                            len(authorized_agents),
                            agent_model.slug,
                        )
                except Exception as agent_err:
                    logger.warning(
                        "[WORKER] @agent tool registration failed (non-fatal): %s",
                        agent_err,
                    )

            container_id = UUID(payload.container_id) if payload.container_id else None
            container_name = payload.container_name
            container_directory = payload.container_directory

            if container_id and project_id and (not container_name or container_directory is None):
                container_result = await db.execute(
                    select(Container).where(
                        Container.id == container_id,
                        Container.project_id == UUID(project_id),
                    )
                )
                container = container_result.scalar_one_or_none()
                if container:
                    container_name = _resolve_container_name(container)
                    if container.directory and container.directory != ".":
                        container_directory = container.directory

            # Discover available skills for this agent (progressive disclosure)
            from .services.skill_discovery import discover_skills

            available_skills = await discover_skills(
                agent_id=agent_model.id if agent_model else None,
                user_id=UUID(payload.user_id),
                project_id=project_id if project_id else None,
                container_name=container_name,
                db=db,
            )

            chat_history = payload.chat_history or await _get_chat_history(
                UUID(payload.chat_id), db, limit=10
            )

            if project:
                project_context = payload.project_context or {
                    "project_name": project.name,
                    "project_description": project.description,
                }
            else:
                project_context = payload.project_context or {}

            # Add available skills to project_context (for prompt injection)
            if available_skills:
                project_context["available_skills"] = available_skills

            # Add MCP resource/prompt catalogs to project_context for prompt injection
            if mcp_context:
                if mcp_context.get("resource_catalog"):
                    project_context["mcp_resource_catalog"] = mcp_context["resource_catalog"]
                if mcp_context.get("prompt_catalog"):
                    project_context["mcp_prompt_catalog"] = mcp_context["prompt_catalog"]

            # Inject TESSLATE.md into the system prompt via project_context.
            # Guard prevents a double-read when chat.py already populated it
            # for inline (non-queued) execution paths.
            if project and not project_context.get("tesslate_context"):
                tesslate_ctx = await _build_tesslate_context(
                    project,
                    UUID(payload.user_id),
                    db,
                    container_name=container_name,
                    container_directory=container_directory,
                )
                if tesslate_ctx:
                    project_context["tesslate_context"] = tesslate_ctx

            # Single-call run-context enrichment (data store overview,
            # @data / @project deep-dive). Idempotent — if chat.py already
            # populated either block on the inline path, RunContextEnrichment
            # rewrites it from the same inputs so the worker never sees a
            # stale view of the data store.
            if project:
                from .services.agent_context import (
                    MentionPayload,
                    enrich_project_context_for_run,
                )

                _run_ctx = await enrich_project_context_for_run(
                    db=db,
                    project=project,
                    user_id=UUID(payload.user_id),
                    mentions=MentionPayload.from_lists(
                        data_collection_refs=payload.mention_data_collection_refs,
                        project_ids=payload.mention_project_ids,
                    ),
                )
                _run_ctx.apply(project_context)

            # Warm the local plan mirror from Redis before the agent builds its prompt.
            from .services.plan_manager import PlanManager

            payload_context = {
                "user_id": UUID(payload.user_id),
                "project_id": UUID(project_id) if project_id else None,
            }
            active_plan = await PlanManager.get_plan(payload_context)

            # Tier snapshot for agent context (compute_tier-aware tools read these).
            from .services.agent_context import build_tier_snapshot

            _tier_snapshot = await build_tier_snapshot(project, db)
            _tier_containers = _tier_snapshot.get("containers", [])
            execution_profile = _derive_execution_profile(
                project,
                _tier_containers,
                chat_history,
            )

            # 8. Build execution context (same structure as chat.py)
            #
            # ``allowed_scopes`` is set explicitly only for agents that
            # need authoring tools (agent-builder). For every other
            # interactive agent the key is omitted, which preserves the
            # existing pass-through behavior in marketplace_ops gates
            # (they accept ``None`` as "no enforcement"). Automation-driven
            # runs derive their scopes from the contract elsewhere.
            from .services.automations.scopes import (
                AUTOMATIONS_WRITE,
                MARKETPLACE_AUTHOR,
            )

            _BUILTIN_AGENT_SCOPES: dict[str, set[str]] = {
                "agent-builder": {MARKETPLACE_AUTHOR, AUTOMATIONS_WRITE},
                "automation-builder": {MARKETPLACE_AUTHOR, AUTOMATIONS_WRITE},
            }
            _agent_slug = getattr(agent_model, "slug", None)
            _admin_scopes = _BUILTIN_AGENT_SCOPES.get(_agent_slug)
            context = {
                "user_id": UUID(payload.user_id),
                "project_id": UUID(project_id) if project_id else None,
                "project_slug": payload.project_slug,
                "container_directory": container_directory,
                "chat_id": UUID(payload.chat_id),
                "task_id": task_id,
                "resume_attempt": payload.resume_attempt,
                "resume_reason": payload.resume_reason,
                "cancellation_check": (
                    (lambda: pubsub.is_cancelled(task_id)) if pubsub is not None else (lambda: False)
                ),
                # The pubsub handle lets in-tool HITL paths
                # (e.g., request_review) emit SSE events directly so the
                # chat surface can render an interactive card while the
                # tool blocks waiting for a user click.
                "pubsub": pubsub,
                "db": db,
                "chat_history": chat_history,
                "project_context": project_context,
                "execution_profile": execution_profile,
                "edit_mode": payload.edit_mode,
                "container_id": container_id,
                "container_name": container_name,
                "view_context": (
                    payload.view_context.get("view")
                    if isinstance(payload.view_context, dict)
                    else payload.view_context
                ),
                "model_name": model_name,
                "agent_id": agent_model.id,
                "required_base": (agent_model.config or {}).get("required_base"),
                "_active_plan": active_plan,
                "available_skills": available_skills,
                "attachments": payload.attachments,
                "api_key_scopes": payload.api_key_scopes,
                # Per-built-in scope grant. Falls back to None so the
                # marketplace_ops defensive gate (``if allowed_scopes and
                # MARKETPLACE_AUTHOR not in allowed_scopes``) keeps its
                # current pass-through semantics for every other agent.
                "allowed_scopes": _admin_scopes,
                # Volume routing — Hub is the live source of truth for node
                # placement; cache_node is NOT passed (dead DB field).
                "volume_id": project.volume_id if project else None,
                "compute_tier": project.compute_tier if project else None,
                "active_compute_pod": project.active_compute_pod if project else None,
                "environment_status": project.environment_status if project else None,
                "containers": _tier_containers,
                # Phase 1: forward automation binding into the agent context so
                # tools / future ContractGate (Phase 2) can read it. Always
                # present (None for non-automation invocations) so consumers
                # can use a uniform ``context.get("automation_run_id")`` check.
                "automation_run_id": payload.automation_run_id,
                "automation_id": payload.automation_id,
                "contract": payload.contract,
                "trigger_kind": payload.trigger_kind,
                "trigger_payload": payload.trigger_payload,
                "trigger_event_id": payload.trigger_event_id,
                # Per-turn @-mentions. The call_agent executor reads
                # ``mention_agent_ids`` to validate that the LLM didn't
                # invent an agent_id outside the user's authorization.
                # Empty lists are the legacy / no-mention default.
                "mention_agent_ids": list(payload.mention_agent_ids or []),
                "mention_mcp_config_ids": list(payload.mention_mcp_config_ids or []),
                "mention_app_instance_ids": list(payload.mention_app_instance_ids or []),
                "parent_task_id": payload.parent_task_id,
            }

            # Inject MCP server configs so adapter executors can connect per-call
            if mcp_context and mcp_context.get("mcp_configs"):
                context["mcp_configs"] = mcp_context["mcp_configs"]

            # Inject channel context for send_message "reply" channel
            if payload.channel_config_id:
                context["channel_config_id"] = payload.channel_config_id
                context["channel_jid"] = payload.channel_jid
                context["channel_type"] = payload.channel_type

            # Inject cross-platform context for gateway-originated tasks
            if payload.channel_type and project:
                cross_platform = await _build_cross_platform_context(
                    chat_id=UUID(payload.chat_id),
                    user_id=UUID(payload.user_id),
                    project_id=UUID(project_id) if project_id else None,
                    platform=payload.channel_type,
                    db=db,
                )
                if cross_platform:
                    project_context["cross_platform_context"] = cross_platform

            # 9. Create placeholder Message before agent loop (crash-safe)
            assistant_message = Message(
                chat_id=UUID(payload.chat_id),
                role="assistant",
                content="",  # Will be finalized on completion
                message_metadata={
                    "agent_mode": True,
                    "agent_type": agent_model.agent_type,
                    "agent_name": agent_model.name,
                    "agent_icon": agent_model.icon,
                    "agent_avatar_url": agent_model.avatar_url,
                    "completion_reason": "in_progress",
                    "executed_by": "worker",
                    "task_id": task_id,
                },
            )
            db.add(assistant_message)
            await db.commit()
            await db.refresh(assistant_message)
            message_id = assistant_message.id
            context["assistant_message_id"] = message_id

            # Back-fill ticket → message FK so the AgentTask row points to
            # the assistant Message created above.
            if claimed_ticket_id is not None:
                from .services.agent_tickets import update_ticket_message_id

                with contextlib.suppress(Exception):
                    await update_ticket_message_id(
                        db, ticket_id=claimed_ticket_id, message_id=message_id
                    )

            # Create file checkpoint before agent execution (for /undo file revert).
            # Uses git ghost commits when a container is running, or a btrfs
            # volume fork for K8s tier-0 projects (no pod).
            checkpoint_hash = None
            if project_id:
                try:
                    from .services.checkpoint_manager import CheckpointManager

                    ckpt_mgr = CheckpointManager(
                        user_id=UUID(payload.user_id),
                        project_id=project_id,
                        volume_id=project.volume_id if project else None,
                    )
                    checkpoint_hash = await ckpt_mgr.create_checkpoint()
                    if checkpoint_hash:
                        logger.info(
                            "[WORKER] Checkpoint %s for task %s",
                            checkpoint_hash[:12],
                            task_id,
                        )
                except Exception as ckpt_err:
                    logger.warning("[WORKER] Checkpoint failed (non-fatal): %s", ckpt_err)

            # Update chat status to running
            chat_result = await db.execute(select(Chat).where(Chat.id == UUID(payload.chat_id)))
            chat = chat_result.scalar_one_or_none()
            if chat:
                chat.status = "running"
                await db.commit()

            # 10. Run agent and publish events — progressive step persistence
            final_response = ""
            iterations = 0
            tool_calls_made = 0
            completion_reason = "interrupted"
            session_id = None
            event_count = 0
            project_changed = False
            project_started_by_agent = False
            preview_task_id: str | None = None
            agent_completed = False
            agent_succeeded = False
            terminal_error: str | None = None
            resume_scheduled = False
            credit_usage_events = 0
            credit_deduction_failures = 0

            def _credit_usage_value(data: dict, key: str) -> int:
                """Normalise untrusted adapter usage into non-negative ints."""
                try:
                    return max(0, int(data.get(key, 0) or 0))
                except (TypeError, ValueError):
                    return 0

            # AgentStep sink: called by run_turn() for every agent_step event so
            # the worker loop only handles cancellation, pubsub, and completion.
            _step_idx = 0

            async def _step_sink(event: dict) -> None:
                nonlocal _step_idx
                if event.get("type") != "agent_step":
                    return
                step_data = event.get("data", {})
                normalized = _build_step_dict(step_data, _convert_uuids_to_strings)
                persisted = await _persist_agent_step(
                    db,
                    message_id=message_id,
                    chat_id=UUID(payload.chat_id),
                    step_index=_step_idx,
                    step_data=normalized,
                )
                if not persisted:
                    raise RuntimeError(
                        "Agent output target was removed while the task was running"
                    )
                _step_idx += 1

            from .services.tesslate_agent_adapter import AgentAdapterContext

            adapter_ctx = AgentAdapterContext(
                project_id=str(project_id) if project_id else "",
                user_id=payload.user_id,
                extra=context,
            )

            # @-mention hint block — appended to the END of the user message
            # (turn-unique content) so the system-prompt cache breakpoint
            # stays intact for non-mention turns. The block resolves the
            # `@<slug>` tokens the user typed into structured metadata so the
            # agent picks the right tool and the right id without guessing.
            #
            # All three kinds share one block under a single `[mentions]`
            # heading; the system prompt teaches the agent to read it.
            effective_message = payload.message or ""
            if (
                payload.mention_agent_ids
                or payload.mention_mcp_config_ids
                or payload.mention_app_instance_ids
            ):
                try:
                    from sqlalchemy import select as _sa_select
                    from sqlalchemy.orm import selectinload as _selectinload

                    from .models import (
                        AppInstance,
                        MarketplaceApp,
                        UserMcpConfig,
                    )
                    from .models import (
                        MarketplaceAgent as _MarketplaceAgent,
                    )
                    from .models_automations import (
                        AppAction,
                        AppDataResource,
                        AppView,
                    )

                    sections: list[str] = []

                    # ------------------------------------------------------
                    # @agent — list slug + id so call_agent gets the right id
                    # ------------------------------------------------------
                    if payload.mention_agent_ids:
                        agent_uuids: list[UUID] = []
                        for raw in payload.mention_agent_ids:
                            try:
                                agent_uuids.append(UUID(str(raw)))
                            except (TypeError, ValueError):
                                continue
                        if agent_uuids:
                            res = await db.execute(
                                _sa_select(_MarketplaceAgent).where(
                                    _MarketplaceAgent.id.in_(agent_uuids)
                                )
                            )
                            lines = []
                            for ag in res.scalars().all():
                                lines.append(
                                    f"  - @{ag.slug or '?'} (name={ag.name or '?'}, "
                                    f"agent_id={ag.id})"
                                )
                            if lines:
                                sections.append(
                                    "agents (delegate one stateless turn via the `call_agent` tool):\n"
                                    + "\n".join(lines)
                                )

                    # ------------------------------------------------------
                    # @mcp — confirm which connector tools just got injected
                    # ------------------------------------------------------
                    if payload.mention_mcp_config_ids:
                        mcp_uuids: list[UUID] = []
                        for raw in payload.mention_mcp_config_ids:
                            try:
                                mcp_uuids.append(UUID(str(raw)))
                            except (TypeError, ValueError):
                                continue
                        if mcp_uuids:
                            res = await db.execute(
                                _sa_select(UserMcpConfig)
                                .where(
                                    UserMcpConfig.id.in_(mcp_uuids),
                                    UserMcpConfig.user_id == UUID(payload.user_id),
                                )
                                .options(_selectinload(UserMcpConfig.marketplace_agent))
                            )
                            lines = []
                            for umc in res.scalars().all():
                                ma = umc.marketplace_agent
                                slug = (ma.slug if ma else None) or "custom"
                                # The bridge normalises hyphens to underscores
                                # in the tool prefix; reflect that so the
                                # agent knows the actual tool names.
                                ns = slug.replace("-", "_")
                                name = (ma.name if ma else None) or slug
                                lines.append(
                                    f"  - @{slug} (name={name}) — "
                                    f"tools registered as `mcp__{ns}__*` "
                                    "for THIS turn only"
                                )
                            if lines:
                                sections.append(
                                    "connectors (active for this turn — call the listed tool names directly):\n"
                                    + "\n".join(lines)
                                )

                    # ------------------------------------------------------
                    # @app — full action signatures, views, data resources
                    # ------------------------------------------------------
                    if payload.mention_app_instance_ids:
                        app_uuids: list[UUID] = []
                        for raw in payload.mention_app_instance_ids:
                            try:
                                app_uuids.append(UUID(str(raw)))
                            except (TypeError, ValueError):
                                continue
                        if app_uuids:
                            inst_result = await db.execute(
                                _sa_select(AppInstance)
                                .where(
                                    AppInstance.id.in_(app_uuids),
                                    AppInstance.installer_user_id == UUID(payload.user_id),
                                )
                                .options(
                                    _selectinload(AppInstance.app).selectinload(
                                        MarketplaceApp.versions
                                    )
                                )
                            )
                            instances = list(inst_result.scalars().all())
                            version_ids = [i.app_version_id for i in instances if i.app_version_id]
                            actions_by_v: dict[UUID, list[AppAction]] = {}
                            views_by_v: dict[UUID, list[AppView]] = {}
                            dr_by_v: dict[UUID, list[AppDataResource]] = {}
                            if version_ids:
                                ar = await db.execute(
                                    _sa_select(AppAction).where(
                                        AppAction.app_version_id.in_(version_ids)
                                    )
                                )
                                for a in ar.scalars().all():
                                    actions_by_v.setdefault(a.app_version_id, []).append(a)
                                vr = await db.execute(
                                    _sa_select(AppView).where(
                                        AppView.app_version_id.in_(version_ids)
                                    )
                                )
                                for v in vr.scalars().all():
                                    views_by_v.setdefault(v.app_version_id, []).append(v)
                                drr = await db.execute(
                                    _sa_select(AppDataResource).where(
                                        AppDataResource.app_version_id.in_(version_ids)
                                    )
                                )
                                for d in drr.scalars().all():
                                    dr_by_v.setdefault(d.app_version_id, []).append(d)

                            for inst in instances:
                                slug = (
                                    getattr(inst.app, "slug", "") if inst.app is not None else ""
                                ) or "?"
                                lines: list[str] = [f"  - @{slug} app_instance_id={inst.id}"]
                                actions = actions_by_v.get(inst.app_version_id, [])
                                if actions:
                                    lines.append(
                                        "    actions (call via invoke_app_action with this exact app_instance_id):"
                                    )
                                    for a in actions:
                                        # Pull the top-level input keys so the
                                        # agent sees the parameter shape
                                        # without us inlining the full
                                        # JSON schema.
                                        keys: list[str] = []
                                        try:
                                            schema = a.input_schema or {}
                                            props = (
                                                (schema.get("properties") or {})
                                                if isinstance(schema, dict)
                                                else {}
                                            )
                                            keys = list(props.keys())
                                        except Exception:
                                            keys = []
                                        keys_str = (
                                            f" input_keys=[{', '.join(keys)}]" if keys else ""
                                        )
                                        rc = a.required_connectors or []
                                        rc_str = f" needs_connectors={list(rc)}" if rc else ""
                                        lines.append(f"      - {a.name}{keys_str}{rc_str}")
                                else:
                                    lines.append("    actions: (none declared in manifest)")
                                views = views_by_v.get(inst.app_version_id, [])
                                if views:
                                    lines.append(
                                        "    views: "
                                        + ", ".join(f"{v.name} ({v.kind})" for v in views)
                                    )
                                drs = dr_by_v.get(inst.app_version_id, [])
                                if drs:
                                    lines.append(
                                        "    data_resources: " + ", ".join(d.name for d in drs)
                                    )

                                # Bridge to the project's workspace-data store
                                # so the agent knows it can READ + ANALYZE what
                                # this app has stored, not just invoke its
                                # actions. Apps installed in a project share
                                # the project's OPENSAIL_DATA_* env contract
                                # via the auto-inject path — the data they
                                # write is queryable via the workspace_data
                                # tool. Surfaces collection names + counts
                                # only when the project actually has any.
                                try:
                                    from .services import workspace_data as wd

                                    coll_rows = await wd.list_collections(db, inst.project_id)
                                    if coll_rows:
                                        coll_summaries: list[str] = []
                                        for c in coll_rows[:10]:
                                            n = await wd.collection_record_count(db, c.id)
                                            coll_summaries.append(f"{c.name} ({n})")
                                        lines.append(
                                            "    workspace_data collections "
                                            "(this app shares the project's "
                                            "built-in data store — use the "
                                            "workspace_data tool's summarize / "
                                            "schema / aggregate / query actions "
                                            "to read or analyze): " + ", ".join(coll_summaries)
                                        )
                                except Exception as wd_err:
                                    logger.debug(
                                        "[WORKER] @app data-store hint skipped: %s",
                                        wd_err,
                                    )
                                sections.append("\n".join(lines))

                    if sections:
                        # The wrapper text is the same every time the block
                        # appears; the system prompt explains how to read it.
                        # Keeping the explanation inline as well so a model
                        # without our updated system prompt still gets a
                        # nudge.
                        hint_block = (
                            "\n\n[mentions]\n"
                            "The user attached structured @-mentions to this "
                            "message. Treat them as authoritative — do not "
                            "guess slugs or ids; use the values below.\n\n" + "\n\n".join(sections)
                        )
                        effective_message = effective_message + hint_block
                        logger.info(
                            "[WORKER] @-mentions: annotated message "
                            "(agents=%d mcps=%d apps=%d) for agent '%s'",
                            len(payload.mention_agent_ids),
                            len(payload.mention_mcp_config_ids),
                            len(payload.mention_app_instance_ids),
                            agent_model.slug,
                        )
                except Exception as mention_err:
                    logger.warning(
                        "[WORKER] @-mention hint block failed (non-fatal): %s",
                        mention_err,
                    )

            agent_loop_started_at = time.monotonic()
            try:
                async for event in agent_run_obj.run_turn(
                    effective_message, adapter_ctx, event_sink=_step_sink
                ):
                    event_count += 1
                    event_type = event.get("type", "unknown")

                    # Check for cancellation between events
                    if pubsub and await pubsub.is_cancelled(task_id):
                        logger.info(f"[WORKER] Task {task_id} cancelled by client")
                        # If a newer task has already taken over the chat lock,
                        # exit quietly — the new task owns DB/stream state now.
                        if agent_lock_enabled:
                            holder = await pubsub.get_chat_lock(chat_id)
                            if holder and holder != task_id:
                                logger.info(
                                    f"[WORKER] Task {task_id} lock stolen by {holder}; "
                                    f"exiting quietly"
                                )
                                lock_stolen = True
                                lock_acquired = False
                                completion_reason = "superseded"
                                break
                        completion_reason = "cancelled"
                        final_response = "Request was cancelled."
                        await pubsub.publish_agent_event(
                            task_id,
                            {
                                "type": "complete",
                                "data": {
                                    "final_response": final_response,
                                    "iterations": iterations,
                                    "tool_calls_made": tool_calls_made,
                                    "completion_reason": "cancelled",
                                },
                            },
                        )
                        break

                    if event_type == "complete":
                        complete_data = event.get("data", {})
                        agent_completed = True
                        agent_succeeded = bool(complete_data.get("success", True))
                        final_response = complete_data.get("final_response", "")
                        iterations = complete_data.get("iterations", iterations)
                        tool_calls_made = complete_data.get("tool_calls_made", tool_calls_made)
                        completion_reason = complete_data.get(
                            "completion_reason", completion_reason
                        )
                        session_id = complete_data.get("session_id")
                        terminal_error = complete_data.get("error")

                        if not agent_succeeded and not final_response:
                            final_response = (
                                "The agent could not complete this request. "
                                + (terminal_error or "No successful completion was received.")
                            )

                        project_changed = bool(context.get("project_changed", project_changed))
                        if (
                            agent_succeeded
                            and project_changed
                            and completion_reason != "cancelled"
                            and project is not None
                        ):
                            try:
                                preview_task_id = str(uuid4())
                                complete_data["preview"] = {
                                    "status": "starting",
                                    "task_id": preview_task_id,
                                }
                                complete_data["project_started"] = False
                                from .services.task_queue import get_task_queue

                                await get_task_queue().enqueue(
                                    "start_project_preview_task",
                                    {
                                        "agent_task_id": task_id,
                                        "preview_task_id": preview_task_id,
                                        "project_id": str(project.id),
                                        "user_id": payload.user_id,
                                        "restart_required": bool(
                                            context.get("preview_restart_required")
                                        ),
                                        "mutation_paths": list(
                                            context.get("project_mutation_paths", []) or []
                                        ),
                                        "automation_run_id": str(auto_run_id)
                                        if auto_run_id is not None
                                        else None,
                                    },
                                )
                                if pubsub:
                                    await pubsub.publish_agent_event(
                                        task_id,
                                        {
                                            "type": "preview_starting",
                                            "data": {
                                                "task_id": task_id,
                                                "preview_task_id": preview_task_id,
                                                "project_id": str(project.id),
                                                "restart_required": bool(
                                                    context.get("preview_restart_required")
                                                ),
                                            },
                                        },
                                    )
                            except Exception as start_err:
                                logger.warning(
                                    "[WORKER] Failed to enqueue preview lifecycle for project %s: %s",
                                    project.id,
                                    start_err,
                                )
                                preview_task_id = None

                    elif event_type == "model_usage":
                        # ``model_usage`` is an internal runner event, not a
                        # chat event.  It is emitted once for every successful
                        # provider response and receives a durable idempotency
                        # key so an ARQ retry cannot bill that response twice.
                        usage_data = event.get("data", {})
                        if not isinstance(usage_data, dict):
                            usage_data = {}
                        usage_model = str(usage_data.get("model") or model_name)
                        usage_iteration = _credit_usage_value(usage_data, "iteration")
                        try:
                            from .services.credit_service import deduct_credits

                            raw_team_id = getattr(project, "team_id", None) or payload.team_id
                            usage_team_id = (
                                UUID(str(raw_team_id)) if raw_team_id else None
                            )
                            credit_result = await deduct_credits(
                                db=db,
                                user_id=UUID(payload.user_id),
                                model_name=usage_model,
                                tokens_in=_credit_usage_value(usage_data, "tokens_input"),
                                tokens_out=_credit_usage_value(usage_data, "tokens_output"),
                                agent_id=agent_model.id,
                                project_id=UUID(project_id) if project_id else None,
                                team_id=usage_team_id,
                                request_id=f"agent:{task_id}:model:{usage_iteration}",
                            )
                            credit_usage_events += 1
                            credit_deduction_failures = 0

                            # The UI already consumes this stable public event
                            # to update the header allocation balance.  Never
                            # forward ``model_usage`` itself: it is internal
                            # accounting data, not a new frontend contract.
                            if pubsub:
                                await pubsub.publish_agent_event(
                                    task_id,
                                    {
                                        "type": "credits_used",
                                        "data": {
                                            **credit_result,
                                            "iteration": usage_iteration,
                                            "model": usage_model,
                                        },
                                    },
                                )

                            # BYOK calls are always permitted, even when the
                            # shared platform allocation is empty.  For hosted
                            # calls, stop before the next LLM request while
                            # retaining any tools the current response ran.
                            if (
                                credit_result.get("credit_enforcement_enabled", True)
                                and
                                not credit_result.get("is_byok")
                                and (
                                    credit_result.get("new_balance", 0) <= 0
                                    or credit_result.get("allocation_exhausted", False)
                                )
                            ):
                                context["credit_limit_reached"] = True
                                context["credit_limit_message"] = (
                                    "Your individual allocation has been reached. The changes already "
                                    "made have been kept; ask a team administrator for more capacity."
                                    if credit_result.get("allocation_exhausted", False)
                                    else "Your team has no credits remaining. The changes already made "
                                    "have been kept; add credits to continue."
                                )
                        except Exception:
                            # Accounting must be observable but must not make
                            # a healthy generation fail because its ledger is
                            # temporarily unavailable.  A future event retries
                            # independently; this mirrors the platform's
                            # non-blocking credit-service contract.
                            credit_deduction_failures += 1
                            logger.exception(
                                "[WORKER] Credit deduction failed for task=%s iteration=%s "
                                "(consecutive failures=%s)",
                                task_id,
                                usage_iteration,
                                credit_deduction_failures,
                            )
                        continue

                    elif event_type == "tool_error":
                        err_data = event.get("data", {})
                        logger.warning(
                            "[WORKER] Tool error in task %s: tool=%s iteration=%s error=%s",
                            task_id,
                            err_data.get("tool_name"),
                            err_data.get("iteration"),
                            err_data.get("error"),
                        )

                    elif event_type == "agent_step":
                        step_data = event.get("data", {})
                        tool_names = {
                            tool_call.get("name")
                            for tool_call in step_data.get("tool_calls", [])
                            if isinstance(tool_call, dict)
                        }
                        project_changed = bool(context.get("project_changed", project_changed))
                        iterations = max(iterations, int(step_data.get("iteration") or 0))
                        tool_calls_made += len(tool_names)
                        project_started_by_agent = project_started_by_agent or (
                            "project_start" in tool_names
                        )

                    # Publish event to Redis Stream for API pod to forward to SSE
                    if pubsub:
                        await pubsub.publish_agent_event(task_id, event)

            except asyncio.CancelledError:
                completion_reason = "interrupted"
                terminal_error = "The agent execution was interrupted before it completed."
                final_response = (
                    "The agent was interrupted before completion. Any changes already written "
                    "have been kept; you can continue from the current project state."
                )
                try:
                    resume_scheduled = await asyncio.shield(
                        _schedule_interrupted_agent_resume(payload, pubsub)
                    )
                except Exception:
                    logger.exception("[WORKER] Failed to schedule interrupted-task recovery")
                if resume_scheduled:
                    final_response = (
                        "The worker was interrupted after preserving completed changes. "
                        "The platform is resuming this task once from the current workspace state."
                    )
                    terminal_error = None
                if pubsub:
                    with contextlib.suppress(Exception):
                        if not resume_scheduled:
                            await _publish_error(pubsub, task_id, terminal_error)
                with contextlib.suppress(Exception):
                    if not resume_scheduled:
                        await _update_task_status_redis(task_id, "failed", error=terminal_error)
                if resume_scheduled:
                    return
                raise

            finally:
                task_succeeded = agent_completed and agent_succeeded
                if not task_succeeded and not final_response:
                    final_response = (
                        "The agent did not complete this request. Any changes already written "
                        "have been kept; you can continue from the current project state."
                    )
                # Finalize Message regardless of how we exit the loop
                logger.info(
                    f"[WORKER] Agent finished: task={task_id}, events={event_count}, "
                    f"iterations={iterations}, tool_calls={tool_calls_made}"
                )

                # 11. Increment usage count
                agent_model.usage_count = (agent_model.usage_count or 0) + 1
                db.add(agent_model)

                # 12. Finalize the placeholder Message with summary metadata.
                #
                # Re-SELECT by id rather than mutating the long-held ORM object:
                # the frontend can delete the placeholder while the agent is
                # running (follow-up message, regenerate, clear chat), and
                # blindly UPDATE-ing a vanished PK raises StaleDataError mid-
                # flush — which poisons the session and also takes down the
                # chat-status UPDATE below.
                stale_msg = (
                    await db.execute(select(Message).where(Message.id == message_id))
                ).scalar_one_or_none()

                if stale_msg is None:
                    logger.warning(
                        "[WORKER] Placeholder message %s deleted during task %s — "
                        "skipping Message finalize (agent work preserved in agent_steps)",
                        message_id,
                        task_id,
                    )
                else:
                    stale_msg.content = final_response
                    final_metadata = {
                        "agent_mode": True,
                        "agent_type": agent_model.agent_type,
                        "agent_name": agent_model.name,
                        "agent_icon": agent_model.icon,
                        "agent_avatar_url": agent_model.avatar_url,
                        "iterations": iterations,
                        "tool_calls_made": tool_calls_made,
                        "execution_profile": execution_profile,
                        "completion_reason": completion_reason,
                        "error": terminal_error,
                        "partial_work_preserved": bool(project_changed and not task_succeeded),
                        "recovery": {
                            "resume_attempt": payload.resume_attempt,
                            "resume_scheduled": resume_scheduled,
                            "resume_reason": payload.resume_reason,
                        },
                        "last_completed_step": _step_idx - 1 if _step_idx else None,
                        "timings_ms": {
                            "total": int((time.monotonic() - task_started_at) * 1000),
                            "context": int(
                                ((agent_loop_started_at or time.monotonic()) - task_started_at)
                                * 1000
                            ),
                            "agent_loop": int(
                                (time.monotonic() - (agent_loop_started_at or task_started_at))
                                * 1000
                            ),
                        },
                        "credit_usage_events": credit_usage_events,
                        "credit_deduction_failures": credit_deduction_failures,
                        "session_id": session_id,
                        "executed_by": "worker",
                        "task_id": task_id,
                        "checkpoint_hash": checkpoint_hash,
                        "preview": (
                            {"status": "starting", "task_id": preview_task_id}
                            if preview_task_id
                            else {"status": "not_needed"}
                        ),
                        "trajectory_path": (
                            f".tesslate/trajectories/trajectory_{session_id}.json"
                            if session_id
                            else None
                        ),
                        # Steps are now in agent_steps table, not here
                        "steps_table": True,
                    }
                    stale_msg.message_metadata = final_metadata
                    db.add(stale_msg)

                if project and project_changed:
                    settings = dict(project.settings or {})
                    settings["has_agent_mutations"] = True
                    project.settings = settings

                # Update chat status — but skip if our lock was stolen.
                # The new owner already set status="running"; we must not
                # flip it back to "active"/"completed".
                if chat and not lock_stolen:
                    chat.status = "completed" if task_succeeded else "active"
                await db.commit()

                # 12b. CAS checkpoint snapshot — runs AFTER the finalize commit
                # so a stuck FileOps / Volume Hub gRPC can't widen the
                # placeholder-deletion race window. Checkpoint is best-effort;
                # the 5s cap is tight because we're now off the critical path.
                if (
                    project
                    and getattr(project, "volume_id", None)
                    and task_succeeded
                ):
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(
                            _create_agent_checkpoint(
                                project.volume_id,
                                final_response or "Agent task completed",
                            ),
                            timeout=5.0,
                        )

            # 13. Auto-generate chat title on first message (non-blocking)
            # Skip if our lock was stolen — the live owner will handle titling.
            if task_succeeded and not lock_stolen:
                await _auto_title_chat(
                    chat,
                    model_adapter,
                    payload.message,
                    db,
                    attachments=payload.attachments,
                    assistant_response=final_response,
                )
                # Publish title to SSE so frontend can update immediately
                if pubsub and chat and chat.title:
                    await pubsub.publish_agent_event(
                        task_id,
                        {
                            "type": "chat_title",
                            "data": {
                                "chat_id": str(chat.id),
                                "title": chat.title,
                            },
                        },
                    )

            # 14. Publish a terminal status.  A runner that emitted an
            # unsuccessful ``complete`` event must not look successful to
            # clients, tickets, or automations.
            if pubsub and resume_scheduled:
                pass
            elif pubsub and completion_reason == "cancelled":
                await pubsub.publish_agent_event(
                    task_id,
                    {"type": "done", "data": {"task_id": task_id, "status": "cancelled"}},
                )
            elif pubsub and not task_succeeded:
                await _publish_error(
                    pubsub,
                    task_id,
                    terminal_error or final_response or "Agent did not complete the request.",
                )
            elif pubsub and not preview_task_id:
                await pubsub.publish_agent_event(
                    task_id,
                    {"type": "done", "data": {"task_id": task_id, "status": "completed"}},
                )

            # 14a. Gateway delivery — XADD to delivery stream if gateway-bound
            if payload.gateway_deliver and not resume_scheduled:
                try:
                    from .services.cache_service import get_redis_client
                    from .services.gateway.envelope import (
                        KIND_MESSAGE,
                        build_envelope,
                    )

                    gw_redis = await get_redis_client()
                    if gw_redis:
                        body = (final_response or "")[:8000]
                        envelope = build_envelope(
                            kind=KIND_MESSAGE,
                            config_id=payload.channel_config_id or "",
                            session_key=payload.session_key or "",
                            task_id=task_id,
                            body=body,
                            artifact_refs=[],
                            # Preserve legacy fields so any consumer rolled
                            # back to the pre-Phase-0 parser still works.
                            extra={
                                "deliver": payload.gateway_deliver,
                                "schedule_id": payload.schedule_id or "",
                                "response": body,
                            },
                        )
                        await gw_redis.xadd(
                            settings.gateway_delivery_stream,
                            envelope,
                            maxlen=settings.gateway_delivery_maxlen,
                        )
                        logger.info(
                            "[WORKER] XADD delivery for task %s (session=%s)",
                            task_id,
                            payload.session_key,
                        )
                except Exception as gw_err:
                    logger.warning("[WORKER] Gateway delivery XADD failed: %s", gw_err)

            # 14b. Enqueue webhook callback if configured
            if payload.webhook_callback_url and not resume_scheduled:
                try:
                    from .services.task_queue import get_task_queue

                    await get_task_queue().enqueue(
                        "send_webhook_callback",
                        payload.webhook_callback_url,
                        {
                            "task_id": task_id,
                            "status": completion_reason,
                            "final_response": final_response,
                            "chat_id": payload.chat_id,
                            "project_id": project_id,
                            "iterations": iterations,
                            "tool_calls_made": tool_calls_made,
                        },
                    )
                    logger.info(f"[WORKER] Enqueued webhook callback for task {task_id}")
                except Exception as wh_err:
                    logger.warning(f"[WORKER] Failed to enqueue webhook callback: {wh_err}")

            # 15. Cleanup bash session
            if context.get("_bash_session_id"):
                try:
                    from .services.shell_session_manager import get_shell_session_manager

                    shell_manager = get_shell_session_manager()
                    await shell_manager.close_session(context["_bash_session_id"])
                except Exception as cleanup_err:
                    logger.warning(f"[WORKER] Failed to cleanup bash session: {cleanup_err}")

            # Belt-and-suspenders: update task status in Redis directly
            # so get_active_agent_task sees COMPLETED even if the SSE relay
            # pod didn't call update_task_status.
            terminal_task_status = (
                "completed"
                if task_succeeded
                else "cancelled"
                if completion_reason == "cancelled"
                else "failed"
            )
            # A preview job still owns the terminal outcome after a successful
            # mutation. Keeping this task RUNNING prevents a failed readiness
            # check from being overwritten by the model completion.
            if not preview_task_id and not resume_scheduled:
                await _update_task_status_redis(
                    task_id,
                    terminal_task_status,
                    error=None if task_succeeded else terminal_error or final_response,
                )

            # Mark the AgentTask ticket as completed / cancelled.
            if claimed_ticket_id is not None and not resume_scheduled:
                terminal = "completed" if task_succeeded else terminal_task_status
                with contextlib.suppress(Exception):
                    from .services.agent_tickets import finish_ticket

                    await finish_ticket(db, ticket_id=claimed_ticket_id, status=terminal)

            # Close the AutomationRun row when the dispatcher handed us
            # this task. Until this fix, the dispatcher flipped status to
            # ``succeeded`` the moment it enqueued — so a real worker
            # crash after dispatch would still leave the run looking
            # successful. The WHERE-clause guard inside _finalize lets a
            # racing user-cancellation or contract-breach pause win.
            if auto_run_id is not None and not preview_task_id and not resume_scheduled:
                final_status = "succeeded" if task_succeeded else terminal_task_status
                await _finalize_automation_run(
                    auto_run_id,
                    status=final_status,
                    raw_output={
                        "task_id": task_id,
                        "chat_id": str(chat.id) if chat else payload.chat_id,
                        "message_id": str(message_id) if message_id else None,
                        "iterations": iterations,
                        "tool_calls": tool_calls_made,
                        "events": event_count,
                        "completion_reason": completion_reason,
                        "session_id": session_id,
                    },
                )

            logger.info(f"[WORKER] Task {task_id} complete, saved to database")

        except Exception as e:
            import traceback

            from .services.agent_approval import ApprovalRequired

            # Any persistence failure may have left the transaction aborted.
            # Restore it before ticket/message/chat cleanup so every task ends
            # in a truthful terminal state and releases its lock.
            with contextlib.suppress(Exception):
                await db.rollback()

            if isinstance(e, ApprovalRequired):
                # Tool hit an approval gate: ticket is already flipped to
                # "awaiting_approval" by check_tool_allowed(); we only need to
                # publish a paused event so the frontend / tray knows.
                logger.info(
                    "[WORKER] Task %s paused awaiting approval for tool %r",
                    task_id,
                    e.tool_name,
                )
                with contextlib.suppress(Exception):
                    if pubsub:
                        await pubsub.publish_agent_event(
                            task_id,
                            {
                                "type": "awaiting_approval",
                                "data": {
                                    "tool_name": e.tool_name,
                                    "ticket_id": str(e.ticket_id),
                                    "task_id": task_id,
                                },
                            },
                        )
                # Hand the AutomationRun off to the approval queue. Status
                # flips from ``running`` to ``waiting_approval`` so
                # heartbeat_sweep (which only reaps ``running``) leaves it
                # alone; the existing approval-resume path can flip it
                # back to ``running`` when the operator unblocks it.
                if auto_run_id is not None:
                    await _finalize_automation_run(
                        auto_run_id,
                        status="waiting_approval",
                        raw_output={
                            "task_id": task_id,
                            "approval_required": {
                                "tool_name": e.tool_name,
                                "ticket_id": (
                                    str(e.ticket_id) if getattr(e, "ticket_id", None) else None
                                ),
                            },
                        },
                    )
                # Do NOT mark the ticket failed — it stays "awaiting_approval"
                # until the operator approves and re-queues it.
                return

            error_traceback = traceback.format_exc()
            logger.error(f"[WORKER] Agent task {task_id} failed: {e}")
            logger.error(f"[WORKER] Traceback:\n{error_traceback}")

            # Publish error event
            await _publish_error(pubsub, task_id, str(e))

            # Update task status to FAILED in Redis
            await _update_task_status_redis(task_id, "failed", error=str(e))

            # Mark the AgentTask ticket as failed
            if claimed_ticket_id is not None:
                with contextlib.suppress(Exception):
                    from .services.agent_tickets import finish_ticket

                    await finish_ticket(db, ticket_id=claimed_ticket_id, status="failed")

            # Close the AutomationRun row as failed. Same WHERE-guard as the
            # success path — a user cancellation or contract-breach pause
            # that landed first wins.
            if auto_run_id is not None:
                await _finalize_automation_run(
                    auto_run_id,
                    status="failed",
                    raw_output={
                        "task_id": task_id,
                        "error": str(e)[:1000],
                        "error_type": type(e).__name__,
                    },
                )

            # Finalize stale in_progress placeholder message and reset chat status
            try:
                # Finalize the placeholder Message so it doesn't show thinking dots
                if message_id is not None:
                    msg_result = await db.execute(select(Message).where(Message.id == message_id))
                    stale_msg = msg_result.scalar_one_or_none()
                    if (
                        stale_msg
                        and (stale_msg.message_metadata or {}).get("completion_reason")
                        == "in_progress"
                    ):
                        stale_msg.content = f"Agent task failed: {str(e)[:200]}"
                        stale_msg.message_metadata = {
                            **(stale_msg.message_metadata or {}),
                            "completion_reason": "error",
                            "error": str(e)[:500],
                        }
                        db.add(stale_msg)

                # Mark chat as active (not running) on error — skip if our
                # lock was stolen so we don't flip state owned by a new task.
                if not lock_stolen:
                    chat_result = await db.execute(
                        select(Chat).where(Chat.id == UUID(payload.chat_id))
                    )
                    chat = chat_result.scalar_one_or_none()
                    if chat and chat.status == "running":
                        chat.status = "active"

                await db.commit()
            except Exception as db_err:
                logger.warning(
                    f"[WORKER] Failed to finalize stale message / reset chat status: {db_err}"
                )

        finally:
            # Always release chat lock, concurrency slot, and heartbeat
            if heartbeat_task:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
            # Cancel the AutomationRun heartbeat too — its loop only
            # tickles a row we no longer own.
            if auto_run_hb_task is not None:
                auto_run_hb_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await auto_run_hb_task
            if lock_acquired and pubsub:
                await pubsub.release_chat_lock(payload.chat_id, task_id)
                logger.debug(f"[WORKER] Released chat lock for {payload.chat_id}")
            # Free the concurrency slot reserved at enqueue time.
            with contextlib.suppress(Exception):
                from .services.concurrency_limits import release_slot

                await release_slot(
                    user_id=payload.user_id,
                    project_id=payload.project_id or None,
                    task_id=task_id,
                )


async def dispatch_automation_task(
    ctx: dict,
    automation_id_str: str,
    event_id_str: str,
    worker_id: str,
) -> dict:
    """ARQ wrapper around ``services.automations.dispatcher.dispatch_automation``.

    Idempotent — safe to enqueue multiple times for the same
    ``(automation_id, event_id)`` pair. The dispatcher's internal status
    branch table refuses to re-execute terminal/in-flight runs, so duplicate
    deliveries from ARQ retries collapse to no-ops.

    The dispatcher manages its own commits/rollbacks (Phase A through D each
    end with ``await db.commit()``); we only own the session lifecycle and a
    last-resort rollback if the dispatcher itself raises before its final
    commit. Re-raise on failure so ARQ's ``max_tries``/backoff applies.
    """
    from .database import AsyncSessionLocal
    from .services.automations.dispatcher import dispatch_automation

    async with AsyncSessionLocal() as db:
        try:
            result = await dispatch_automation(
                db,
                automation_id=UUID(automation_id_str),
                event_id=UUID(event_id_str),
                worker_id=worker_id,
            )
        except Exception:
            logger.exception(
                "[WORKER] dispatch_automation_task failed automation=%s event=%s",
                automation_id_str,
                event_id_str,
            )
            # Best-effort rollback in case the dispatcher raised mid-transaction
            # before its own commit. Suppressed because the session may already
            # be in an aborted/closed state.
            with contextlib.suppress(Exception):
                await db.rollback()
            raise

        status_value = (
            result.status.value if hasattr(result.status, "value") else str(result.status)
        )
        return {
            "run_id": str(result.run_id),
            "status": status_value,
            "run_status": result.run_status,
            "reason": result.reason,
        }


async def resume_automation_run(ctx: dict, run_id_str: str) -> dict:
    """ARQ task: hydrate a paused AutomationRun's checkpoint and continue.

    Called from the approval-response endpoint when the user picks an
    ``allow_*`` option (or ``restart_from_last_checkpoint``). We:

    1. Load the serialized checkpoint from ``automation_runs.checkpoint``.
    2. Branch on its :attr:`RunCheckpoint.resume_strategy`:
       * ``redispatch`` — re-call the action dispatcher with the saved input
         (idempotent for ``app.invoke`` / ``gateway.send``).
       * ``agent_continue`` — re-enqueue ``execute_agent_task`` with the
         saved message history.
       * ``restart_from_checkpoint`` — re-enqueue with a clean message
         history (the in-flight non-serializable tool was cancelled at
         pause time).

    Failure modes are bounded:

    * No checkpoint row → log + return ``{"status": "no_checkpoint"}``. Not
      raised so ARQ doesn't burn retries on a row a sweep already cleaned.
    * Dispatcher errors propagate as exceptions so ARQ's max_tries +
      backoff kick in.

    Mirrors the lifecycle of :func:`dispatch_automation_task` — owns the
    DB session, defers commits to :func:`resume_run`, last-resort rollback
    on unexpected exceptions.
    """
    from .database import AsyncSessionLocal
    from .services.automations.checkpoint import hydrate_checkpoint
    from .services.automations.dispatcher import resume_run

    async with AsyncSessionLocal() as db:
        try:
            checkpoint = await hydrate_checkpoint(db, run_id=UUID(run_id_str))
            if checkpoint is None:
                logger.warning(
                    "[WORKER] resume_automation_run: no checkpoint for run=%s",
                    run_id_str,
                )
                return {"status": "no_checkpoint", "run_id": run_id_str}

            result = await resume_run(db, checkpoint=checkpoint)
            await db.commit()
        except Exception:
            logger.exception("[WORKER] resume_automation_run failed run=%s", run_id_str)
            with contextlib.suppress(Exception):
                await db.rollback()
            raise

        status_value = (
            result.status.value if hasattr(result.status, "value") else str(result.status)
        )
        return {
            "run_id": str(result.run_id),
            "status": status_value,
            "run_status": result.run_status,
            "reason": result.reason,
        }


async def send_webhook_callback(ctx: dict, url: str, payload: dict):
    """
    Send webhook callback to external client.

    ARQ handles retries (max_tries=5, exponential backoff).
    """
    from urllib.parse import urlparse

    import httpx

    parsed_url = urlparse(url)
    logger.info(
        f"[WEBHOOK] Sending callback to {parsed_url.scheme}://{parsed_url.hostname}{parsed_url.path}"
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()

    logger.info(f"[WEBHOOK] Callback sent successfully: {response.status_code}")


async def _update_task_status_redis(task_id: str, status: str, error: str | None = None):
    """Directly update task status in Redis from the worker process.

    The worker doesn't share TaskManager state with the API pod, so we write
    the status key directly.  Belt-and-suspenders for when the SSE relay pod
    doesn't mark the task as completed.
    """
    try:
        from .services.cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        import json
        from datetime import datetime

        task_key = f"tesslate:task:{task_id}"
        raw = await redis.get(task_key)
        if not raw:
            return

        data = json.loads(raw)
        data["status"] = status
        data["completed_at"] = datetime.now(UTC).isoformat()
        if error:
            data["error"] = error

        await redis.setex(task_key, 86400, json.dumps(data))
        logger.info(f"[WORKER] Updated task {task_id} status to {status} in Redis")
    except Exception as e:
        logger.debug(f"[WORKER] Failed to update task status in Redis (non-blocking): {e}")


async def _update_task_metadata_redis(task_id: str, updates: dict[str, object]) -> None:
    """Merge task metadata from a worker-owned lifecycle transition."""
    try:
        from .services.cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return
        task_key = f"tesslate:task:{task_id}"
        raw = await redis.get(task_key)
        if not raw:
            return
        import json

        data = json.loads(raw)
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        metadata.update(updates)
        data["metadata"] = metadata
        await redis.setex(task_key, 86400, json.dumps(data))
    except Exception as exc:
        logger.debug("[WORKER] Failed to update task metadata for %s: %s", task_id, exc)


async def _publish_error(pubsub, task_id: str, message: str):
    """Publish an error event to Redis."""
    if pubsub:
        await pubsub.publish_agent_event(
            task_id,
            {"type": "error", "data": {"message": message}},
        )
        # Also publish done so the API pod stops listening
        await pubsub.publish_agent_event(
            task_id,
            {
                "type": "done",
                "data": {"task_id": task_id, "status": "failed", "error": message},
            },
        )


async def refresh_templates(ctx: dict):
    """Check for outdated templates and trigger rebuilds.

    Compares git HEAD SHA of each base's repo with the SHA stored in
    the TemplateBuild record. If different, triggers a rebuild.
    """
    from sqlalchemy import select

    from .config import get_settings

    settings = get_settings()
    if not settings.template_build_enabled:
        return

    from .database import AsyncSessionLocal
    from .models import MarketplaceBase, TemplateBuild
    from .services.template_builder import TemplateBuilderService

    async with AsyncSessionLocal() as db:
        # Find bases with ready templates that have a git repo
        result = await db.execute(
            select(MarketplaceBase).where(
                MarketplaceBase.template_slug.isnot(None),
                MarketplaceBase.git_repo_url.isnot(None),
            )
        )
        bases = result.scalars().all()

        if not bases:
            return

        builder = TemplateBuilderService()
        rebuilt = 0
        for base in bases:
            try:
                # Get latest remote SHA via git ls-remote
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "ls-remote",
                    base.git_repo_url,
                    "HEAD",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode != 0:
                    continue
                remote_sha = stdout.decode().split()[0][:40]

                # Get latest successful build SHA
                latest_build = await db.scalar(
                    select(TemplateBuild)
                    .where(
                        TemplateBuild.base_slug == base.slug,
                        TemplateBuild.status == "ready",
                    )
                    .order_by(TemplateBuild.completed_at.desc())
                    .limit(1)
                )

                if latest_build and latest_build.git_commit_sha == remote_sha:
                    continue  # Template is up to date

                logger.info(
                    "[WORKER] Template %s outdated (remote=%s, build=%s), rebuilding...",
                    base.slug,
                    remote_sha[:8],
                    (latest_build.git_commit_sha or "none")[:8] if latest_build else "none",
                )
                await builder.build_template(base, db)
                rebuilt += 1
            except Exception:
                logger.exception("[WORKER] Failed to refresh template for %s", base.slug)

        if rebuilt:
            logger.info("[WORKER] Refreshed %d templates", rebuilt)


async def reap_idle_session_keys(ctx: dict) -> dict:
    """Periodic task: sweep idle session-tier LiteLLM keys past their TTL.

    For each idle key, transition active -> settling (revokes at LiteLLM),
    then settling -> settled. Per-key work is best-effort; failures are
    logged and the sweep continues.
    """
    from .database import AsyncSessionLocal
    from .services import litellm_keys
    from .services.litellm_service import litellm_service

    async with AsyncSessionLocal() as db:
        try:
            key_ids = await litellm_keys.select_idle_session_keys(db, limit=200)
        except Exception:
            logger.exception("reap_idle_session_keys: select failed")
            return {"swept": 0}

        swept = 0
        for key_id in key_ids:
            try:
                await litellm_keys.begin_settlement(
                    db, delegate=litellm_service, key_id=key_id, reason="idle_reap"
                )
                await litellm_keys.finalize_settlement(db, key_id=key_id)
                await db.commit()
                swept += 1
            except Exception:
                await db.rollback()
                logger.exception("reap_idle_session_keys: key %s failed", key_id)

        if swept:
            logger.info("[WORKER] reaped %d idle session keys", swept)
        return {"swept": swept}


async def settle_invocation_key(ctx: dict, key_id: str) -> dict:
    """Enqueue-able: settle a completed invocation key (headless run).

    Called by the billing dispatcher when an invocation completes. The
    dispatcher is responsible for wallet reserve/settle — this function
    owns only the ledger transition and the LiteLLM revoke.
    """
    from .database import AsyncSessionLocal
    from .services import litellm_keys
    from .services.litellm_service import litellm_service

    async with AsyncSessionLocal() as db:
        try:
            await litellm_keys.begin_settlement(
                db, delegate=litellm_service, key_id=key_id, reason="complete"
            )
            await litellm_keys.finalize_settlement(db, key_id=key_id)
            await db.commit()
            return {"key_id": key_id, "state": "settled"}
        except Exception:
            await db.rollback()
            logger.exception("settle_invocation_key: %s failed", key_id)
            raise


async def cascade_revoke_children(ctx: dict, parent_key_id: str) -> dict:
    """Enqueue-able: BFS revoke all active descendants of a key.

    Fired when a parent transitions out of active (explicit revoke, failed
    state, etc.). Returns the list of revoked key_ids.
    """
    from .database import AsyncSessionLocal
    from .services import litellm_keys
    from .services.litellm_service import litellm_service

    async with AsyncSessionLocal() as db:
        try:
            revoked = await litellm_keys.cascade_revoke(
                db, delegate=litellm_service, parent_key_id=parent_key_id
            )
            await db.commit()
            return {"parent_key_id": parent_key_id, "revoked": revoked}
        except Exception:
            await db.rollback()
            logger.exception("cascade_revoke_children: %s failed", parent_key_id)
            raise


async def refill_warm_pools_cron(ctx: dict) -> dict:
    """Every 60s: refill warm pools for all installed AppInstances whose
    manifest declares any hosted agent with `warm_pool_size > 0`.

    The refill is idempotent — it only mints the shortfall per agent.
    """
    from sqlalchemy import select

    from .database import AsyncSessionLocal
    from .models import AppInstance
    from .services.apps import warm_pool
    from .services.litellm_service import litellm_service

    async with AsyncSessionLocal() as db:
        try:
            instance_ids = (
                (await db.execute(select(AppInstance.id).where(AppInstance.state == "installed")))
                .scalars()
                .all()
            )
        except Exception:
            logger.exception("refill_warm_pools_cron: scan failed")
            return {"scanned": 0, "refilled": 0}

    refilled = 0
    for instance_id in instance_ids:
        async with AsyncSessionLocal() as db:
            try:
                result = await warm_pool.refill_warm_pool(
                    db, app_instance_id=instance_id, delegate=litellm_service
                )
                await db.commit()
                if result.get("minted", 0) > 0:
                    refilled += 1
            except Exception:
                await db.rollback()
                logger.exception("refill_warm_pools_cron: instance %s failed", instance_id)
    return {"scanned": len(instance_ids), "refilled": refilled}


async def refill_warm_pool_task(ctx: dict, app_instance_id: str) -> dict:
    """Enqueue-able per-instance warm-pool refill (e.g., right after install)."""
    from .database import AsyncSessionLocal
    from .services.apps import warm_pool
    from .services.litellm_service import litellm_service

    async with AsyncSessionLocal() as db:
        try:
            result = await warm_pool.refill_warm_pool(
                db,
                app_instance_id=UUID(app_instance_id),
                delegate=litellm_service,
            )
            await db.commit()
            return result
        except Exception:
            await db.rollback()
            logger.exception("refill_warm_pool_task: %s failed", app_instance_id)
            raise


async def drain_warm_pool_task(ctx: dict, app_instance_id: str) -> dict:
    """Enqueue-able warm-pool drain on uninstall/yank."""
    from .database import AsyncSessionLocal
    from .services.apps import warm_pool
    from .services.litellm_service import litellm_service

    async with AsyncSessionLocal() as db:
        try:
            count = await warm_pool.drain_warm_pool(
                db,
                app_instance_id=UUID(app_instance_id),
                delegate=litellm_service,
            )
            await db.commit()
            return {"app_instance_id": app_instance_id, "drained": count}
        except Exception:
            await db.rollback()
            logger.exception("drain_warm_pool_task: %s failed", app_instance_id)
            raise


async def run_stage1_scan_task(ctx: dict, submission_id: str) -> dict:
    """Wave 7: run the Stage1 structural scan on a submission."""
    from uuid import UUID as _UUID

    from .database import AsyncSessionLocal
    from .services.apps import stage1_scanner

    async with AsyncSessionLocal() as db:
        try:
            out = await stage1_scanner.run_stage1_scan(db, submission_id=_UUID(submission_id))
            await db.commit()
            return out
        except Exception:
            await db.rollback()
            logger.exception("run_stage1_scan_task: %s failed", submission_id)
            raise


async def run_stage2_eval_task(ctx: dict, submission_id: str) -> dict:
    """Wave 7: run the Stage2 sandbox eval on a submission."""
    from uuid import UUID as _UUID

    from .database import AsyncSessionLocal
    from .services.apps import stage2_sandbox

    async with AsyncSessionLocal() as db:
        try:
            out = await stage2_sandbox.run_stage2_eval(db, submission_id=_UUID(submission_id))
            await db.commit()
            return out
        except Exception:
            await db.rollback()
            logger.exception("run_stage2_eval_task: %s failed", submission_id)
            raise


async def run_monitoring_sweep_task(ctx: dict, app_version_id: str) -> dict:
    """Wave 7: run a single monitoring canary sweep for an approved AppVersion."""
    from uuid import UUID as _UUID

    from .database import AsyncSessionLocal
    from .services.apps import monitoring_sweep

    async with AsyncSessionLocal() as db:
        try:
            out = await monitoring_sweep.run_monitoring_sweep(
                db, app_version_id=_UUID(app_version_id)
            )
            await db.commit()
            return out
        except Exception:
            await db.rollback()
            logger.exception("run_monitoring_sweep_task: %s failed", app_version_id)
            raise


async def process_schedule_triggers_cron(ctx: dict) -> dict:
    """Wave 7 cron: drain pending schedule_trigger_events."""
    from .services.apps import schedule_triggers

    try:
        return await schedule_triggers.process_trigger_events_batch(ctx)
    except Exception:
        logger.exception("process_schedule_triggers_cron failed")
        return {"processed": 0, "failed": 0, "skipped": 0, "error": True}


async def reap_orphaned_install_attempts_cron(ctx: dict) -> dict:
    """Wave 9 A2 cron: free Hub volumes orphaned by crashed installs.

    Cheap when idle (single indexed scan on ``app_install_attempts`` where
    ``state='hub_created'``). 60s cadence; grace window 15 min before an
    attempt is eligible for reaping.
    """
    from .config import get_settings
    from .services.apps.install_reaper import reap_orphaned_install_attempts
    from .services.hub_client import HubClient

    hub = HubClient(get_settings().volume_hub_address)
    try:
        return await reap_orphaned_install_attempts(hub)
    except Exception:
        logger.exception("reap_orphaned_install_attempts_cron failed")
        return {"scanned": 0, "reaped": 0, "failed": 0, "error": True}
    finally:
        close = getattr(hub, "close", None)
        if callable(close):
            with contextlib.suppress(Exception):
                await close()


async def db_event_dispatcher_cron(ctx: dict) -> dict:
    """Wave 9 D1 cron: drain tesslate:db_events:* streams into ScheduleTriggerEvent.

    No-op while no AgentSchedule has trigger_kind='db_event'. Wave 10 lights
    consumers up; the rails ship now so schema/topology are stable.
    """
    from .services.apps.db_event_dispatcher import db_event_dispatcher

    try:
        return await db_event_dispatcher(ctx)
    except Exception:
        logger.exception("db_event_dispatcher_cron failed")
        return {"streams": 0, "events": 0, "inserted": 0, "error": True}


async def startup(ctx: dict):
    """Worker startup hook — initialize logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("[WORKER] ARQ worker started")

    # Publish before other startup work so incoming chat requests can tell
    # that this worker is available even while optional warm-up is running.
    await _write_worker_heartbeat()
    ctx["worker_heartbeat_task"] = asyncio.create_task(_worker_heartbeat_loop())

    # Load prompt-caching eligible models from LiteLLM
    from .services.prompt_caching import refresh_eligible_models

    await refresh_eligible_models()


async def shutdown(ctx: dict):
    """Worker shutdown hook — cleanup."""
    heartbeat_task = ctx.get("worker_heartbeat_task")
    if heartbeat_task is not None:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
    logger.info("[WORKER] ARQ worker shutting down")


def _get_redis_settings() -> RedisSettings:
    """Build ARQ RedisSettings from REDIS_URL environment variable."""
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    # Parse redis://host:port/db format
    from urllib.parse import urlparse

    parsed = urlparse(redis_url)
    return RedisSettings(
        host=parsed.hostname or "redis",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
        password=parsed.password,
    )


def _get_worker_settings():
    """Load worker tuning values from app config (env-overridable)."""
    from .config import get_settings

    s = get_settings()
    return s.worker_max_jobs, s.worker_job_timeout, s.worker_max_tries


def _build_cron_jobs():
    """Build list of ARQ cron jobs from settings."""
    from arq.cron import cron

    from .config import get_settings

    s = get_settings()
    jobs = []

    if s.template_build_enabled and s.template_refresh_interval_hours > 0:
        # Run template refresh at the configured interval.
        # ARQ cron uses hour= to set which hours the job runs.
        # For a 24h interval, run at midnight; for shorter intervals,
        # build a set of hours to match the cadence.
        interval_h = s.template_refresh_interval_hours
        run_hours = set(range(0, 24, interval_h)) if interval_h < 24 else {0}
        jobs.append(
            cron(
                refresh_templates,
                hour=run_hours,
                minute={0},
                timeout=s.template_build_timeout + 120,  # extra grace for multiple builds
                unique=True,
                run_at_startup=False,
            )
        )

    # Tesslate Apps: idle session-key reaper. Runs every minute; short budget.
    # The reaper is cheap when idle (single SELECT with partial index), so
    # the 60s cadence is safe and keeps session TTL enforcement tight.
    jobs.append(
        cron(
            reap_idle_session_keys,
            minute=set(range(0, 60)),  # every minute
            timeout=120,
            unique=True,
            run_at_startup=False,
        )
    )

    # Tesslate Apps: spend settlement sweep. Every minute, bounded batch.
    jobs.append(
        cron(
            settle_spend_batch_cron,
            minute=set(range(0, 60)),
            timeout=180,
            unique=True,
            run_at_startup=False,
        )
    )

    # Tesslate Apps (Wave 6): hosted-agent warm-pool refill. 60s cadence.
    jobs.append(
        cron(
            refill_warm_pools_cron,
            minute=set(range(0, 60)),
            timeout=120,
            unique=True,
            run_at_startup=False,
        )
    )

    # Tesslate Apps (Wave 7): schedule trigger events drain. 60s cadence.
    jobs.append(
        cron(
            process_schedule_triggers_cron,
            minute=set(range(0, 60)),
            timeout=120,
            unique=True,
            run_at_startup=False,
        )
    )

    # Tesslate Apps (Wave 9 A2): orphaned install-attempt reaper. 60s cadence.
    # Grace window is 15 min inside the reaper; keep cron cheap and frequent.
    jobs.append(
        cron(
            reap_orphaned_install_attempts_cron,
            minute=set(range(0, 60)),
            timeout=120,
            unique=True,
            run_at_startup=False,
        )
    )

    # Tesslate Apps (Wave 9 D1): DB-event stream drain → ScheduleTriggerEvent.
    # 5-second cadence — DB events should feel near-real-time to Apps. The
    # cron is cheap when no streams exist (single SCAN, returns immediately).
    jobs.append(
        cron(
            db_event_dispatcher_cron,
            second=set(range(0, 60, 5)),
            timeout=60,
            unique=True,
            run_at_startup=False,
        )
    )

    # Federated marketplace (Wave 3): periodic sync against every active
    # MarketplaceSource. Drains /v1/changes per source every 5 minutes and
    # applies upsert/delete/deactivate/yank/version_remove/pricing_change
    # tombstones. Failures per source are logged but never raised.
    jobs.append(
        cron(
            marketplace_sync_periodic_cron,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            timeout=300,
            unique=True,
            run_at_startup=False,
        )
    )

    # Federated marketplace (Wave 3): fast yank propagation. Polls each
    # source's /v1/yanks every minute so a critical yank reaches the
    # orchestrator's cache within ~1 minute of being published upstream.
    jobs.append(
        cron(
            marketplace_yanks_fast_cron,
            minute=set(range(0, 60)),
            timeout=120,
            unique=True,
            run_at_startup=False,
        )
    )

    return jobs


_max_jobs, _job_timeout, _max_tries = _get_worker_settings()


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [
        execute_agent_task,
        start_project_preview_task,
        dispatch_automation_task,
        resume_automation_run,
        send_webhook_callback,
        reap_idle_session_keys,
        settle_invocation_key,
        cascade_revoke_children,
        settle_spend_batch_cron,
        refill_warm_pools_cron,
        refill_warm_pool_task,
        drain_warm_pool_task,
        run_stage1_scan_task,
        run_stage2_eval_task,
        run_monitoring_sweep_task,
        process_schedule_triggers_cron,
        db_event_dispatcher_cron,
        reap_orphaned_install_attempts_cron,
        invoke_app_instance_task,
        marketplace_sync_periodic_cron,
        marketplace_yanks_fast_cron,
    ]
    cron_jobs = _build_cron_jobs()
    redis_settings = _get_redis_settings()
    max_jobs = _max_jobs
    job_timeout = _job_timeout
    on_startup = startup
    on_shutdown = shutdown
    max_tries = _max_tries

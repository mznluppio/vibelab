"""Adapter between the orchestrator and the ``tesslate-agent`` package.

Responsibilities:
    1. Re-export the submodule's ``TesslateAgent`` + ``AbstractAgent`` with
       stable local names (``TesslateAgentAdapter.inner`` preserves the raw
       submodule instance for callers that need direct access).
    2. ``run_turn()`` drives a single request/response cycle against the
       submodule runner, yielding every event. Callers pass an optional
       ``event_sink`` to handle per-event side-effects (e.g. ``AgentStep``
       persistence) without coupling the submodule to orchestrator internals.
    3. ``AgentAdapterContext`` is the neutral invocation envelope shared by
       routers and the worker.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from tesslate_agent.agent.base import AbstractAgent
from tesslate_agent.agent.tesslate_agent import TesslateAgent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentAdapterContext:
    """Minimal invocation context the orchestrator hands to the adapter."""

    project_id: str
    user_id: str
    goal_ancestry: list[str] | None = None
    extra: dict[str, Any] | None = None


class TesslateAgentAdapter:
    """Thin wrapper around ``TesslateAgent`` for orchestrator-side use.

    Construction mirrors ``TesslateAgent.__init__``. The wrapper exists so
    orchestrator call sites depend on a local class name; once trajectory
    persistence and tool-registry plumbing are wired, only this module
    changes.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._inner: AbstractAgent = TesslateAgent(*args, **kwargs)

    @property
    def inner(self) -> AbstractAgent:
        return self._inner

    @property
    def tools(self) -> Any:
        return self._inner.tools

    async def run_turn(
        self,
        user_request: str,
        adapter_context: AgentAdapterContext,
        *,
        event_sink: EventSink | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Drive a single agent turn, yielding every event.

        Yields each event emitted by the submodule runner so callers can
        interleave cancellation checks, pubsub publishing, or other
        per-event work. If ``event_sink`` is provided it is awaited on
        each event before yielding — this is how the orchestrator persists
        trajectory events as ``AgentStep`` rows without coupling the
        submodule to that plumbing.
        """
        # The worker reads mutation state (``project_changed`` and preview
        # metadata) from ``adapter_context.extra`` after this turn.  Tools
        # mutate their execution context in place, so forwarding a merged copy
        # would silently discard that state and prevent the preview lifecycle
        # from being enqueued.  Reuse the worker-owned dict when present.
        ctx: dict[str, Any] = (
            adapter_context.extra if adapter_context.extra is not None else {}
        )
        ctx.setdefault("project_id", adapter_context.project_id)
        ctx.setdefault("user_id", adapter_context.user_id)
        if adapter_context.goal_ancestry:
            ctx.setdefault("goal_ancestry", adapter_context.goal_ancestry)
        async for event in _iter_events(self._inner, user_request, ctx):
            if event_sink is not None:
                try:
                    await event_sink(event)
                except Exception as exc:
                    # Progressive persistence is part of the execution
                    # contract, not optional telemetry.  Continuing after a
                    # fatal sink failure can spend credits and modify files
                    # while the user no longer has a recoverable task record.
                    logger.exception("event_sink failed; stopping agent turn: %s", exc)
                    raise
            yield event


async def _iter_events(
    agent: AbstractAgent, user_request: str, context: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """Normalise ``agent.run()`` into a plain async-iterator of event dicts.

    ``TesslateAgent.run`` returns an async generator; some older code paths
    return a coroutine that awaits to an async generator. Tolerate both.
    """
    result = agent.run(user_request, context)
    if hasattr(result, "__aiter__"):
        async for event in result:
            yield event
        return
    awaited = await result  # type: ignore[misc]
    async for event in awaited:
        yield event


# ---------------------------------------------------------------------------
# Event sink type
# ---------------------------------------------------------------------------

EventSink = Any  # async callable taking a single event dict


__all__ = [
    "AgentAdapterContext",
    "TesslateAgentAdapter",
]

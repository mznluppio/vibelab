"""Authorization rules for mutations of marketplace agent definitions.

An installed agent grants a user permission to use it, not to alter the
shared catalog row. Keep this decision in one place because tools, skills,
MCP assignments, and the main editor all mutate the same definition.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MarketplaceAgent, MarketplaceSource, User
from .marketplace_source_cache import load_source


def is_agent_owner(agent: MarketplaceAgent, user: User) -> bool:
    return user.id in {agent.created_by_user_id, agent.forked_by_user_id}


def is_protected_agent(agent: MarketplaceAgent, source: MarketplaceSource | None) -> bool:
    from .default_agent import is_system_default

    return bool(
        is_system_default(agent.id)
        or agent.is_system
        or agent.is_builtin
        or (source and source.trust_level == "official")
    )


def can_edit_agent(
    agent: MarketplaceAgent,
    source: MarketplaceSource | None,
    user: User,
) -> bool:
    """Whether the standard Library surface may expose agent editing.

    The Library and its mutation endpoint must agree: platform administrators
    are allowed to maintain protected catalog rows, while personal agents stay
    editable only by their creator.  This keeps the UI from hiding an action
    that the API will accept, without granting administrators access to other
    users' private agents.
    """
    if is_protected_agent(agent, source):
        return bool(getattr(user, "is_superuser", False))
    return is_agent_owner(agent, user)


async def require_agent_mutation_access(
    db: AsyncSession,
    agent: MarketplaceAgent,
    current_user: User,
) -> None:
    """Require ownership, or a global administrator for protected rows."""
    source = await load_source(db, agent.source_id)
    if is_protected_agent(agent, source):
        if getattr(current_user, "is_superuser", False):
            return
        raise HTTPException(
            status_code=403,
            detail="Official and system agents are read-only. Duplicate an eligible agent to customize it.",
        )
    if is_agent_owner(agent, current_user):
        return
    raise HTTPException(status_code=403, detail="Only the agent creator can change this agent.")

"""
Credit deduction service for real-time AI usage billing.

Handles pre-request credit checks, post-request deduction with
priority ordering (daily → bundled → bonus → purchased), and
UsageLog creation.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from .model_pricing import calculate_cost_cents

logger = logging.getLogger(__name__)


def _get_byok_prefixes() -> tuple[str, ...]:
    """Get BYOK provider prefixes from the canonical provider registry.

    Derives prefixes from BUILTIN_PROVIDERS in agent/models.py — the single
    source of truth for all supported providers. Adding a new provider there
    automatically makes it recognized as BYOK here.
    """
    try:
        from .model_adapters import get_byok_provider_prefixes

        return get_byok_provider_prefixes()
    except Exception:
        # Fallback only during early startup or import errors
        logger.debug("Could not load provider registry, using fallback BYOK prefixes")
        return (
            "openrouter/",
            "openai/",
            "groq/",
            "anthropic/",
            "together/",
            "deepseek/",
            "fireworks/",
            "nano-gpt/",
        )


def is_byok_model(model_name: str) -> bool:
    """Return True if the model uses the user's own API key (no credit charge)."""
    return any(model_name.startswith(p) for p in _get_byok_prefixes())


def _allocation_cycle_start(team) -> datetime:
    """Use the team's explicit cycle where available, with a safe legacy fallback."""
    if team.credit_cycle_started_at:
        return team.credit_cycle_started_at
    now = datetime.now(UTC)
    return datetime(now.year, now.month, 1, tzinfo=UTC)


async def _member_allocation_remaining(
    db: AsyncSession, *, team, user_id, lock_membership: bool = False
) -> int | None:
    """Return an individual allowance's remaining amount, or ``None`` in shared mode."""
    from ..models import UsageLog
    from ..models_team import TeamMembership

    if team.credit_allocation_mode != "individual":
        return None

    membership_query = select(TeamMembership).where(
        TeamMembership.team_id == team.id,
        TeamMembership.user_id == user_id,
        TeamMembership.is_active.is_(True),
    )
    if lock_membership:
        membership_query = membership_query.with_for_update()
    membership_result = await db.execute(membership_query)
    membership = membership_result.scalar_one_or_none()
    if membership is None:
        return 0
    used_result = await db.execute(
        select(func.coalesce(func.sum(UsageLog.cost_total), 0)).where(
            UsageLog.team_id == team.id,
            UsageLog.user_id == user_id,
            UsageLog.created_at >= _allocation_cycle_start(team),
        )
    )
    return max(int(membership.credit_limit or 0) - int(used_result.scalar_one() or 0), 0)


async def check_credits(
    user, model_name: str, team=None, db: AsyncSession | None = None
) -> tuple[bool, str]:
    """
    Pre-request guard: verify credits before making an LLM call.

    Credits live on the Team row (see migration 0088_drop_user_billing_columns
    which removed the per-user balance columns). Resolution order:

      1. Explicit ``team`` argument (preferred — caller already loaded it).
      2. ``user.default_team_id`` looked up via ``db`` (fallback so single-team
         users don't have to be re-plumbed at every call site).
      3. No team resolvable → permissive (return True). Users without any
         team have no credit ledger to evaluate, and silently failing-open
         here is safer than 500-ing the request path.

    Returns:
        (True, "") if user can proceed.
        (False, error_message) if insufficient credits.
    """
    if is_byok_model(model_name):
        return True, ""

    # Lazy-resolve team from user.default_team_id when caller didn't pass one.
    if team is None and db is not None and user is not None:
        team_id = getattr(user, "default_team_id", None)
        if team_id is not None:
            from ..models_team import Team

            result = await db.execute(select(Team).where(Team.id == team_id))
            team = result.scalar_one_or_none()

    # No team = no credit ledger to evaluate. Don't block the request.
    if team is None:
        return True, ""

    if team.total_credits <= 0:
        return False, (
            "You have no credits remaining. "
            "Please purchase credits or upgrade your plan to continue using AI features."
        )

    if team.credit_allocation_mode == "individual" and db is not None:
        remaining = await _member_allocation_remaining(
            db,
            team=team,
            user_id=user.id,
        )
        if remaining <= 0:
            return False, (
                "Your individual allocation has been reached. "
                "Please contact a team administrator for more capacity."
            )

    return True, ""


async def deduct_credits(
    db: AsyncSession,
    user_id: UUID,
    model_name: str,
    tokens_in: int,
    tokens_out: int,
    agent_id: UUID | None = None,
    project_id: UUID | None = None,
    team_id: UUID | None = None,
    request_id: str | None = None,
) -> dict:
    """
    Deduct credits from team (or user) balance and create a UsageLog entry.

    When team_id is provided, locks and deducts from the Team row.
    Falls back to user-level deduction for backward compatibility.

    Uses SELECT FOR UPDATE to prevent race conditions on concurrent requests.
    Deduction priority: daily → bundled → signup_bonus → purchased.

    ``request_id`` makes an upstream model response idempotent.  Agent
    workers can be retried after a successful DB commit, and must not debit
    the same provider response twice.  Callers that do not have a stable
    request id keep the legacy behavior.

    Returns dict with cost_total, credits_deducted, new_balance, usage_log_id.
    """
    from ..models import UsageLog, User
    from ..models_team import Team

    byok = is_byok_model(model_name)

    # A task retry can replay the same successful provider response.  Reuse
    # its ledger entry instead of performing a second debit.  The project/chat
    # task lock prevents concurrent duplicate writers; this lookup handles the
    # durable retry path after a worker loss or post-commit interruption.
    if request_id:
        existing_result = await db.execute(
            select(UsageLog).where(UsageLog.request_id == request_id).limit(1)
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            if existing.team_id:
                balance_result = await db.execute(
                    select(Team).where(Team.id == existing.team_id)
                )
            else:
                balance_result = await db.execute(
                    select(User).where(User.id == existing.user_id)
                )
            credit_source = balance_result.scalar_one_or_none()
            new_balance = getattr(credit_source, "total_credits", 0) or 0
            member_remaining = None
            if credit_source is not None and existing.team_id:
                member_remaining = await _member_allocation_remaining(
                    db,
                    team=credit_source,
                    user_id=user_id,
                )
            return {
                "cost_total": existing.cost_total,
                "credits_deducted": 0,
                "new_balance": new_balance,
                "usage_log_id": str(existing.id),
                "is_byok": bool(existing.is_byok),
                "already_recorded": True,
                "member_remaining": member_remaining,
                "allocation_exhausted": bool(
                    member_remaining is not None
                    and member_remaining <= 0
                    and not existing.is_byok
                ),
            }

    # Calculate cost (0 for BYOK)
    if byok:
        cost_input, cost_output, cost_total = 0, 0, 0
    else:
        cost_input, cost_output, cost_total = await calculate_cost_cents(
            model_name, tokens_in, tokens_out
        )

    # Resolve team_id from project or user if not explicitly provided
    resolved_team_id = team_id
    if not resolved_team_id and project_id:
        from ..models import Project

        proj_result = await db.execute(select(Project.team_id).where(Project.id == project_id))
        resolved_team_id = proj_result.scalar_one_or_none()
    if not resolved_team_id:
        user_result = await db.execute(select(User.default_team_id).where(User.id == user_id))
        resolved_team_id = user_result.scalar_one_or_none()

    max_retries = 3
    for attempt in range(max_retries):
        try:
            credits_deducted = 0

            # Deduct from team if we have one, otherwise fall back to user
            if resolved_team_id:
                result = await db.execute(
                    select(Team).where(Team.id == resolved_team_id).with_for_update()
                )
                credit_source = result.scalar_one()
            else:
                result = await db.execute(select(User).where(User.id == user_id).with_for_update())
                credit_source = result.scalar_one()

            # Team-level locking serializes all shared credits.  Lock the
            # member row as well before querying the per-user ledger so an
            # individual allocation is evaluated against a stable cycle.
            member_remaining_before = None
            if resolved_team_id:
                member_remaining_before = await _member_allocation_remaining(
                    db,
                    team=credit_source,
                    user_id=user_id,
                    lock_membership=True,
                )

            if not byok and cost_total > 0:
                remaining = cost_total

                # 1. Daily credits first
                daily = credit_source.daily_credits or 0
                if daily > 0 and remaining > 0:
                    take = min(daily, remaining)
                    credit_source.daily_credits = daily - take
                    remaining -= take
                    credits_deducted += take

                # 2. Bundled credits (monthly allowance)
                bundled = credit_source.bundled_credits or 0
                if bundled > 0 and remaining > 0:
                    take = min(bundled, remaining)
                    credit_source.bundled_credits = bundled - take
                    remaining -= take
                    credits_deducted += take

                # 3. Signup bonus credits (if not expired)
                bonus = credit_source.signup_bonus_credits or 0
                if bonus > 0 and remaining > 0:
                    from ..database import ensure_aware

                    _expires = ensure_aware(credit_source.signup_bonus_expires_at)
                    expired = bool(_expires and datetime.now(UTC) > _expires)
                    if not expired:
                        take = min(bonus, remaining)
                        credit_source.signup_bonus_credits = bonus - take
                        remaining -= take
                        credits_deducted += take

                # 4. Purchased credits (permanent, last resort)
                purchased = credit_source.purchased_credits or 0
                if purchased > 0 and remaining > 0:
                    take = min(purchased, remaining)
                    credit_source.purchased_credits = purchased - take
                    remaining -= take
                    credits_deducted += take

            # Create UsageLog entry with both user_id (attribution) and team_id (billing)
            usage_log = UsageLog(
                user_id=user_id,
                team_id=resolved_team_id,
                agent_id=agent_id,
                project_id=project_id,
                model=model_name,
                tokens_input=tokens_in,
                tokens_output=tokens_out,
                cost_input=cost_input,
                cost_output=cost_output,
                cost_total=cost_total,
                is_byok=byok,
                request_id=request_id,
                billed_status="credited"
                if credits_deducted > 0
                else ("exempt" if byok else "pending"),
            )
            db.add(usage_log)

            # Flush the ledger row before calculating the per-member balance.
            # This makes the result include this exact provider response while
            # the team and membership locks remain held through the commit.
            await db.flush()
            if member_remaining_before is not None:
                member_remaining = await _member_allocation_remaining(
                    db,
                    team=credit_source,
                    user_id=user_id,
                )
            else:
                member_remaining = None

            await db.commit()
            await db.refresh(usage_log)
            break  # Success, exit retry loop
        except OperationalError as e:
            await db.rollback()
            if attempt < max_retries - 1:
                logger.warning(
                    f"Credit deduction retry {attempt + 1}/{max_retries} for user={user_id}: {e}"
                )
                continue
            logger.error(f"Credit deduction failed after {max_retries} retries for user={user_id}")
            raise

    new_balance = credit_source.total_credits

    logger.info(
        f"Credit deduction: user={user_id} team={resolved_team_id} model={model_name} "
        f"tokens_in={tokens_in} tokens_out={tokens_out} "
        f"cost={cost_total}¢ deducted={credits_deducted}¢ "
        f"balance={new_balance} byok={byok}"
    )

    return {
        "cost_total": cost_total,
        "credits_deducted": credits_deducted,
        "new_balance": new_balance,
        "usage_log_id": str(usage_log.id),
        "is_byok": byok,
        "already_recorded": False,
        "member_remaining": member_remaining,
        "allocation_exhausted": bool(
            member_remaining is not None and member_remaining <= 0 and not byok
        ),
    }

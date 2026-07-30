"""Backfill legacy agent-library rows into each user's default team.

Revision ID: 0124_backfill_agent_team
Revises: 0123_team_feature_access
Create Date: 2026-07-30
"""

from alembic import op


revision = "0124_backfill_agent_team"
down_revision = "0123_team_feature_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Make legacy library rows visible in the active team again."""
    op.execute(
        """
        UPDATE user_purchased_agents AS purchase
        SET team_id = users.default_team_id
        FROM users
        WHERE purchase.user_id = users.id
          AND purchase.team_id IS NULL
          AND users.default_team_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Data backfills are intentionally not reversed."""

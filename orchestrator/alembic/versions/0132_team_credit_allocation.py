"""Add team allocation modes and member credit ceilings.

Revision ID: 0132_team_credit_allocation
Revises: 0131_team_import_and_connectors_access
"""

import sqlalchemy as sa
from alembic import op


revision = "0132_team_credit_allocation"
down_revision = "0131_team_import_and_connectors_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add backward-compatible shared allocation fields and a stable reporting origin."""
    bind = op.get_bind()
    team_columns = {column["name"] for column in sa.inspect(bind).get_columns("teams")}
    membership_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("team_memberships")
    }
    if "credit_allocation_mode" not in team_columns:
        op.add_column(
            "teams",
            sa.Column(
                "credit_allocation_mode",
                sa.String(length=20),
                nullable=False,
                server_default="shared",
            ),
        )
    if "credit_cycle_started_at" not in team_columns:
        op.add_column("teams", sa.Column("credit_cycle_started_at", sa.DateTime(timezone=True)))
    if "credit_limit" not in membership_columns:
        op.add_column(
            "team_memberships",
            sa.Column("credit_limit", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    team_columns = {column["name"] for column in sa.inspect(bind).get_columns("teams")}
    membership_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("team_memberships")
    }
    if "credit_limit" in membership_columns:
        op.drop_column("team_memberships", "credit_limit")
    if "credit_cycle_started_at" in team_columns:
        op.drop_column("teams", "credit_cycle_started_at")
    if "credit_allocation_mode" in team_columns:
        op.drop_column("teams", "credit_allocation_mode")

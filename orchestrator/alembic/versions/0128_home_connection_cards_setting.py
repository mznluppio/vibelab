"""Add the platform switch for optional Home connection cards.

Revision ID: 0128_home_connection_cards_setting
Revises: 0127_platform_workspace_governance
"""

import sqlalchemy as sa
from alembic import op

revision = "0128_home_connection_cards_setting"
down_revision = "0127_platform_workspace_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("platform_settings")}
    if "show_home_connection_cards" not in columns:
        op.add_column(
            "platform_settings",
            sa.Column(
                "show_home_connection_cards",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("platform_settings")}
    if "show_home_connection_cards" in columns:
        op.drop_column("platform_settings", "show_home_connection_cards")

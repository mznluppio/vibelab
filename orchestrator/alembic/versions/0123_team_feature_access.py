"""Add team-scoped Marketplace and Automations visibility settings.

Revision ID: 0123_team_feature_access
Revises: 0122_platform_settings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0123_team_feature_access"
down_revision = "0122_platform_settings"
branch_labels = None
depends_on = None

_COLUMNS = (
    "marketplace_access_for_non_admins",
    "automations_access_for_non_admins",
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("teams")}
    for name in _COLUMNS:
        if name not in existing:
            op.add_column(
                "teams",
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()),
            )


def downgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("teams")}
    for name in _COLUMNS:
        if name in existing:
            op.drop_column("teams", name)

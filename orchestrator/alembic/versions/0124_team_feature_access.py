"""Add team-scoped marketplace and automations access settings.

Revision ID: 0124_team_feature_access
Revises: 0123_restore_vibelab_default_theme
"""

import sqlalchemy as sa
from alembic import op

revision = "0124_team_feature_access"
down_revision = "0123_restore_vibelab_default_theme"
branch_labels = None
depends_on = None


_COLUMNS = (
    "marketplace_access_for_non_admins",
    "automations_access_for_non_admins",
)


def upgrade() -> None:
    """Add defaults safely when upgrading databases with partially applied DDL."""
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

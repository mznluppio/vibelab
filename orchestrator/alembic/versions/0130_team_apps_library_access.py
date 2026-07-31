"""Add team-scoped Apps and Library access settings.

Revision ID: 0130_team_apps_library_access
Revises: 0129_platform_auth_appearance
"""

import sqlalchemy as sa
from alembic import op

revision = "0130_team_apps_library_access"
down_revision = "0129_platform_auth_appearance"
branch_labels = None
depends_on = None


_COLUMNS = (
    "apps_access_for_non_admins",
    "library_access_for_non_admins",
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

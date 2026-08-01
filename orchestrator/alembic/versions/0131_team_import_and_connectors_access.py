"""Add team settings for repository imports and prompt connectors.

Revision ID: 0131_team_import_and_connectors_access
Revises: 0130_team_apps_library_access
"""

import sqlalchemy as sa
from alembic import op

revision = "0131_team_import_and_connectors_access"
down_revision = "0130_team_apps_library_access"
branch_labels = None
depends_on = None


_COLUMNS = (
    "repository_import_access_for_non_admins",
    "prompt_connectors_access_for_non_admins",
)


def upgrade() -> None:
    """Add backwards-compatible defaults for all existing teams."""
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("teams")}
    for name in _COLUMNS:
        if name not in existing:
            op.add_column(
                "teams",
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()),
            )


def downgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("teams")}
    for name in _COLUMNS:
        if name in existing:
            op.drop_column("teams", name)

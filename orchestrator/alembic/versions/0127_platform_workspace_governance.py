"""Add platform Workspace-creation governance and per-user override.

Extends the existing singleton ``platform_settings`` row rather than
introducing a second policy table, and mirrors ``can_create_teams_override``
with ``can_create_workspaces_override`` on ``users``.

Both default to the secure internal-deployment posture: standard users cannot
create Workspaces until a platform admin enables it (globally or per user).

Revision ID: 0127_platform_workspace_governance
Revises: 0126_restore_vibelab_light_theme
"""

import sqlalchemy as sa
from alembic import op

revision = "0127_platform_workspace_governance"
down_revision = "0126_restore_vibelab_light_theme"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    settings_columns = {c["name"] for c in inspector.get_columns("platform_settings")}
    if "allow_user_workspace_creation" not in settings_columns:
        op.add_column(
            "platform_settings",
            sa.Column(
                "allow_user_workspace_creation",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    user_columns = {c["name"] for c in inspector.get_columns("users")}
    if "can_create_workspaces_override" not in user_columns:
        op.add_column(
            "users",
            sa.Column("can_create_workspaces_override", sa.Boolean(), nullable=True),
        )

    # Keep the singleton row present so the admin surface always has a target.
    has_settings = bind.execute(sa.text("SELECT 1 FROM platform_settings WHERE id = 1")).scalar()
    if not has_settings:
        op.bulk_insert(
            sa.table(
                "platform_settings",
                sa.column("id", sa.Integer()),
                sa.column("automatically_create_personal_teams", sa.Boolean()),
                sa.column("allow_user_team_creation", sa.Boolean()),
                sa.column("allow_user_workspace_creation", sa.Boolean()),
            ),
            [
                {
                    "id": 1,
                    "automatically_create_personal_teams": False,
                    "allow_user_team_creation": False,
                    "allow_user_workspace_creation": False,
                }
            ],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_columns = {c["name"] for c in inspector.get_columns("users")}
    if "can_create_workspaces_override" in user_columns:
        op.drop_column("users", "can_create_workspaces_override")

    settings_columns = {c["name"] for c in inspector.get_columns("platform_settings")}
    if "allow_user_workspace_creation" in settings_columns:
        op.drop_column("platform_settings", "allow_user_workspace_creation")

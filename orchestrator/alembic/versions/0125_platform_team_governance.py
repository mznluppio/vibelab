"""Add singleton platform Team-governance settings and user overrides.

Revision ID: 0125_platform_team_governance
Revises: 0124_team_feature_access
"""

import sqlalchemy as sa
from alembic import op


revision = "0125_platform_team_governance"
down_revision = "0124_team_feature_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "platform_settings" not in inspector.get_table_names():
        op.create_table(
            "platform_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "automatically_create_personal_teams",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "allow_user_team_creation",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint("id = 1", name="ck_platform_settings_singleton"),
        )

    user_columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "can_create_teams_override" not in user_columns:
        op.add_column("users", sa.Column("can_create_teams_override", sa.Boolean(), nullable=True))

    has_settings = bind.execute(sa.text("SELECT 1 FROM platform_settings WHERE id = 1")).scalar()
    if not has_settings:
        op.bulk_insert(
            sa.table(
                "platform_settings",
                sa.column("id", sa.Integer()),
                sa.column("automatically_create_personal_teams", sa.Boolean()),
                sa.column("allow_user_team_creation", sa.Boolean()),
            ),
            [
                {
                    "id": 1,
                    "automatically_create_personal_teams": False,
                    "allow_user_team_creation": False,
                }
            ],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "can_create_teams_override" in user_columns:
        op.drop_column("users", "can_create_teams_override")
    if "platform_settings" in inspector.get_table_names():
        op.drop_table("platform_settings")

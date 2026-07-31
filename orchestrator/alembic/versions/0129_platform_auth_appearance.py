"""Add platform-managed authentication presentation settings.

Revision ID: 0129_platform_auth_appearance
Revises: 0128_home_connection_cards_setting
"""

import sqlalchemy as sa
from alembic import op

revision = "0129_platform_auth_appearance"
down_revision = "0128_home_connection_cards_setting"
branch_labels = None
depends_on = None

DEFAULT_AUTH_BACKGROUND = "linear-gradient(135deg, #0f172a, #0055a4)"


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("platform_settings")}
    additions = (
        ("show_google_sign_in", sa.Column("show_google_sign_in", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("show_github_sign_in", sa.Column("show_github_sign_in", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("auth_background_mode", sa.Column("auth_background_mode", sa.String(length=16), nullable=False, server_default="gradient")),
        ("auth_background_value", sa.Column("auth_background_value", sa.Text(), nullable=False, server_default=DEFAULT_AUTH_BACKGROUND)),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("platform_settings", column)


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("platform_settings")}
    for name in (
        "auth_background_value",
        "auth_background_mode",
        "show_github_sign_in",
        "show_google_sign_in",
    ):
        if name in columns:
            op.drop_column("platform_settings", name)

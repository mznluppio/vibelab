"""Restore VibeLab branding for the legacy light theme identifier.

Revision ID: 0126_restore_vibelab_light_theme
Revises: 0125_platform_team_governance
"""

import json

from alembic import op
from sqlalchemy import text

revision = "0126_restore_vibelab_light_theme"
down_revision = "0125_platform_team_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Brand the persisted light fallback without changing user preferences."""
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        rows = bind.execute(
            text(
                "SELECT id, theme_json FROM themes "
                "WHERE slug = 'default-light' "
                "AND (source_id IS NULL OR source_id = '00000000-0000-0000-0000-000000000001')"
            )
        ).mappings()
        for row in rows:
            theme_json = row["theme_json"]
            if isinstance(theme_json, str):
                theme_json = json.loads(theme_json)
            theme_json = dict(theme_json or {})
            colors = dict(theme_json.get("colors") or {})
            colors.update(
                {
                    "primary": "#0055A4",
                    "primaryHover": "#004580",
                    "primaryRgb": "0, 85, 164",
                    "accent": "#00A3E0",
                }
            )
            sidebar = dict(colors.get("sidebar") or {})
            sidebar["active"] = "rgba(0, 85, 164, 0.15)"
            colors["sidebar"] = sidebar
            input_colors = dict(colors.get("input") or {})
            input_colors["borderFocus"] = "#0055A4"
            colors["input"] = input_colors
            code = dict(colors.get("code") or {})
            code.update(
                {
                    "inlineBackground": "rgba(0, 85, 164, 0.1)",
                    "inlineText": "#0055A4",
                }
            )
            colors["code"] = code
            theme_json["colors"] = colors
            bind.execute(
                text(
                    "UPDATE themes SET name = :name, author = :author, "
                    "description = :description, theme_json = :theme_json WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "name": "VibeLab Light",
                    "author": "VibeLab by Legrand",
                    "description": "The official VibeLab light theme",
                    "theme_json": json.dumps(theme_json),
                },
            )
        return

    bind.execute(
        text(
            """
            UPDATE themes
            SET name = 'VibeLab Light',
                author = 'VibeLab by Legrand',
                description = 'The official VibeLab light theme',
                theme_json = jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            jsonb_set(
                                jsonb_set(
                                    jsonb_set(
                                        jsonb_set(
                                            theme_json::jsonb, '{colors,primary}', '"#0055A4"', true
                                        ),
                                        '{colors,primaryHover}', '"#004580"', true
                                    ),
                                    '{colors,primaryRgb}', '"0, 85, 164"', true
                                ),
                                '{colors,accent}', '"#00A3E0"', true
                            ),
                            '{colors,sidebar,active}', '"rgba(0, 85, 164, 0.15)"', true
                        ),
                        '{colors,input,borderFocus}', '"#0055A4"', true
                    ),
                    '{colors,code,inlineBackground}', '"rgba(0, 85, 164, 0.1)"', true
                )
            WHERE slug = 'default-light'
              AND (
                source_id IS NULL
                OR source_id = '00000000-0000-0000-0000-000000000001'
              )
            """
        )
    )
    bind.execute(
        text(
            """
            UPDATE themes
            SET theme_json = jsonb_set(
                theme_json::jsonb, '{colors,code,inlineText}', '"#0055A4"', true
            )
            WHERE slug = 'default-light'
              AND (
                source_id IS NULL
                OR source_id = '00000000-0000-0000-0000-000000000001'
              )
            """
        )
    )


def downgrade() -> None:
    # Stable user/team preference IDs must not be reverted to retired branding.
    pass

"""Restore VibeLab branding for the legacy default theme identifier.

Revision ID: 0123_restore_vibelab_default_theme
Revises: 0122_vibelab_marketplace_display_branding
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


revision = "0123_restore_vibelab_default_theme"
down_revision = "0122_vibelab_marketplace_display_branding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Repair the official cached theme without changing user preferences.

    ``default-dark`` is a public, persisted preference value. Keeping that
    identifier avoids resetting users while replacing only its official
    Tesslate-era presentation with VibeLab's stable brand colors.
    """
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        # Desktop uses SQLite. Keep its existing local catalogs usable too;
        # JSON mutation functions are PostgreSQL-specific, so update the
        # structured payload in Python rather than skipping the repair.
        rows = bind.execute(
            text(
                "SELECT id, theme_json FROM themes "
                "WHERE slug = 'default-dark' AND source_id IS NULL"
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
            code["inlineText"] = "#00A3E0"
            colors["code"] = code
            theme_json["colors"] = colors
            bind.execute(
                text(
                    "UPDATE themes SET name = :name, author = :author, "
                    "description = :description, is_default = :is_default, "
                    "theme_json = :theme_json WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "name": "VibeLab Dark",
                    "author": "VibeLab by Legrand",
                    "description": "The official VibeLab dark theme",
                    "is_default": True,
                    "theme_json": json.dumps(theme_json),
                },
            )
        return

    bind.execute(
        text(
            """
            UPDATE themes
            SET name = 'VibeLab Dark',
                author = 'VibeLab by Legrand',
                description = 'The official VibeLab dark theme',
                is_default = true,
                theme_json = jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            jsonb_set(
                                jsonb_set(
                                    jsonb_set(
                                        jsonb_set(theme_json::jsonb, '{colors,primary}', '"#0055A4"', true),
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
                    '{colors,code,inlineText}', '"#00A3E0"', true
                )
            WHERE slug = 'default-dark'
              AND (
                source_id IS NULL
                OR source_id = '00000000-0000-0000-0000-000000000001'
              )
            """
        )
    )


def downgrade() -> None:
    # The old identifier is intentionally retained; reverting code must not
    # reintroduce the retired orange branding into persisted user state.
    pass

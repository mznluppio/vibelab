"""Refresh legacy marketplace display values without changing protocol IDs.

Revision ID: 0122_vibelab_marketplace_display_branding
Revises: 0121_seed_system_default_agent
"""

from alembic import op
from sqlalchemy import text


revision = "0122_vibelab_marketplace_display_branding"
down_revision = "0121_seed_system_default_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # The handle and UUID are federation compatibility keys. Only the display
    # name changes, and only when it still carries the legacy visible value.
    bind.execute(
        text(
            """
            UPDATE marketplace_sources
            SET display_name = 'Legrand Official'
            WHERE handle = 'tesslate-official'
              AND display_name IN ('Tesslate Official', 'Tesslate Marketplace')
            """
        )
    )

    # Existing synchronized caches can render before their next /v1 change
    # poll. Refresh the visible fields now; the rebranded seed keeps them
    # stable on every later synchronization.
    bind.execute(
        text(
            """
            UPDATE marketplace_agents
            SET name = 'VibeLab Default',
                description = 'The official VibeLab autonomous software engineering agent',
                long_description = 'VibeLab Default is a full-featured coding assistant with subagent delegation, context compaction, and native OpenAI function calling. It reads files, executes commands, plans complex tasks, and iteratively solves problems until complete.'
            WHERE slug = 'tesslate-agent'
              AND name = 'Tesslate Agent'
            """
        )
    )

    bind.execute(
        text(
            """
            UPDATE marketplace_agents
            SET name = 'VibeLab Default',
                description = 'The built-in VibeLab coding assistant. Always available to every user.',
                long_description = 'VibeLab’s general-purpose autonomous coding agent. Reads, writes, and patches files; executes shell commands; plans multi-step tasks; and delegates to specialist sub-agents.'
            WHERE id = '00000000-0000-0000-0000-000000000005'
            """
        )
    )


def downgrade() -> None:
    # Display-only data migration: retain VibeLab branding on downgrade.
    pass

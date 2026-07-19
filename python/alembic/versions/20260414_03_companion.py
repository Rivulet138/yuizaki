"""companion entity and workspace binding

Revision ID: 20260414_03
Revises: 20260414_02
Create Date: 2026-04-14 18:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260414_03"
down_revision = "20260414_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companions",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("avatar", sa.String(length=255), nullable=True),
        sa.Column("model_type", sa.String(length=32), nullable=True),
        sa.Column("model_id", sa.String(length=100), nullable=True),
        sa.Column("voice_profile", sa.Text(), nullable=True),
        sa.Column("persona_prompt", sa.Text(), nullable=True),
        sa.Column("emotion_state", sa.String(length=32), nullable=True),
        sa.Column("affinity_state", sa.Float(), nullable=True),
        sa.Column("energy_state", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        """
        INSERT INTO companions (id, name, avatar, model_type, model_id, voice_profile, persona_prompt, emotion_state, affinity_state, energy_state, created_at, updated_at)
        VALUES ('default', '默认結崎', NULL, 'live2d', 'hiyori', NULL, NULL, 'neutral', 0.5, 1.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    )

    op.execute(
        "UPDATE workspaces SET companion_profile_id = 'default' WHERE companion_profile_id IS NULL"
    )


def downgrade() -> None:
    op.execute("UPDATE workspaces SET companion_profile_id = NULL WHERE companion_profile_id = 'default'")
    op.drop_table("companions")

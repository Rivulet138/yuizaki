"""workspace companion foreign key hardening

Revision ID: 20260421_01
Revises: 20260414_04
Create Date: 2026-04-21 18:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_01"
down_revision = "20260414_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("INSERT OR IGNORE INTO companions (id, name, model_type, emotion_state, affinity_state, energy_state, temperament, attachment_style, support_style, created_at, updated_at) VALUES ('default', '默认結崎', 'live2d', 'neutral', 0.5, 1.0, 'warm', 'secure', 'gentle', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    conn.execute(sa.text("UPDATE workspaces SET companion_profile_id = 'default' WHERE companion_profile_id IS NULL OR companion_profile_id = '' OR companion_profile_id NOT IN (SELECT id FROM companions)"))

    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.alter_column("companion_profile_id", existing_type=sa.String(length=50), nullable=False)
        batch_op.create_foreign_key("fk_workspaces_companion_profile_id", "companions", ["companion_profile_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.drop_constraint("fk_workspaces_companion_profile_id", type_="foreignkey")
        batch_op.alter_column("companion_profile_id", existing_type=sa.String(length=50), nullable=True)

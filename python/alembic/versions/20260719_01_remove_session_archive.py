"""remove session archive state

Revision ID: 20260719_01
Revises: 20260422_01
Create Date: 2026-07-19 18:00:00
"""

from __future__ import annotations

from alembic import op


revision = "20260719_01"
down_revision = "20260422_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_column("archived")


def downgrade() -> None:
    raise RuntimeError("This permanent data cleanup cannot be downgraded")

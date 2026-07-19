"""companion relationship state fields

Revision ID: 20260422_01
Revises: 20260421_01
Create Date: 2026-04-22 18:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260422_01"
down_revision = "20260421_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companions", sa.Column("trust_state", sa.Float(), nullable=True))
    op.add_column("companions", sa.Column("intimacy_state", sa.Float(), nullable=True))
    op.add_column("companions", sa.Column("interruptibility_state", sa.Float(), nullable=True))
    op.add_column("companions", sa.Column("fatigue_state", sa.Float(), nullable=True))
    op.execute("UPDATE companions SET trust_state = 0.5 WHERE trust_state IS NULL")
    op.execute("UPDATE companions SET intimacy_state = 0.5 WHERE intimacy_state IS NULL")
    op.execute("UPDATE companions SET interruptibility_state = 0.75 WHERE interruptibility_state IS NULL")
    op.execute("UPDATE companions SET fatigue_state = 0.0 WHERE fatigue_state IS NULL")


def downgrade() -> None:
    op.drop_column("companions", "fatigue_state")
    op.drop_column("companions", "interruptibility_state")
    op.drop_column("companions", "intimacy_state")
    op.drop_column("companions", "trust_state")

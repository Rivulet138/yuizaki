"""companion style fields

Revision ID: 20260414_04
Revises: 20260414_03
Create Date: 2026-04-14 21:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260414_04"
down_revision = "20260414_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companions", sa.Column("temperament", sa.String(length=32), nullable=True))
    op.add_column("companions", sa.Column("attachment_style", sa.String(length=32), nullable=True))
    op.add_column("companions", sa.Column("support_style", sa.String(length=32), nullable=True))
    op.execute("UPDATE companions SET temperament = 'warm' WHERE temperament IS NULL")
    op.execute("UPDATE companions SET attachment_style = 'secure' WHERE attachment_style IS NULL")
    op.execute("UPDATE companions SET support_style = 'gentle' WHERE support_style IS NULL")


def downgrade() -> None:
    op.drop_column("companions", "support_style")
    op.drop_column("companions", "attachment_style")
    op.drop_column("companions", "temperament")

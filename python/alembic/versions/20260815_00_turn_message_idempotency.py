"""add idempotent turn identity to chat messages

Revision ID: 20260815_00
Revises: 20260808_00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260815_00"
down_revision = "20260808_00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    column_names = {
        str(column["name"])
        for column in inspector.get_columns("chat_messages")
    }
    if "turn_idempotency_key" not in column_names:
        with op.batch_alter_table("chat_messages") as batch_op:
            batch_op.add_column(
                sa.Column("turn_idempotency_key", sa.String(length=80), nullable=True)
            )
    index_names = {
        str(index["name"])
        for index in inspect(connection).get_indexes("chat_messages")
    }
    if "uq_chat_message_turn_role" not in index_names:
        with op.batch_alter_table("chat_messages") as batch_op:
            batch_op.create_index(
                "uq_chat_message_turn_role",
                ["turn_idempotency_key", "role"],
                unique=True,
            )


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.drop_index("uq_chat_message_turn_role")
        batch_op.drop_column("turn_idempotency_key")

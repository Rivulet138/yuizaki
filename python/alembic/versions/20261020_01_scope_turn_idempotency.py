"""scope turn idempotency by chat session

Revision ID: 20261020_01
Revises: 20261020_00
"""

from __future__ import annotations

from sqlalchemy import inspect

from alembic import op

revision = "20261020_01"
down_revision = "20261020_00"
branch_labels = None
depends_on = None


CHAT_MESSAGES_TABLE = "chat_messages"
TURN_ROLE_INDEX = "uq_chat_message_turn_role"
LEGACY_INDEX_COLUMNS = ("turn_idempotency_key", "role")
SCOPED_INDEX_COLUMNS = ("session_id", "turn_idempotency_key", "role")


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    indexes = {
        str(index.get("name")): index
        for index in inspector.get_indexes(CHAT_MESSAGES_TABLE)
        if index.get("name")
    }
    current = indexes.get(TURN_ROLE_INDEX)
    if (
        current
        and tuple(current.get("column_names") or ()) == SCOPED_INDEX_COLUMNS
        and bool(current.get("unique"))
    ):
        return
    with op.batch_alter_table(CHAT_MESSAGES_TABLE) as batch_op:
        if current:
            batch_op.drop_index(TURN_ROLE_INDEX)
        batch_op.create_index(
            TURN_ROLE_INDEX,
            list(SCOPED_INDEX_COLUMNS),
            unique=True,
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    indexes = {
        str(index.get("name")): index
        for index in inspector.get_indexes(CHAT_MESSAGES_TABLE)
        if index.get("name")
    }
    current = indexes.get(TURN_ROLE_INDEX)
    with op.batch_alter_table(CHAT_MESSAGES_TABLE) as batch_op:
        if current:
            batch_op.drop_index(TURN_ROLE_INDEX)
        batch_op.create_index(
            TURN_ROLE_INDEX,
            list(LEGACY_INDEX_COLUMNS),
            unique=True,
        )

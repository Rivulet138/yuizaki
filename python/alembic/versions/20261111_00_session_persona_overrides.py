"""Store session-local persona scenario and example dialogue overrides.

Revision ID: 20261111_00
Revises: 20261020_01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261111_00"
down_revision = "20261020_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("chat_sessions")}
    if "persona_overrides" not in columns:
        with op.batch_alter_table("chat_sessions") as batch_op:
            batch_op.add_column(sa.Column("persona_overrides", sa.JSON(none_as_null=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_column("persona_overrides")

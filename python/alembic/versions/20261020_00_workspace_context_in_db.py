"""store workspace ambient context inside the workspace row

Workspace context used to live in a JSON sidecar next to the SQLite database,
which meant two independent writes per change: a crash (or a database failure
after the sidecar write) could leave the sidecar and the workspace row
describing different states. Keeping the payload on the row makes the context
commit atomically with the metadata it belongs to.

Revision ID: 20261020_00
Revises: 20260815_00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261020_00"
down_revision = "20260815_00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    column_names = {
        str(column["name"])
        for column in inspector.get_columns("workspaces")
    }
    if "context" not in column_names:
        with op.batch_alter_table("workspaces") as batch_op:
            batch_op.add_column(sa.Column("context", sa.JSON(), nullable=True))
    if "context_revision" not in column_names:
        with op.batch_alter_table("workspaces") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "context_revision",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.drop_column("context_revision")
        batch_op.drop_column("context")

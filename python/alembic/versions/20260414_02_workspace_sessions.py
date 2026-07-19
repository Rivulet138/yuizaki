"""workspace and session metadata

Revision ID: 20260414_02
Revises: 20260414_01
Create Date: 2026-04-14 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260414_02"
down_revision = "20260414_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=64), nullable=True),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("companion_profile_id", sa.String(length=50), nullable=True),
        sa.Column("default_model", sa.String(length=100), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("tool_preset", sa.Text(), nullable=True),
        sa.Column("memory_scope", sa.String(length=32), nullable=True),
        sa.Column("mcp_preset_id", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column("chat_sessions", sa.Column("workspace_id", sa.String(length=50), nullable=True))
    op.add_column("chat_sessions", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("chat_sessions", sa.Column("pinned", sa.Boolean(), nullable=True))
    op.add_column("chat_sessions", sa.Column("archived", sa.Boolean(), nullable=True))
    op.create_index("ix_chat_sessions_workspace_id", "chat_sessions", ["workspace_id"], unique=False)
    op.create_index("idx_workspace_updated", "chat_sessions", ["workspace_id", "updated_at"], unique=False)

    op.execute(
        """
        INSERT INTO workspaces (id, name, description, icon, color, companion_profile_id, default_model, system_prompt, tool_preset, memory_scope, mcp_preset_id, created_at, updated_at)
        VALUES ('default', '默认工作区', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'workspace', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
    )
    op.execute("UPDATE chat_sessions SET workspace_id = 'default' WHERE workspace_id IS NULL")
    op.execute("UPDATE chat_sessions SET pinned = 0 WHERE pinned IS NULL")
    op.execute("UPDATE chat_sessions SET archived = 0 WHERE archived IS NULL")


def downgrade() -> None:
    op.drop_index("idx_workspace_updated", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_workspace_id", table_name="chat_sessions")
    op.drop_column("chat_sessions", "archived")
    op.drop_column("chat_sessions", "pinned")
    op.drop_column("chat_sessions", "summary")
    op.drop_column("chat_sessions", "workspace_id")
    op.drop_table("workspaces")

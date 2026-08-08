"""current application schema baseline

Revision ID: 20260808_00
Revises: None
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
from sqlalchemy import insert, select

from database.models import Base, Companion, Workspace


revision = "20260808_00"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    Base.metadata.create_all(bind=connection)

    # A fresh install needs the two protected records required by repository APIs.
    companions = Base.metadata.tables[Companion.__tablename__]
    workspaces = Base.metadata.tables[Workspace.__tablename__]
    now = datetime.now(timezone.utc)
    if connection.execute(select(companions.c.id).where(companions.c.id == "default")).first() is None:
        connection.execute(insert(companions).values(
            id="default",
            name="Default Companion",
            model_type="live2d",
            temperament="warm",
            attachment_style="secure",
            support_style="gentle",
            emotion_state="neutral",
            affinity_state=0.5,
            energy_state=1.0,
            trust_state=0.5,
            intimacy_state=0.5,
            interruptibility_state=0.75,
            fatigue_state=0.0,
            created_at=now,
            updated_at=now,
        ))
    if connection.execute(select(workspaces.c.id).where(workspaces.c.id == "default")).first() is None:
        connection.execute(insert(workspaces).values(
            id="default",
            name="Default Workspace",
            companion_profile_id="default",
            memory_scope="workspace",
            created_at=now,
            updated_at=now,
        ))


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

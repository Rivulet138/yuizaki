"""Database models - SQLAlchemy ORM definitions."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""


class ChatMessage(Base):
    """聊天消息表"""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, default=0)
    model: Mapped[str | None] = mapped_column(String(100))
    # JSON payloads intentionally contain only user-visible tool/memory metadata.
    tool_trace: Mapped[str | None] = mapped_column(Text)
    memory_trace: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index('idx_session_timestamp', 'session_id', 'timestamp'),
    )


class ChatSession(Base):
    """聊天会话表"""
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    workspace_id: Mapped[str | None] = mapped_column(String(50), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    pinned: Mapped[bool | None] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    parent_session_id: Mapped[str | None] = mapped_column(String(50))
    branched_from_message_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    message_count: Mapped[int | None] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int | None] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index('idx_created_at', 'created_at'),
        Index('idx_workspace_updated', 'workspace_id', 'updated_at'),
    )


class Workspace(Base):
    """工作区表"""
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(64))
    color: Mapped[str | None] = mapped_column(String(32))
    companion_profile_id: Mapped[str] = mapped_column(String(50), ForeignKey("companions.id"), nullable=False, default="default")
    default_model: Mapped[str | None] = mapped_column(String(100))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    tool_preset: Mapped[str | None] = mapped_column(Text)
    memory_scope: Mapped[str | None] = mapped_column(String(32), default="workspace")
    mcp_preset_id: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    companion: Mapped["Companion"] = relationship(foreign_keys=[companion_profile_id], lazy="joined", back_populates="workspaces")


class Companion(Base):
    """結崎角色表"""
    __tablename__ = "companions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(255))
    model_type: Mapped[str | None] = mapped_column(String(32), default="live2d")
    model_id: Mapped[str | None] = mapped_column(String(100))
    voice_profile: Mapped[str | None] = mapped_column(Text)
    persona_prompt: Mapped[str | None] = mapped_column(Text)
    temperament: Mapped[str | None] = mapped_column(String(32), default="warm")
    attachment_style: Mapped[str | None] = mapped_column(String(32), default="secure")
    support_style: Mapped[str | None] = mapped_column(String(32), default="gentle")
    emotion_state: Mapped[str | None] = mapped_column(String(32), default="neutral")
    affinity_state: Mapped[float | None] = mapped_column(Float, default=0.5)
    energy_state: Mapped[float | None] = mapped_column(Float, default=1.0)
    trust_state: Mapped[float | None] = mapped_column(Float, default=0.5)
    intimacy_state: Mapped[float | None] = mapped_column(Float, default=0.5)
    interruptibility_state: Mapped[float | None] = mapped_column(Float, default=0.75)
    fatigue_state: Mapped[float | None] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    workspaces: Mapped[list[Workspace]] = relationship(
        foreign_keys="Workspace.companion_profile_id",
        lazy="selectin",
        back_populates="companion",
        viewonly=True,
    )


class UserStatistics(Base):
    """用户统计表"""
    __tablename__ = "user_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)  # YYYY-MM-DD
    total_messages: Mapped[int | None] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int | None] = mapped_column(Integer, default=0)
    avg_response_time: Mapped[float | None] = mapped_column(Float, default=0.0)
    ocr_count: Mapped[int | None] = mapped_column(Integer, default=0)
    svc_count: Mapped[int | None] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class UserSettings(Base):
    """用户设置表"""
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

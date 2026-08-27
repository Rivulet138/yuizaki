"""数据访问层 - 数据库操作接口"""

from __future__ import annotations

from sqlalchemy import create_engine, func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import csv
from io import StringIO
import logging
from uuid import uuid4

from typing import Any

from modules.core.paths import data_dir_from_env, database_url_from_env

from .models import ChatMessage, ChatSession, UserStatistics, UserSettings, Workspace, Companion

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = data_dir_from_env() / "chat.db"
DEFAULT_DB_PATH_STR = str(DEFAULT_DB_PATH)


def _isoformat_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class RepositoryError(RuntimeError):
    """仓储层异常基类"""
    pass


class NotFoundError(RepositoryError):
    """资源不存在异常"""
    pass


class DatabaseError(RepositoryError):
    """数据库操作异常"""
    pass


class DatabaseRepository:
    """数据库操作类"""

    def __init__(self, db_path: str | Path | None = None):
        """初始化数据库连接

        Args:
            db_path: Optional explicit SQLite database file path. When omitted,
                DATABASE_URL takes precedence over YUIZAKI_DATA_DIR/chat.db.
        """
        if db_path is None:
            database_url = database_url_from_env()
        else:
            explicit_path = Path(db_path).expanduser()
            explicit_path.parent.mkdir(parents=True, exist_ok=True)
            database_url = f"sqlite:///{explicit_path.as_posix()}"

        parsed_url = make_url(database_url)
        is_sqlite = parsed_url.get_backend_name() == "sqlite"
        database_name = parsed_url.database
        self.db_path = (
            Path(database_name).expanduser()
            if is_sqlite and database_name not in (None, "", ":memory:")
            else None
        )
        if self.db_path is not None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_url = database_url

        # 创建数据库引擎
        engine_options: dict[str, Any] = {"echo": False}
        if is_sqlite:
            engine_options["connect_args"] = {"check_same_thread": False}
        self.engine = create_engine(database_url, **engine_options)

        # 创建会话工厂
        self.SessionLocal = sessionmaker(bind=self.engine)
        logger.info("Database initialized at %s", self.db_path or parsed_url.render_as_string())

    def close(self) -> None:
        """Dispose database engine and release pooled connections."""
        try:
            self.engine.dispose()
        except Exception as exc:
            logger.warning("Failed to dispose database engine: %s", exc)

    def _normalize_workspace_id(self, workspace_id: str | None) -> str:
        return str(workspace_id or "default").strip() or "default"

    def _require_workspace(self, session: Any, workspace_id: str | None) -> str:
        normalized = self._normalize_workspace_id(workspace_id)
        workspace = session.query(Workspace).filter_by(id=normalized).first()
        if workspace is None:
            raise NotFoundError(f"workspace_not_found: {normalized}")
        return normalized

    def _message_to_record(self, message: ChatMessage) -> dict[str, Any]:
        def decode(value: str | None) -> list[dict[str, Any]]:
            if not value:
                return []
            try:
                payload = json.loads(value)
                return payload if isinstance(payload, list) else []
            except (TypeError, ValueError):
                return []
        tool_trace = decode(message.tool_trace)
        memory_trace = decode(message.memory_trace)
        return {
            "id": message.id,
            "session_id": message.session_id,
            "role": message.role,
            "content": message.content,
            "timestamp": _isoformat_or_none(message.timestamp),
            "tokens": message.tokens_used,
            "model": message.model,
            "agentSteps": tool_trace,
            "memorySources": memory_trace,
        }

    def _session_to_record(self, chat_session: ChatSession) -> dict[str, Any]:
        return {
            "id": chat_session.id,
            "workspace_id": chat_session.workspace_id,
            "title": chat_session.title,
            "summary": chat_session.summary,
            "pinned": bool(chat_session.pinned),
            "archived": bool(chat_session.archived),
            "parent_session_id": chat_session.parent_session_id,
            "branched_from_message_id": chat_session.branched_from_message_id,
            "created_at": _isoformat_or_none(chat_session.created_at),
            "updated_at": _isoformat_or_none(chat_session.updated_at),
            "message_count": int(chat_session.message_count or 0),
            "total_tokens": int(chat_session.total_tokens or 0),
        }

    def save_message(self, session_id: str, role: str, content: str,
                     tokens: int = 0, model: str = "", workspace_id: str = "default",
                     tool_trace: list[dict[str, Any]] | None = None,
                     memory_trace: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """保存聊天消息

        Args:
            session_id: 会话 ID
            role: 角色（user/assistant）
            content: 消息内容
            tokens: 使用的 token 数
            model: 使用的模型

        Raises:
            DatabaseError: 保存失败时抛出
        """
        session = self.SessionLocal()
        try:
            normalized_workspace_id = self._require_workspace(session, workspace_id)
            # 创建消息记录
            msg = ChatMessage(
                session_id=session_id,
                role=role,
                content=content,
                tokens_used=tokens,
                model=model,
                tool_trace=json.dumps(tool_trace, ensure_ascii=False) if tool_trace else None,
                memory_trace=json.dumps(memory_trace, ensure_ascii=False) if memory_trace else None,
            )
            session.add(msg)

            # 更新或创建会话
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if not chat_session:
                chat_session = ChatSession(
                    id=session_id,
                    workspace_id=normalized_workspace_id,
                    title=f"Chat {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
                    pinned=False,
                    message_count=0,
                    total_tokens=0,
                )
                session.add(chat_session)
            elif not chat_session.workspace_id:
                chat_session.workspace_id = normalized_workspace_id
            elif chat_session.workspace_id != normalized_workspace_id:
                raise DatabaseError(
                    f"session_workspace_mismatch: {session_id} belongs to {chat_session.workspace_id}, not {normalized_workspace_id}"
                )

            chat_session.message_count = (chat_session.message_count or 0) + 1
            chat_session.total_tokens = (chat_session.total_tokens or 0) + tokens
            chat_session.updated_at = datetime.now(timezone.utc)

            session.flush()
            saved_message = self._message_to_record(msg)
            session.commit()
            logger.debug(f"Message saved: {session_id} - {role}")
            return saved_message
        except Exception as exc:
            logger.exception(f"Failed to save message: {exc}")
            session.rollback()
            raise DatabaseError(f"failed_to_save_message: {exc}") from exc
        finally:
            session.close()

    def save_message_pair(
        self,
        session_id: str,
        user_content: str,
        assistant_content: str,
        *,
        model: str = "",
        workspace_id: str = "default",
        tool_trace: list[dict[str, Any]] | None = None,
        memory_trace: list[dict[str, Any]] | None = None,
        turn_idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Persist one user/assistant turn atomically and in conversation order."""
        session = self.SessionLocal()
        try:
            normalized_workspace_id = self._require_workspace(session, workspace_id)
            normalized_turn_key = str(turn_idempotency_key or "").strip() or None
            if normalized_turn_key is not None:
                existing = session.query(ChatMessage)\
                    .filter(ChatMessage.turn_idempotency_key == normalized_turn_key)\
                    .order_by(ChatMessage.id.asc())\
                    .all()
                by_role = {message.role: message for message in existing}
                if "user" in by_role and "assistant" in by_role:
                    return (
                        self._message_to_record(by_role["user"]),
                        self._message_to_record(by_role["assistant"]),
                    )
                if existing:
                    raise DatabaseError(
                        "incomplete_turn_message_pair: existing idempotent turn is partial"
                    )
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if not chat_session:
                chat_session = ChatSession(
                    id=session_id,
                    workspace_id=normalized_workspace_id,
                    title=f"Chat {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
                    pinned=False,
                    message_count=0,
                    total_tokens=0,
                )
                session.add(chat_session)
            elif not chat_session.workspace_id:
                chat_session.workspace_id = normalized_workspace_id
            elif chat_session.workspace_id != normalized_workspace_id:
                raise DatabaseError(
                    f"session_workspace_mismatch: {session_id} belongs to "
                    f"{chat_session.workspace_id}, not {normalized_workspace_id}"
                )

            user_message = ChatMessage(
                session_id=session_id,
                role="user",
                content=user_content,
                tokens_used=0,
                model=model,
                turn_idempotency_key=normalized_turn_key,
            )
            assistant_message = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=assistant_content,
                tokens_used=0,
                model=model,
                turn_idempotency_key=normalized_turn_key,
                tool_trace=json.dumps(tool_trace, ensure_ascii=False) if tool_trace else None,
                memory_trace=json.dumps(memory_trace, ensure_ascii=False) if memory_trace else None,
            )
            session.add_all([user_message, assistant_message])
            chat_session.message_count = (chat_session.message_count or 0) + 2
            chat_session.updated_at = datetime.now(timezone.utc)
            session.flush()
            records = (
                self._message_to_record(user_message),
                self._message_to_record(assistant_message),
            )
            session.commit()
            logger.debug("Message pair saved: %s", session_id)
            return records
        except Exception as exc:
            logger.exception("Failed to save message pair: %s", exc)
            session.rollback()
            raise DatabaseError(f"failed_to_save_message_pair: {exc}") from exc
        finally:
            session.close()

    def get_message_pair_by_turn_idempotency_key(
        self,
        turn_idempotency_key: str,
        *,
        workspace_id: str = "default",
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Load the authoritative chat pair for a committed semantic turn."""
        normalized_turn_key = str(turn_idempotency_key or "").strip()
        if not normalized_turn_key:
            return None
        normalized_workspace_id = self._normalize_workspace_id(workspace_id)
        session = self.SessionLocal()
        try:
            existing = session.query(ChatMessage)\
                .join(ChatSession, ChatSession.id == ChatMessage.session_id)\
                .filter(
                    ChatMessage.turn_idempotency_key == normalized_turn_key,
                    ChatSession.workspace_id == normalized_workspace_id,
                )\
                .order_by(ChatMessage.id.asc())\
                .all()
            if not existing:
                return None
            by_role = {message.role: message for message in existing}
            if "user" not in by_role or "assistant" not in by_role:
                raise DatabaseError(
                    "incomplete_turn_message_pair: existing idempotent turn is partial"
                )
            return (
                self._message_to_record(by_role["user"]),
                self._message_to_record(by_role["assistant"]),
            )
        except DatabaseError:
            raise
        except Exception as exc:
            logger.exception("Failed to load message pair for turn %s", normalized_turn_key)
            raise DatabaseError(f"failed_to_load_turn_message_pair: {exc}") from exc
        finally:
            session.close()

    def get_chat_history(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """获取聊天历史

        Args:
            session_id: 会话 ID
            limit: 返回的最大消息数

        Returns:
            消息列表

        Raises:
            DatabaseError: 查询失败时抛出
        """
        session = self.SessionLocal()
        try:
            messages = session.query(ChatMessage)\
                .filter_by(session_id=session_id)\
                .order_by(ChatMessage.timestamp.asc())\
                .limit(limit)\
                .all()

            records: list[dict[str, Any]] = []
            for message in messages:
                metadata = self._message_to_record(message)
                records.append({
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "timestamp": _isoformat_or_none(message.timestamp),
                    "tokens": message.tokens_used,
                    "model": message.model,
                    **({"agentSteps": metadata["agentSteps"]} if metadata["agentSteps"] else {}),
                    **({"memorySources": metadata["memorySources"]} if metadata["memorySources"] else {}),
                })
            return records
        except Exception as exc:
            logger.exception(f"Failed to get chat history: {exc}")
            raise DatabaseError(f"failed_to_get_chat_history: {exc}") from exc
        finally:
            session.close()

    def update_message_metadata(
        self,
        message_id: int,
        *,
        tool_trace: list[dict[str, Any]] | None = None,
        memory_trace: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        session = self.SessionLocal()
        try:
            message = session.query(ChatMessage).filter_by(id=message_id).first()
            if message is None:
                raise NotFoundError(f"message_not_found: {message_id}")
            if tool_trace is not None:
                message.tool_trace = json.dumps(tool_trace, ensure_ascii=False) if tool_trace else None
            if memory_trace is not None:
                message.memory_trace = json.dumps(memory_trace, ensure_ascii=False) if memory_trace else None
            session.commit()
            return self._message_to_record(message)
        except NotFoundError:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            raise DatabaseError(f"failed_to_update_message_metadata: {exc}") from exc
        finally:
            session.close()

    def clear_memory_references(self, memory_ids: list[str]) -> int:
        target_ids = {str(memory_id).strip() for memory_id in memory_ids if str(memory_id).strip()}
        if not target_ids:
            return 0

        session = self.SessionLocal()
        try:
            changed = 0
            messages = session.query(ChatMessage).filter(ChatMessage.memory_trace.isnot(None)).all()
            for message in messages:
                try:
                    trace = json.loads(message.memory_trace or "[]")
                except (TypeError, ValueError):
                    continue
                if not isinstance(trace, list):
                    continue
                filtered = [
                    source for source in trace
                    if not isinstance(source, dict) or str(source.get("id") or "").strip() not in target_ids
                ]
                if len(filtered) == len(trace):
                    continue
                message.memory_trace = json.dumps(filtered, ensure_ascii=False) if filtered else None
                changed += 1
            session.commit()
            return changed
        except Exception as exc:
            session.rollback()
            raise DatabaseError(f"failed_to_clear_memory_references: {exc}") from exc
        finally:
            session.close()

    def count_memory_references(self, memory_ids: list[str]) -> int:
        """Count messages whose memory trace references any target id."""
        target_ids = {str(memory_id).strip() for memory_id in memory_ids if str(memory_id).strip()}
        if not target_ids:
            return 0

        session = self.SessionLocal()
        try:
            affected = 0
            messages = session.query(ChatMessage).filter(ChatMessage.memory_trace.isnot(None)).all()
            for message in messages:
                try:
                    trace = json.loads(message.memory_trace or "[]")
                except (TypeError, ValueError):
                    continue
                if not isinstance(trace, list):
                    continue
                if any(
                    isinstance(source, dict) and str(source.get("id") or "").strip() in target_ids
                    for source in trace
                ):
                    affected += 1
            return affected
        except Exception as exc:
            raise DatabaseError(f"failed_to_count_memory_references: {exc}") from exc
        finally:
            session.close()

    def get_all_sessions(self) -> list[dict[str, Any]]:
        """获取所有会话

        Returns:
            会话列表

        Raises:
            DatabaseError: 查询失败时抛出
        """
        session = self.SessionLocal()
        try:
            sessions = session.query(ChatSession)\
                .order_by(ChatSession.updated_at.desc())\
                .all()

            return [self._session_to_record(chat_session) for chat_session in sessions]
        except Exception as exc:
            logger.exception(f"Failed to get sessions: {exc}")
            raise DatabaseError(f"failed_to_get_sessions: {exc}") from exc
        finally:
            session.close()

    def get_session_workspace_id(self, session_id: str) -> str:
        """Return the workspace that owns a chat session."""
        session = self.SessionLocal()
        try:
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if not chat_session:
                raise NotFoundError(f"session_not_found: {session_id}")
            return self._normalize_workspace_id(chat_session.workspace_id)
        except NotFoundError:
            raise
        except Exception as exc:
            logger.exception(f"Failed to get session workspace: {exc}")
            raise DatabaseError(f"failed_to_get_session_workspace: {exc}") from exc
        finally:
            session.close()

    def get_message_session_id(self, message_id: int) -> str:
        """Return the session that owns a chat message."""
        session = self.SessionLocal()
        try:
            message = session.query(ChatMessage).filter_by(id=message_id).first()
            if not message:
                raise NotFoundError(f"message_not_found: {message_id}")
            return str(message.session_id)
        except NotFoundError:
            raise
        except Exception as exc:
            logger.exception(f"Failed to get message session: {exc}")
            raise DatabaseError(f"failed_to_get_message_session: {exc}") from exc
        finally:
            session.close()

    def delete_message(self, message_id: int) -> dict[str, Any]:
        """Delete one persisted message and update its parent session counters."""
        session = self.SessionLocal()
        try:
            message = session.query(ChatMessage).filter_by(id=message_id).first()
            if not message:
                raise NotFoundError(f"message_not_found: {message_id}")

            session_id = str(message.session_id)
            removed_tokens = int(message.tokens_used or 0)
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            session.delete(message)
            if chat_session:
                chat_session.message_count = max(0, int(chat_session.message_count or 0) - 1)
                chat_session.total_tokens = max(0, int(chat_session.total_tokens or 0) - removed_tokens)
                chat_session.updated_at = datetime.now(timezone.utc)
            session.commit()
            logger.info("Message deleted: %s", message_id)
            return {"message_id": message_id, "session_id": session_id}
        except NotFoundError:
            session.rollback()
            raise
        except Exception as exc:
            logger.exception(f"Failed to delete message: {exc}")
            session.rollback()
            raise DatabaseError(f"failed_to_delete_message: {exc}") from exc
        finally:
            session.close()

    def update_message(self, message_id: int, content: str) -> dict[str, Any]:
        """Update one persisted message body."""
        session = self.SessionLocal()
        try:
            message = session.query(ChatMessage).filter_by(id=message_id).first()
            if not message:
                raise NotFoundError(f"message_not_found: {message_id}")

            message.content = content
            chat_session = session.query(ChatSession).filter_by(id=message.session_id).first()
            if chat_session:
                chat_session.updated_at = datetime.now(timezone.utc)
            session.commit()
            updated = self._message_to_record(message)
            logger.info("Message updated: %s", message_id)
            return updated
        except NotFoundError:
            session.rollback()
            raise
        except Exception as exc:
            logger.exception(f"Failed to update message: {exc}")
            session.rollback()
            raise DatabaseError(f"failed_to_update_message: {exc}") from exc
        finally:
            session.close()

    def delete_messages_after(self, message_id: int) -> dict[str, Any]:
        """Delete persisted messages after one message in the same session."""
        session = self.SessionLocal()
        try:
            message = session.query(ChatMessage).filter_by(id=message_id).first()
            if not message:
                raise NotFoundError(f"message_not_found: {message_id}")

            session_id = str(message.session_id)
            trailing_messages = session.query(ChatMessage)\
                .filter(ChatMessage.session_id == session_id, ChatMessage.id > message_id)\
                .all()
            deleted_count = len(trailing_messages)
            removed_tokens = sum(int(item.tokens_used or 0) for item in trailing_messages)
            for item in trailing_messages:
                session.delete(item)

            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if chat_session:
                chat_session.message_count = max(0, int(chat_session.message_count or 0) - deleted_count)
                chat_session.total_tokens = max(0, int(chat_session.total_tokens or 0) - removed_tokens)
                chat_session.updated_at = datetime.now(timezone.utc)
            session.commit()
            logger.info("Messages after %s deleted: %s", message_id, deleted_count)
            return {"message_id": message_id, "session_id": session_id, "deleted_count": deleted_count}
        except NotFoundError:
            session.rollback()
            raise
        except Exception as exc:
            logger.exception(f"Failed to delete trailing messages: {exc}")
            session.rollback()
            raise DatabaseError(f"failed_to_delete_trailing_messages: {exc}") from exc
        finally:
            session.close()

    def clear_session_messages(self, session_id: str) -> dict[str, Any]:
        """Delete all messages from a session while keeping the session record."""
        session = self.SessionLocal()
        try:
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if not chat_session:
                raise NotFoundError(f"session_not_found: {session_id}")

            deleted_count = session.query(ChatMessage).filter_by(session_id=session_id).delete(synchronize_session=False)
            chat_session.message_count = 0
            chat_session.total_tokens = 0
            chat_session.updated_at = datetime.now(timezone.utc)
            session.commit()
            logger.info("Session messages cleared: %s (%s messages)", session_id, deleted_count)
            return {"session_id": session_id, "deleted_count": int(deleted_count or 0)}
        except NotFoundError:
            session.rollback()
            raise
        except Exception as exc:
            logger.exception(f"Failed to clear session messages: {exc}")
            session.rollback()
            raise DatabaseError(f"failed_to_clear_session_messages: {exc}") from exc
        finally:
            session.close()

    def delete_session(self, session_id: str) -> None:
        """删除会话及其所有消息

        Args:
            session_id: 会话 ID

        Raises:
            DatabaseError: 删除失败时抛出
        """
        session = self.SessionLocal()
        try:
            # 删除消息
            session.query(ChatMessage).filter_by(session_id=session_id).delete()

            # 删除会话
            session.query(ChatSession).filter_by(id=session_id).delete()

            session.commit()
            logger.info(f"Session deleted: {session_id}")
        except Exception as exc:
            logger.exception(f"Failed to delete session: {exc}")
            session.rollback()
            raise DatabaseError(f"failed_to_delete_session: {exc}") from exc
        finally:
            session.close()

    def get_statistics(self, days: int = 7) -> list[dict[str, Any]]:
        """获取统计数据

        Args:
            days: 获取最近 N 天的数据

        Returns:
            统计数据列表

        Raises:
            DatabaseError: 查询失败时抛出
        """
        session = self.SessionLocal()
        try:
            stats = session.query(UserStatistics)\
                .order_by(UserStatistics.date.desc())\
                .limit(days)\
                .all()

            return [
                {
                    "date": s.date,
                    "messages": s.total_messages,
                    "tokens": s.total_tokens,
                    "avg_response_time": s.avg_response_time,
                    "ocr_count": s.ocr_count,
                    "svc_count": s.svc_count
                }
                for s in reversed(stats)
            ]
        except Exception as exc:
            logger.exception(f"Failed to get statistics: {exc}")
            raise DatabaseError(f"failed_to_get_statistics: {exc}") from exc
        finally:
            session.close()

    def update_daily_statistics(self) -> None:
        """更新每日统计数据

        Raises:
            DatabaseError: 更新失败时抛出
        """
        session = self.SessionLocal()
        try:
            today = datetime.now().strftime("%Y-%m-%d")

            # 统计今日数据
            today_start = datetime.strptime(today, "%Y-%m-%d")
            today_end = today_start + timedelta(days=1)

            total_msgs = session.query(func.count(ChatMessage.id))\
                .filter(ChatMessage.timestamp >= today_start)\
                .filter(ChatMessage.timestamp < today_end)\
                .scalar() or 0

            total_tokens = session.query(func.sum(ChatMessage.tokens_used))\
                .filter(ChatMessage.timestamp >= today_start)\
                .filter(ChatMessage.timestamp < today_end)\
                .scalar() or 0

            # 计算平均响应时间（简化版）
            avg_response_time = 0.0

            # 更新或创建统计记录
            stat = session.query(UserStatistics).filter_by(date=today).first()
            if not stat:
                stat = UserStatistics(date=today)
                session.add(stat)

            stat.total_messages = total_msgs
            stat.total_tokens = total_tokens
            stat.avg_response_time = avg_response_time

            session.commit()
            logger.info(f"Statistics updated for {today}")
        except Exception as exc:
            logger.exception(f"Failed to update statistics: {exc}")
            session.rollback()
            raise DatabaseError(f"failed_to_update_statistics: {exc}") from exc
        finally:
            session.close()

    def export_to_json(self, session_id: str | None = None) -> str:
        """导出为 JSON 格式

        Args:
            session_id: 会话 ID（None 表示导出所有）

        Returns:
            JSON 字符串
        """
        session = self.SessionLocal()
        try:
            if session_id:
                messages = session.query(ChatMessage)\
                    .filter_by(session_id=session_id)\
                    .all()
            else:
                messages = session.query(ChatMessage).all()

            data = [
                {
                    "session_id": m.session_id,
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                    "tokens": m.tokens_used,
                    "model": m.model
                }
                for m in messages
            ]

            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.exception(f"Failed to export JSON: {exc}")
            raise DatabaseError(f"failed_to_export_json: {exc}") from exc
        finally:
            session.close()

    def export_to_csv(self, session_id: str | None = None) -> str:
        """导出为 CSV 格式

        Args:
            session_id: 会话 ID（None 表示导出所有）

        Returns:
            CSV 字符串
        """
        session = self.SessionLocal()
        try:
            if session_id:
                messages = session.query(ChatMessage)\
                    .filter_by(session_id=session_id)\
                    .all()
            else:
                messages = session.query(ChatMessage).all()

            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(["Session ID", "Role", "Content", "Timestamp", "Tokens", "Model"])

            for m in messages:
                writer.writerow([
                    m.session_id,
                    m.role,
                    m.content,
                    m.timestamp.isoformat() if m.timestamp else "",
                    m.tokens_used,
                    m.model or ""
                ])

            return output.getvalue()
        except Exception as exc:
            logger.exception(f"Failed to export CSV: {exc}")
            raise DatabaseError(f"failed_to_export_csv: {exc}") from exc
        finally:
            session.close()

    def save_setting(self, key: str, value: Any) -> None:
        """保存用户设置

        Args:
            key: 设置键
            value: 设置值

        Raises:
            DatabaseError: 保存失败时抛出
        """
        session = self.SessionLocal()
        try:
            setting = session.query(UserSettings).filter_by(key=key).first()
            if not setting:
                setting = UserSettings(key=key)
                session.add(setting)

            setting.value = json.dumps(value) if not isinstance(value, str) else value
            session.commit()
            logger.debug(f"Setting saved: {key}")
        except Exception as exc:
            logger.exception(f"Failed to save setting: {exc}")
            session.rollback()
            raise DatabaseError(f"failed_to_save_setting: {exc}") from exc
        finally:
            session.close()

    def get_setting(self, key: str, default: Any | None = None) -> Any:
        """获取用户设置

        Args:
            key: 设置键
            default: 默认值

        Returns:
            设置值
        """
        session = self.SessionLocal()
        try:
            setting = session.query(UserSettings).filter_by(key=key).first()
            if not setting:
                raise NotFoundError(f"setting_not_found: {key}")

            try:
                raw_value = setting.value
                if raw_value is None:
                    return default
                return json.loads(raw_value)
            except json.JSONDecodeError:
                return setting.value
        except NotFoundError:
            if default is not None:
                return default
            raise
        except Exception as exc:
            logger.exception(f"Failed to get setting: {exc}")
            if default is not None:
                return default
            raise DatabaseError(f"failed_to_get_setting: {exc}") from exc
        finally:
            session.close()

    def get_database_stats(self) -> dict[str, Any]:
        """获取数据库统计信息

        Returns:
            统计信息字典

        Raises:
            DatabaseError: 查询失败时抛出
        """
        session = self.SessionLocal()
        try:
            total_messages = session.query(func.count(ChatMessage.id)).scalar() or 0
            total_sessions = session.query(func.count(ChatSession.id)).scalar() or 0
            total_tokens = session.query(func.sum(ChatMessage.tokens_used)).scalar() or 0

            return {
                "total_messages": total_messages,
                "total_sessions": total_sessions,
                "total_tokens": total_tokens,
                "db_path": str(self.db_path) if self.db_path is not None else None,
                "db_size_mb": (
                    self.db_path.stat().st_size / (1024 * 1024)
                    if self.db_path is not None and self.db_path.exists()
                    else 0
                ),
            }
        except Exception as exc:
            logger.exception(f"Failed to get database stats: {exc}")
            raise DatabaseError(f"failed_to_get_database_stats: {exc}") from exc
        finally:
            session.close()

    # Workspace APIs
    def list_workspaces(self) -> list[dict[str, Any]]:
        session = self.SessionLocal()
        try:
            workspaces = session.query(Workspace).order_by(Workspace.updated_at.desc()).all()
            return [
                {
                    "id": w.id,
                    "name": w.name,
                    "description": w.description,
                    "icon": w.icon,
                    "color": w.color,
                    "companion_profile_id": w.companion_profile_id,
                    "default_model": w.default_model,
                    "system_prompt": w.system_prompt,
                    "tool_preset": w.tool_preset,
                    "memory_scope": w.memory_scope,
                    "mcp_preset_id": w.mcp_preset_id,
                    "created_at": _isoformat_or_none(w.created_at),
                    "updated_at": _isoformat_or_none(w.updated_at),
                }
                for w in workspaces
            ]
        finally:
            session.close()

    def create_workspace(self, workspace_id: str, name: str, description: str | None = None) -> dict[str, Any]:
        session = self.SessionLocal()
        try:
            workspace = Workspace(
                id=workspace_id,
                name=name,
                description=description,
                memory_scope="workspace",
            )
            session.add(workspace)
            session.commit()
            return {
                "id": workspace.id,
                "name": workspace.name,
                "description": workspace.description,
                "icon": workspace.icon,
                "color": workspace.color,
                "companion_profile_id": workspace.companion_profile_id,
                "default_model": workspace.default_model,
                "system_prompt": workspace.system_prompt,
                "tool_preset": workspace.tool_preset,
                "memory_scope": workspace.memory_scope,
                "mcp_preset_id": workspace.mcp_preset_id,
                "created_at": _isoformat_or_none(workspace.created_at),
                "updated_at": _isoformat_or_none(workspace.updated_at),
            }
        except Exception as exc:
            session.rollback()
            raise DatabaseError(f"failed_to_create_workspace: {exc}") from exc
        finally:
            session.close()

    def update_workspace(self, workspace_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        session = self.SessionLocal()
        try:
            workspace = session.query(Workspace).filter_by(id=workspace_id).first()
            if not workspace:
                raise NotFoundError(f"workspace_not_found: {workspace_id}")
            if "companion_profile_id" in updates:
                requested_companion_id = str(updates.get("companion_profile_id") or "default").strip() or "default"
                companion = session.query(Companion).filter_by(id=requested_companion_id).first()
                if not companion:
                    raise DatabaseError(f"invalid_companion_binding: {requested_companion_id}")
                updates["companion_profile_id"] = requested_companion_id
            if "tool_preset" in updates:
                raw_preset = updates["tool_preset"]
                if raw_preset is not None:
                    raw_preset = str(raw_preset).strip()
                    if raw_preset:
                        try:
                            parsed = json.loads(raw_preset)
                            if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                                raise DatabaseError("tool_preset must be a JSON array of tool name strings")
                        except json.JSONDecodeError as exc:
                            raise DatabaseError(f"tool_preset is not valid JSON: {exc}") from exc
                    else:
                        updates["tool_preset"] = None
            if "mcp_preset_id" in updates:
                raw_mcp = updates["mcp_preset_id"]
                if raw_mcp is not None:
                    raw_mcp = str(raw_mcp).strip()
                    if not raw_mcp:
                        updates["mcp_preset_id"] = None
            if "memory_scope" in updates:
                raw_scope = updates["memory_scope"]
                if raw_scope is not None:
                    memory_scope = str(raw_scope).strip()
                    if memory_scope not in {"global", "workspace", "session"}:
                        raise DatabaseError(f"invalid_memory_scope: {memory_scope}")
                    updates["memory_scope"] = memory_scope
            for key in ["name", "description", "icon", "color", "companion_profile_id", "default_model", "system_prompt", "tool_preset", "memory_scope", "mcp_preset_id"]:
                if key in updates:
                    setattr(workspace, key, updates[key])
            workspace.updated_at = datetime.now(timezone.utc)
            session.commit()
            return {
                "id": workspace.id,
                "name": workspace.name,
                "description": workspace.description,
                "icon": workspace.icon,
                "color": workspace.color,
                "companion_profile_id": workspace.companion_profile_id,
                "default_model": workspace.default_model,
                "system_prompt": workspace.system_prompt,
                "tool_preset": workspace.tool_preset,
                "memory_scope": workspace.memory_scope,
                "mcp_preset_id": workspace.mcp_preset_id,
                "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
                "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
            }
        finally:
            session.close()

    def delete_workspace(self, workspace_id: str) -> None:
        session = self.SessionLocal()
        try:
            if workspace_id == "default":
                raise DatabaseError("cannot_delete_default_workspace")
            target = session.query(Workspace).filter_by(id=workspace_id).first()
            if not target:
                raise NotFoundError(f"workspace_not_found: {workspace_id}")
            session.query(ChatSession).filter_by(workspace_id=workspace_id).update({"workspace_id": "default"})
            session.delete(target)
            session.commit()
        except Exception as exc:
            session.rollback()
            raise DatabaseError(f"failed_to_delete_workspace: {exc}") from exc
        finally:
            session.close()

    def list_workspace_sessions(self, workspace_id: str) -> list[dict[str, Any]]:
        session = self.SessionLocal()
        try:
            normalized_workspace_id = self._require_workspace(session, workspace_id)
            query = session.query(ChatSession).filter_by(workspace_id=normalized_workspace_id)
            sessions = query.order_by(ChatSession.pinned.desc(), ChatSession.updated_at.desc()).all()
            return [self._session_to_record(chat_session) for chat_session in sessions]
        finally:
            session.close()

    def create_chat_session(self, workspace_id: str, title: str | None = None) -> dict[str, Any]:
        session = self.SessionLocal()
        try:
            normalized_workspace_id = self._require_workspace(session, workspace_id)
            session_id = f"sess_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
            chat_session = ChatSession(
                id=session_id,
                workspace_id=normalized_workspace_id,
                title=title or f"Chat {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
                pinned=False,
            )
            session.add(chat_session)
            session.commit()
            return self._session_to_record(chat_session)
        except NotFoundError:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            raise DatabaseError(f"failed_to_create_chat_session: {exc}") from exc
        finally:
            session.close()

    def update_chat_session(self, session_id: str, *, summary: str | None = None, pinned: bool | None = None, title: str | None = None, archived: bool | None = None) -> dict[str, Any]:
        session = self.SessionLocal()
        try:
            chat_session = session.query(ChatSession).filter_by(id=session_id).first()
            if not chat_session:
                raise NotFoundError(f"session_not_found: {session_id}")
            if summary is not None:
                chat_session.summary = summary
            if pinned is not None:
                chat_session.pinned = pinned
            if title is not None:
                chat_session.title = title
            if archived is not None:
                chat_session.archived = archived
            chat_session.updated_at = datetime.now(timezone.utc)
            session.commit()
            return self._session_to_record(chat_session)
        finally:
            session.close()

    def branch_chat_session(
        self,
        source_session_id: str,
        message_id: int,
        *,
        title: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        session = self.SessionLocal()
        try:
            source = session.query(ChatSession).filter_by(id=source_session_id).first()
            if not source:
                raise NotFoundError(f"session_not_found: {source_session_id}")
            source_workspace_id = self._normalize_workspace_id(source.workspace_id)
            requested_workspace_id = self._normalize_workspace_id(workspace_id or source_workspace_id)
            if requested_workspace_id != source_workspace_id:
                raise DatabaseError("session_workspace_mismatch")

            branch_point = session.query(ChatMessage).filter_by(id=message_id, session_id=source_session_id).first()
            if not branch_point:
                raise NotFoundError(f"message_not_found_in_session: {message_id}")
            source_messages = session.query(ChatMessage)\
                .filter(ChatMessage.session_id == source_session_id, ChatMessage.id <= message_id)\
                .order_by(ChatMessage.id.asc())\
                .all()

            branch_session = ChatSession(
                id=f"sess_{uuid4().hex[:20]}",
                workspace_id=source_workspace_id,
                title=title or f"{source.title or 'Chat'} branch",
                pinned=False,
                archived=False,
                parent_session_id=source_session_id,
                branched_from_message_id=message_id,
                message_count=len(source_messages),
                total_tokens=sum(int(message.tokens_used or 0) for message in source_messages),
            )
            session.add(branch_session)
            session.flush()
            for message in source_messages:
                session.add(ChatMessage(
                    session_id=branch_session.id,
                    role=message.role,
                    content=message.content,
                    timestamp=message.timestamp,
                    tokens_used=message.tokens_used,
                    model=message.model,
                    tool_trace=message.tool_trace,
                    memory_trace=message.memory_trace,
                ))
            session.commit()
            session.refresh(branch_session)
            return self._session_to_record(branch_session)
        except (NotFoundError, DatabaseError):
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            raise DatabaseError(f"failed_to_branch_chat_session: {exc}") from exc
        finally:
            session.close()

    # Companion APIs
    def _deserialize_voice_profile(self, raw: str | None) -> dict[str, Any] | None:
        if not raw:
            return None
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except Exception:
            return None

    def _serialize_voice_profile(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        return None

    def _companion_to_dict(self, c: Companion) -> dict[str, Any]:
        return {
            "id": c.id,
            "name": c.name,
            "avatar": c.avatar,
            "model_type": c.model_type,
            "model_id": c.model_id,
            "voice_profile": self._deserialize_voice_profile(c.voice_profile),
            "persona_prompt": c.persona_prompt,
            "temperament": c.temperament,
            "attachment_style": c.attachment_style,
            "support_style": c.support_style,
            "emotion_state": c.emotion_state,
            "affinity_state": float(c.affinity_state) if c.affinity_state is not None else 0.5,
            "energy_state": float(c.energy_state) if c.energy_state is not None else 1.0,
            "trust_state": float(c.trust_state) if c.trust_state is not None else 0.5,
            "intimacy_state": float(c.intimacy_state) if c.intimacy_state is not None else 0.5,
            "interruptibility_state": float(c.interruptibility_state) if c.interruptibility_state is not None else 0.75,
            "fatigue_state": float(c.fatigue_state) if c.fatigue_state is not None else 0.0,
            "created_at": _isoformat_or_none(c.created_at),
            "updated_at": _isoformat_or_none(c.updated_at),
        }

    def list_companions(self) -> list[dict[str, Any]]:
        session = self.SessionLocal()
        try:
            companions = session.query(Companion).order_by(Companion.updated_at.desc()).all()
            return [self._companion_to_dict(c) for c in companions]
        finally:
            session.close()

    def get_companion(self, companion_id: str) -> dict[str, Any] | None:
        session = self.SessionLocal()
        try:
            c = session.query(Companion).filter_by(id=companion_id).first()
            return self._companion_to_dict(c) if c else None
        finally:
            session.close()

    def create_companion(self, companion_id: str, name: str, **kwargs: Any) -> dict[str, Any]:
        session = self.SessionLocal()
        try:
            companion = Companion(id=companion_id, name=name)
            for key in ["avatar", "model_type", "model_id", "voice_profile", "persona_prompt", "temperament", "attachment_style", "support_style", "emotion_state", "affinity_state", "energy_state", "trust_state", "intimacy_state", "interruptibility_state", "fatigue_state"]:
                if key in kwargs:
                    setattr(companion, key, self._serialize_voice_profile(kwargs[key]) if key == 'voice_profile' else kwargs[key])
            session.add(companion)
            session.commit()
            return self._companion_to_dict(companion)
        except Exception as exc:
            session.rollback()
            raise DatabaseError(f"failed_to_create_companion: {exc}") from exc
        finally:
            session.close()

    def update_companion(self, companion_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        session = self.SessionLocal()
        try:
            companion = session.query(Companion).filter_by(id=companion_id).first()
            if not companion:
                raise NotFoundError(f"companion_not_found: {companion_id}")
            for key in ["name", "avatar", "model_type", "model_id", "voice_profile", "persona_prompt", "temperament", "attachment_style", "support_style", "emotion_state", "affinity_state", "energy_state", "trust_state", "intimacy_state", "interruptibility_state", "fatigue_state"]:
                if key in updates:
                    setattr(companion, key, self._serialize_voice_profile(updates[key]) if key == 'voice_profile' else updates[key])
            companion.updated_at = datetime.now(timezone.utc)
            session.commit()
            return self._companion_to_dict(companion)
        finally:
            session.close()

    def delete_companion(self, companion_id: str) -> None:
        session = self.SessionLocal()
        try:
            if companion_id == "default":
                raise DatabaseError("cannot_delete_default_companion")
            target = session.query(Companion).filter_by(id=companion_id).first()
            if not target:
                raise NotFoundError(f"companion_not_found: {companion_id}")
            fallback = session.query(Companion).filter_by(id="default").first()
            if not fallback:
                raise DatabaseError("default_companion_missing")
            session.query(Workspace).filter_by(companion_profile_id=companion_id).update({"companion_profile_id": "default"})
            session.delete(target)
            session.commit()
        except Exception as exc:
            session.rollback()
            raise DatabaseError(f"failed_to_delete_companion: {exc}") from exc
        finally:
            session.close()

    def list_workspaces_referencing_companion(self, companion_id: str) -> list[dict[str, Any]]:
        session = self.SessionLocal()
        try:
            workspaces = session.query(Workspace).filter_by(companion_profile_id=companion_id).order_by(Workspace.updated_at.desc()).all()
            return [
                {
                    "id": workspace.id,
                    "name": workspace.name,
                    "updated_at": _isoformat_or_none(workspace.updated_at),
                }
                for workspace in workspaces
            ]
        finally:
            session.close()

    def get_workspace_companion(self, workspace_id: str) -> dict[str, Any] | None:
        session = self.SessionLocal()
        try:
            workspace = session.query(Workspace).filter_by(id=workspace_id).first()
            if not workspace:
                return None
            companion = getattr(workspace, "companion", None)
            if companion is None:
                companion_id = workspace.companion_profile_id or 'default'
                companion = session.query(Companion).filter_by(id=companion_id).first()
            return self._companion_to_dict(companion) if companion else None
        finally:
            session.close()

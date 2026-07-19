from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


DEFAULT_LOG_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 3


def _bounded_env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def install_rotating_file_handler(
    target_logger: logging.Logger,
    log_file: Path,
    *,
    level: int,
    log_format: str,
    max_bytes: int,
    backup_count: int,
) -> RotatingFileHandler:
    target_logger.setLevel(level)
    resolved_log_file = log_file.resolve()
    for handler in list(target_logger.handlers):
        if not isinstance(handler, logging.FileHandler):
            continue
        if Path(handler.baseFilename).resolve() != resolved_log_file:
            continue
        if (
            isinstance(handler, RotatingFileHandler)
            and handler.maxBytes == max_bytes
            and handler.backupCount == backup_count
        ):
            return handler
        target_logger.removeHandler(handler)
        handler.close()

    file_handler = RotatingFileHandler(
        resolved_log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
        errors="backslashreplace",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(log_format))
    target_logger.addHandler(file_handler)
    return file_handler


def configure_application_logging(default_log_file: Path, log_format: str) -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format=log_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    log_file = Path(os.getenv("YUIZAKI_PYTHON_LOG_FILE") or default_log_file)
    max_bytes = _bounded_env_int(
        "YUIZAKI_LOG_MAX_BYTES",
        DEFAULT_LOG_MAX_BYTES,
        minimum=64 * 1024,
        maximum=1024 * 1024 * 1024,
    )
    backup_count = _bounded_env_int(
        "YUIZAKI_LOG_BACKUP_COUNT",
        DEFAULT_LOG_BACKUP_COUNT,
        minimum=1,
        maximum=100,
    )
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        install_rotating_file_handler(
            root_logger,
            log_file,
            level=level,
            log_format=log_format,
            max_bytes=max_bytes,
            backup_count=backup_count,
        )
    except OSError as exc:
        root_logger.warning("Failed to initialize Python file logging: %s", exc)

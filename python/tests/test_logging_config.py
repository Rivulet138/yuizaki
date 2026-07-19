from __future__ import annotations

import logging
from pathlib import Path

from modules.system.logging_config import install_rotating_file_handler


def test_rotating_file_handler_rolls_over_and_is_not_duplicated(tmp_path: Path) -> None:
    logger = logging.getLogger(f"yuizaki.test.rotation.{id(tmp_path)}")
    logger.handlers.clear()
    logger.propagate = False
    log_file = tmp_path / "python.log"

    handler = install_rotating_file_handler(
        logger,
        log_file,
        level=logging.INFO,
        log_format="%(message)s",
        max_bytes=256,
        backup_count=2,
    )
    same_handler = install_rotating_file_handler(
        logger,
        log_file,
        level=logging.INFO,
        log_format="%(message)s",
        max_bytes=256,
        backup_count=2,
    )

    try:
        assert same_handler is handler
        assert len(logger.handlers) == 1
        for index in range(20):
            logger.info("line-%02d %s", index, "x" * 80)
        handler.flush()
        assert log_file.exists()
        assert (tmp_path / "python.log.1").exists()
        assert len(list(tmp_path.glob("python.log*"))) <= 3
    finally:
        logger.removeHandler(handler)
        handler.close()

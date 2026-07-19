from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="yuizaki-pytest-data-"))
os.environ["YUIZAKI_DATA_DIR"] = str(_TEST_DATA_DIR)


def pytest_sessionfinish() -> None:
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)

"""所有測試共用的定位點。"""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def 專案根() -> Path:
    """回傳 repo 根目錄（本檔案的上一層）。"""
    return Path(__file__).resolve().parent.parent

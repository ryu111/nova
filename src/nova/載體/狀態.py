"""狀態路徑：nova 的狀態目錄與跨模組共用路徑。"""

from os import environ
from pathlib import Path


def 狀態根目錄() -> Path:
    """nova 的狀態根目錄。預設 `$XDG_STATE_HOME/nova`，沒設就 `~/.local/state/nova`。"""
    根 = environ.get("XDG_STATE_HOME")
    return (Path(根) if 根 else Path.home() / ".local" / "state") / "nova"

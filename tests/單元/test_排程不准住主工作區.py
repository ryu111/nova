"""排程醒來的時候**不准站在要被巡的那棵樹裡**。

守的就是一格：`排程設定` 印出來的 `WorkingDirectory` 必須是另一份 checkout，
等於 `專案` 或落在 `專案` 底下就當場炸、一個字都不准印。

理由是「壞的時候要還活著」：主工作區正是最容易壞的地方——rebase 到一半、
conflict 沒收、被 `git clean` 掃過。排程站在裡面的話，它跟那棵樹一起壞，
而那正好是最需要它醒著的時刻（收件匣 daemon 跑在主工作區把人鎖在門外過）。

純字串，不碰硬碟，所以住單元層。
"""

import plistlib
from pathlib import Path

import pytest

from nova.載體.排程 import 怎麼跑, 排程設定

_專案 = Path("/Users/someone/nova")
_狀態根 = Path("/Users/someone/.local/state/nova")
_啟動器 = Path("/Users/someone/nova-daemon/.venv/bin/nova-patrol")


def _設定(工作目錄: Path) -> str:
    return 排程設定(
        跑法=怎麼跑(執行檔=_啟動器, 路徑環境="/usr/bin:/bin", 工作目錄=工作目錄),
        專案=_專案,
        狀態根=_狀態根,
        每幾分=15,
    )


def test_工作目錄在專案底下就raise() -> None:
    """工作目錄踩進 `專案` 就不准印；指到另一份 checkout 才印得出來。

    兩格都要擋：**底下的子目錄**（`專案/x`）與**專案自己**。只擋其中一格的話，
    另一格照樣讓排程住在會壞的那棵樹裡。
    """
    with pytest.raises(ValueError, match=str(_專案)):
        _設定(_專案 / "x")

    with pytest.raises(ValueError, match=str(_專案)):
        _設定(_專案)

    daemon = Path("/Users/someone/nova-daemon")
    讀回來 = plistlib.loads(_設定(daemon).encode("utf-8"))

    assert 讀回來["WorkingDirectory"] == str(daemon)

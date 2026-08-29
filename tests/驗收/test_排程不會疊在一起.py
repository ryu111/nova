"""排程一定會踩到的那個坑：**跑太慢的時候，下一次排程會疊上來。**

排程每 15 分鐘叫一次而一輪工作流可能跑 40 分鐘。沒有單例鎖的話，
第 15 分鐘會開第二個、第 30 分鐘第三個——三個一起燒預算、一起改同一份原始碼，
而且看起來完全正常：每一個都在跑，每一個都有帳本。

`收件/處理中/` 擋得住「兩個程序拿到同一件」，擋不住「兩個程序各拿一件同時跑」。

**這一支守的是 CLI 有沒有真的接上那道鎖。** 純函式那一半在
`tests/整合/test_單例.py`，接線壞掉的話那邊照樣全綠。
"""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from nova.載體.單例 import 只准一個
from nova.載體.已處理 import 已處理目錄

nova執行檔 = Path(sys.executable).parent / "nova"
做假CLI型 = Callable[..., tuple[Path, Path]]


def _跑(*參數: str, 狀態: Path, 在: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )


def _鎖在哪(狀態: Path, 專案: Path) -> Path:
    """問 nova 自己鎖在哪——**不要在測試裡重算路徑**。

    重算的話，落點改了測試不會紅，而那正是要守的東西之一。
    """
    os.environ["XDG_STATE_HOME"] = str(狀態)
    try:
        return 已處理目錄(專案).parent / "工作流.鎖"
    finally:
        os.environ.pop("XDG_STATE_HOME", None)


def _做一輪(執行檔: Path, *額外: str, 狀態: Path, 專案: Path) -> subprocess.CompletedProcess[str]:
    return _跑(
        "工作流",
        *額外,
        "--用",
        "claude",
        "--審查用",
        "codex",
        "--執行檔",
        str(執行檔),
        "--工作目錄",
        str(專案),
        "--最多步數",
        "0",
        "--判準",
        "true",
        狀態=狀態,
        在=專案,
    )


def test_排程撞到正在跑的就安靜讓開(tmp_path: Path, 做假CLI: 做假CLI型) -> None:
    """**回 0 不是錯誤碼。**

    排程本來就會在忙的時候醒來。印成錯誤的話，排程的 log 會被永遠不會有人修的
    錯誤塞滿，然後真的錯誤就被淹掉了。
    """
    執行檔, _ = 做假CLI("claude")
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()

    with 只准一個(_鎖在哪(狀態, 專案)):
        跑完 = _做一輪(執行檔, "--從收件匣", 狀態=狀態, 專案=專案)

    assert 跑完.returncode == 0, 跑完.stderr[:300]
    assert "已經有一個在跑了" in 跑完.stderr


def test_人手動下的指令撞到就是真衝突(tmp_path: Path, 做假CLI: 做假CLI型) -> None:
    """**這一半跟上面相反，而且是刻意的。**

    人打了指令卻什麼都沒發生、還回 0，他會以為做完了。
    排程沒有這個問題——它不看回傳值，它看的是下一次還會不會醒來。
    """
    執行檔, _ = 做假CLI("claude")
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()

    with 只准一個(_鎖在哪(狀態, 專案)):
        跑完 = _做一輪(執行檔, "隨便一件事", 狀態=狀態, 專案=專案)

    assert 跑完.returncode == 2, 跑完.stderr[:300]


def test_沒人佔著的時候照常跑(tmp_path: Path, 做假CLI: 做假CLI型) -> None:
    """**這支防的是鎖擋過頭。** 永遠拿不到鎖的話排程等於沒裝。"""
    執行檔, _ = 做假CLI("claude")
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()

    跑完 = _做一輪(執行檔, "隨便一件事", 狀態=狀態, 專案=專案)

    assert 跑完.returncode == 4, 跑完.stderr[:300]

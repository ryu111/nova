"""使用者說的那句話：**「這件工作做完了沒？」**

事件帳本（`nova 帳本`）答的是「花了多少、叫了幾次、走了哪幾階」。
它答不出「做完了沒」——那要從軌跡自己推。成果帳本一次工作一筆，
把收場與退出碼直接寫在帳上。

路線圖上這一格是 `已處理/ 歸檔`，副標「成果帳本」，層是落盤，
上游那條邊來自執行核（`收割 → 歸檔`）。
"""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from nova.契約.工作流 import 結束代碼

nova執行檔 = Path(sys.executable).parent / "nova"
做假CLI型 = Callable[..., tuple[Path, Path]]
_護欄碼 = 4


def _跑(*參數: str, 狀態: Path, 在: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )


def _跑一輪撞護欄的工作流(
    執行檔: Path, *, 狀態: Path, 專案: Path
) -> subprocess.CompletedProcess[str]:
    """`--最多步數 0`：一顆模型都不會叫，所以這條路不燒 token。

    **`--用` 與 `--審查用` 都要明講。** 不給就走派工表，派工表要 `找執行檔`，
    而 CI 沒裝三家 CLI——建角色當場 FileNotFoundError，退出碼會是 2 不是 4。
    本機綠、CI 紅，差別是環境（硬規則 3 的第一層）。這一格是被 CI 教的。

    兩家共用同一支假 CLI 在這裡是安全的：**沒有任何一階會真的叫模型**。
    「執行檔不准誤用到審查那家」那條保證由
    `tests/整合/test_門面.py::test_執行檔不准誤用到審查那家` 守，不在這裡重測。
    """
    return _跑(
        "工作流",
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
        "把某件事做完",
        狀態=狀態,
        在=專案,
    )


def test_工作流跑完之後帳上看得到這次的收場(tmp_path: Path, 做假CLI: 做假CLI型) -> None:
    """撞到護欄停下來也是一種收場，帳上要看得到是「護欄」不是空白。"""
    執行檔, _ = 做假CLI("claude")
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()

    跑完 = _跑一輪撞護欄的工作流(執行檔, 狀態=狀態, 專案=專案)
    assert 跑完.returncode == _護欄碼, 跑完.stderr[:400]

    帳 = _跑("已處理", 狀態=狀態, 在=專案)

    assert 結束代碼.護欄.value in 帳.stdout, 帳.stdout + 帳.stderr
    assert "把某件事做完" in 帳.stdout, 帳.stdout


def test_帳沒有落在工作目錄裡(tmp_path: Path) -> None:
    """**會被拿來當證據的東西，不准放在執行者摸得到的地方。**

    跟進度檔同一條規則：屬於某個專案，不等於存在那個專案裡面。
    斷言看的是 CLI 自己講的落點——沒有紀錄時它會把目錄印出來。
    """
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()

    帳 = _跑("已處理", 狀態=狀態, 在=專案)

    assert str(專案.resolve()) not in 帳.stdout, 帳.stdout
    assert "某個專案" in 帳.stdout, "落點看不出是哪個專案，人就查不動"


def test_成果對得回事件帳本(tmp_path: Path, 做假CLI: 做假CLI型) -> None:
    """成果上的執行識別碼就是事件帳本那個 `<執行識別碼>.jsonl` 的檔名。

    **兩本帳走散了就對不回去**：成果說「護欄停下」，你想知道停之前叫過誰、
    花了多少，就得靠這個識別碼跳過去。各發各的號會讓那一跳斷掉，
    而且斷掉的樣子跟正常一模一樣——兩本帳都在，只是誰也不認識誰。
    """
    執行檔, _ = 做假CLI("claude")
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()

    _跑一輪撞護欄的工作流(執行檔, 狀態=狀態, 專案=專案)

    成果那筆 = _跑("已處理", 狀態=狀態, 在=專案).stdout.split()[0]
    事件帳 = _跑("帳本", 狀態=狀態, 在=專案).stdout

    assert 成果那筆 in 事件帳, f"成果 {成果那筆} 在事件帳本裡找不到：\n{事件帳}"

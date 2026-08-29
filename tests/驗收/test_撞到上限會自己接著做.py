"""使用者說的那句話：**「撞到上限停的，下一次醒來自動接著做；被殺掉的，等我看。」**

這兩種以前長得一模一樣（都是「那件事沒做完」），但它們的**狀態不一樣**：

| 怎麼停的 | 退出碼 | 做到哪知道嗎 | 自動接著做安全嗎 |
|---|---|---|---|
| 撞到步數／預算上限 | 4 | 知道，軌跡是完整的 | **安全** |
| 軌跡裡有一步結果未知 | 3 | **不知道**（可能做了一半） | 不安全，重跑會重做副作用 |
| 角色確定失敗（認證、接線） | 1 | 知道，但環境壞了 | 不安全，接著做只會再壞一次 |
| 做完了 | 0 | — | 沒有東西要接 |

所以判準是**最終退出碼等於 4**，不是「收場分類是護欄」——
`3` 蓋過收場分類（`_工作流退出碼` 的規則），而 3 是「不准重跑」。
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

nova執行檔 = Path(sys.executable).parent / "nova"
做假CLI型 = Callable[..., tuple[Path, Path]]
_護欄碼, _未知碼 = 4, 3


def _跑(*參數: str, 狀態: Path, 在: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def 佈景(tmp_path: Path) -> tuple[Path, Path]:
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()
    return 狀態, 專案


def _敲一次(
    執行檔: Path, 題目: str, *, 狀態: Path, 專案: Path, 多給: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    return _跑(
        "跑",
        題目,
        "--用",
        "claude",
        "--審查用",
        "codex",
        "--執行檔",
        str(執行檔),
        "--最多步數",
        "0",
        "--判準",
        "true",
        *多給,
        狀態=狀態,
        在=專案,
    )


def _醒一次(
    執行檔: Path, *, 狀態: Path, 專案: Path, 多給: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    """排程醒來走的那一條——`工作流 --從收件匣`，沒有別條路。"""
    return _跑(
        "工作流",
        "--從收件匣",
        "--用",
        "claude",
        "--審查用",
        "codex",
        "--執行檔",
        str(執行檔),
        "--最多步數",
        "0",
        "--判準",
        "true",
        *多給,
        狀態=狀態,
        在=專案,
    )


def _收件匣(狀態: Path) -> Path:
    return next((狀態 / "nova" / "專案").glob("*/收件"))


def _等著的(狀態: Path) -> list[Path]:
    return [路 for 路 in _收件匣(狀態).iterdir() if 路.is_file()]


class Test撞到上限會自己接著做:
    def test_排回收件匣等下一次醒來(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        """**排程醒來只撈收件匣**，所以要接著做就得回到收件匣裡。"""
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")

        跑完 = _敲一次(執行檔, "把某件事做完", 狀態=狀態, 專案=專案)

        assert 跑完.returncode == _護欄碼
        assert len(_等著的(狀態)) == 1, "撞到上限之後收件匣應該有一張接續票"

    def test_前情真的餵進下一輪(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        """**接不上的接續等於重跑。** 要證明的是前情進了提示，不是檔案裡有字。"""
        狀態, 專案 = 佈景
        執行檔, 紀錄 = 做假CLI("claude")
        _敲一次(執行檔, "把某件事做完", 狀態=狀態, 專案=專案, 多給=("--最多步數", "1"))

        _醒一次(執行檔, 狀態=狀態, 專案=專案, 多給=("--最多步數", "1"))

        提示 = " ".join(json.loads(紀錄.read_text(encoding="utf-8"))["argv"])
        # **不准只找「前情」兩個字**：`--add-dir` 帶著暫存路徑，而路徑裡有測試名稱
        # ——那兩個字在還沒實作的時候就已經在 argv 裡了（實測，這支一開始是假綠的）。
        assert "前情（上一輪的進度" in 提示, 提示[-600:]
        assert "上一輪撞到上限停下" in 提示, 提示[-600:]

    def test_輪次用完就停下來等你(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        """**沒有上限的自動重排就是成本漏洞**——每 15 分鐘一次，永遠。"""
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")
        _敲一次(執行檔, "永遠做不完的事", 狀態=狀態, 專案=專案)
        for _ in range(10):
            if not _等著的(狀態):
                break
            _醒一次(執行檔, 狀態=狀態, 專案=專案)

        assert _等著的(狀態) == [], "輪次用完之後不該再排"
        assert "接續" in _跑("狀態", 狀態=狀態, 在=專案).stdout


class Test不該接著做的一律不排:
    def test_結果未知不准排回去(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        """**3 是「不知道工作做了沒」。** 自動重排會把可能已經做過的事再做一次。"""
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")
        壞掉的 = 專案.parent / "解不出來.txt"
        壞掉的.write_text("這不是任何一家的 envelope", encoding="utf-8")
        os.environ["NOVA_FAKE_CLAUDE_TRANSCRIPT"] = str(壞掉的)

        跑完 = _敲一次(執行檔, "會解不出來的一件", 狀態=狀態, 專案=專案, 多給=("--最多步數", "1"))

        assert 跑完.returncode == _未知碼, 跑完.stderr[-400:]
        assert _等著的(狀態) == [], "結果未知不准自動接著做"

    def test_你自己敲的不從收件匣來也一樣算(
        self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型
    ) -> None:
        """`nova 跑` 先落成收件檔再走同一條路，**所以它也接得下去**。"""
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")

        跑完 = _敲一次(執行檔, "你敲的一件", 狀態=狀態, 專案=專案)

        assert 跑完.returncode == _護欄碼, 跑完.stderr[-300:]
        票 = _等著的(狀態)
        assert len(票) == 1
        assert "-typed-" in 票[0].name, 票[0].name

"""派一條線 = **往收件匣落一張票，然後當場把它搶下來**。

今天派線走的是 `nova 工作流 --提示檔 <票>`，而那條路不碰收件匣：只有
`--從收件匣` 會走 `收件._搶下來` 的 rename 把票移進 `處理中/`。結果是
**已經在跑的票還躺在收件匣根目錄上**——`nova 收件` 說它「等著」，
排程醒來就再派一次同一件事，而「哪幾張其實已經派過」只有那個對話知道。

這一支釘的就是那個 bug 的反面：`nova 派工 <票檔>` 回來之後，
**那張票不准還留在 `收件/` 根目錄**。rename 是 at-most-once 的所有權宣告，
不是裝飾——少了它，佇列會在無人看管的那一晚把同一件事派上四次。

**票不准用「刪掉」當修法**，所以同時釘它落在 `處理中/` 或 `已處理/`：
所有權宣告的意思是「有人正在做」，不是「這件事消失了」。

住整合層：真的落檔、真的 rename、真的起一條背景線，而 rename 的
at-most-once 只有在真檔案系統上才是真的。
"""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from nova.契約.退出碼 import 護欄碼

nova執行檔 = Path(sys.executable).parent / "nova"
做假CLI型 = Callable[..., tuple[Path, Path]]

#: 一張四欄齊全、帶機械驗收的票。**四欄齊全是刻意的**：`收件._擋下殘缺的自主票`
#: 會把缺欄的自主票擋在開跑前，那條擋人是對的，但不是這一支要測的東西。
票內容 = """# 把某件事做完

## 輸入

`src/nova/載體/收件.py`

## 輸出

一個會動的東西

## 驗收

<!--nova:驗收 true-->

## 停止

做不出來就停下來問人
"""

_指名四支 = (
    "tests/單元/test_甲.py::test_甲",
    "tests/單元/test_乙.py::test_乙",
    "test/整合/test_丙.py::test_丙",
    "tests/驗收/test_丁.py::test_丁",
)
四支指名的票內容 = 票內容 + "\n" + "\n".join(_指名四支) + "\n"


def _跑(*參數: str, 狀態: Path, 在: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )


def _造一個commit的repo(根: Path) -> None:
    """派工要開 worktree，所以工作區得是一個真的 repo。"""

    def git(*指令: str) -> int:
        return subprocess.run(["git", *指令], cwd=根, check=False).returncode

    for 指令 in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "測試@例子"),
        ("config", "user.name", "測試"),
    ):
        assert git(*指令) == 0
    (根 / "讀我.md").write_text("第一版\n", encoding="utf-8")
    assert git("add", "-A") == 0
    assert git("commit", "-q", "-m", "第一版") == 0


def _收件匣(狀態: Path, 專案: Path) -> Path:
    """問 nova 自己收件匣在哪——**不要在測試裡重算一次路徑**。"""
    第一行 = _跑("收件", 狀態=狀態, 在=專案).stdout.splitlines()[0]
    return Path(第一行.removeprefix("收件匣：").strip())


@pytest.fixture
def 佈景(tmp_path: Path) -> tuple[Path, Path]:
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()
    _造一個commit的repo(專案)
    return 狀態, 專案


def test_派出去的票不准留在收件匣根目錄(佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
    """**這是這張票存在的全部理由。**

    留在根目錄的票，`nova 收件` 會說它「等著」，排程下一次醒來就再派一次。
    把 `_搶下來` 那一步拿掉就會紅——負控紀錄裡那一列量的就是這條。
    """
    狀態, 專案 = 佈景
    執行檔, _ = 做假CLI("claude")
    票檔 = 專案 / "票.md"
    票檔.write_text(票內容, encoding="utf-8")

    派完 = _跑(
        "派工",
        str(票檔),
        "--用",
        "claude",
        "--審查用",
        "codex",
        "--執行檔",
        str(執行檔),
        # 一顆模型都不叫，所以這條路不燒 token。
        "--最多步數",
        "0",
        "--判準",
        "true",
        狀態=狀態,
        在=專案,
    )

    assert 派完.returncode == 0, f"派工自己就失敗了：\n{派完.stderr[:600]}"
    匣 = _收件匣(狀態, 專案)
    還等著的 = [路.name for 路 in 匣.iterdir() if 路.is_file()]
    assert not 還等著的, f"票還躺在收件匣根目錄，排程醒來會再派一次：{還等著的}"
    在別處 = [
        *(匣 / "處理中").glob("*"),
        *(匣.parent / "已處理").glob("*.收件"),
    ]
    assert any("把某件事做完" in 路.read_text(encoding="utf-8") for 路 in 在別處), (
        f"票既不在收件匣、也不在 處理中/ 或 已處理/——被刪掉不是修法：{[路.name for 路 in 在別處]}"
    )


@pytest.mark.parametrize("子命令", ("派工", "跑"), ids=("派工入口", "跑入口"))
def test_指名四支測試的票派工收4而且收件匣不留檔(
    佈景: tuple[Path, Path], 做假CLI: 做假CLI型, 子命令: str
) -> None:
    """守派工與跑遇到超過三支指名測試時都回護欄碼，且不落票、不開工作樹。"""
    狀態, 專案 = 佈景
    執行檔, _ = 做假CLI("claude")
    票檔 = 專案 / "票.md"
    票檔.write_text(四支指名的票內容, encoding="utf-8")

    參數 = ("派工", str(票檔)) if 子命令 == "派工" else ("跑", "--提示檔", str(票檔))
    派完 = _跑(
        *參數,
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
        狀態=狀態,
        在=專案,
    )

    assert 派完.returncode == 護欄碼, f"派工未以護欄碼退件：\n{派完.stderr}"
    assert all(一支 in 派完.stderr for 一支 in _指名四支), 派完.stderr
    匣 = _收件匣(狀態, 專案)
    assert not [路 for 路 in 匣.glob("*") if 路.is_file()]
    assert not [路 for 路 in (匣 / "處理中").glob("*") if 路.is_file()]
    assert not list(專案.parent.glob("nova-wt-*"))

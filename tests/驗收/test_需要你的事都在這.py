"""使用者說的那句話：**`nova 狀態` 一眼看得到「需要我處理的事」。**

無人看管跑起來之後，最貴的不是失敗，是**看不出來失敗過**。現在有三種
醒來完全不留痕跡：

| 醒來的結果 | 帳本 | 成果帳 | 看得到嗎 |
|---|---|---|---|
| 做完一件 | 有 | 有 | 看得到 |
| 收件匣是空的 | 無 | 無 | **看不到** |
| 被預算鎖擋下 | 無 | 無 | **看不到** |
| 撞到單例鎖 | 無 | 無 | **看不到** |

前三種是排程醒來的**絕大多數**。所以「排程到底有沒有在跑」這個問題，
今天只能去翻 launchd 的 log——而那份 log 沒有人在看。

## 狀態檔是狀態，不是歷史

**它被覆寫，不是 append。** 歷史已經有兩本了（事件帳本、成果帳），
再開第三本 append-only 的東西只會跟前兩本漂移。狀態檔答的是
**「現在怎麼樣」**：上次醒來是什麼時候、結果是什麼、有幾件卡住了。

跟 `額度/快取.json` 同一種東西——一個給人與狀態列讀的小 JSON。
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from nova.載體.收件 import 待處理

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


def _狀態檔(狀態: Path, 專案: Path) -> dict[str, object]:
    """問 nova 狀態檔在哪，再自己讀——**不要在測試裡重算路徑**。"""
    第一行 = _跑("狀態", 狀態=狀態, 在=專案).stdout.splitlines()[0]
    路徑 = Path(第一行.removeprefix("狀態檔：").strip())
    讀到: dict[str, object] = json.loads(路徑.read_text(encoding="utf-8"))
    return 讀到


class Test每一次醒來都留得下痕跡:
    """**排程醒來的絕大多數不會產生成果**，而那些正是今天完全看不到的。"""

    def test_做完一件之後看得到(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")

        _敲一次(執行檔, "把某件事做完", 狀態=狀態, 專案=專案)

        現在 = _狀態檔(狀態, 專案)
        assert 現在["last_wake_outcome"] == "guardrail"
        assert 現在["last_wake_exit"] == _護欄碼
        assert 現在["last_wake_at"]

    def test_收件匣是空的也要留痕跡(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        """**「排程有沒有在跑」今天只能去翻 launchd 的 log。**

        空收件匣是排程醒來最常見的結果。不記的話，「排程壞掉了」跟
        「排程好好的但沒事做」長得一模一樣。
        """
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")

        _跑(
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
            狀態=狀態,
            在=專案,
        )

        assert _狀態檔(狀態, 專案)["last_wake_outcome"] == "idle"

    def test_被預算鎖擋下要留痕跡(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        """**護欄生效不是壞了，但它要看得見。**

        今天被擋下只留一行 stderr 在 launchd 的 log 裡。看不見的話，
        「排程從昨晚就一直被擋著」會是一個沒有人發現的狀態。
        """
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")
        # **要真的花掉 token**：`--最多步數 0` 一顆模型都不叫，帳上是 0，
        # 而 0 不大於 0——那樣擋不下來，這支測試就變成在測別的東西。
        _敲一次(執行檔, "先花一點 token", 狀態=狀態, 專案=專案, 多給=("--最多步數", "1"))
        花了 = [
            json.loads(路.read_text(encoding="utf-8"))["tokens"]
            for 路 in (狀態 / "nova" / "專案").glob("*/已處理/*.json")
        ]
        assert any(數 > 0 for 數 in 花了), f"沒花到 token，這支測不到預算鎖：{花了}"

        跑完 = _敲一次(執行檔, "這一次要被擋下", 狀態=狀態, 專案=專案, 多給=("--預算token", "1"))

        assert 跑完.returncode == _護欄碼
        現在 = _狀態檔(狀態, 專案)
        assert 現在["last_wake_outcome"] == "budget"
        assert "預算" in str(現在["last_wake_reason"])


class Test需要你的事:
    def test_佇列上還有幾件看得到(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        """**一次只做一件**，所以佇列會累積。累積到幾件是人要知道的事。

        **佇列深度是當場數出來的，不是狀態檔裡的快照**——存快照的話，
        丟五個檔進去狀態檔還說 0，而那比不顯示更糟。
        """
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")
        _敲一次(執行檔, "甲", 狀態=狀態, 專案=專案)
        匣 = next((狀態 / "nova" / "專案").glob("*/收件"))
        # 「甲」撞到上限（`--最多步數 0`），所以它自己留了一張接續票在佇列上。
        # **這裡數的是絕對值，所以要把那張算進去**——寫死 2 的話，
        # 這支會在接續功能上線的那天紅，而紅的理由跟它要守的東西無關。
        本來就有 = len(待處理(匣))
        assert 本來就有 == 1, [路.name for 路 in 待處理(匣)]
        (匣 / "20260830T120000Z-file-乙-aaa.md").write_text("乙", encoding="utf-8")
        (匣 / "20260830T120001Z-file-丙-bbb.md").write_text("丙", encoding="utf-8")

        印出來 = _跑("狀態", 狀態=狀態, 在=專案).stdout

        assert f"佇列上 {本來就有 + 2} 件" in 印出來, 印出來

    def test_沒收尾的算需要你(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        """程序被殺掉會在 `處理中/` 留一件。**不自動放回佇列**（可能做了一半），

        所以它只能靠人來決定——那正是「需要你的事」。
        """
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")
        _敲一次(執行檔, "先跑一次好讓目錄長出來", 狀態=狀態, 專案=專案)
        匣 = next((狀態 / "nova" / "專案").glob("*/收件"))
        (匣 / "處理中").mkdir(parents=True, exist_ok=True)
        (匣 / "處理中" / "999-沒收尾的.md").write_text("做到一半", encoding="utf-8")

        印出來 = _跑("狀態", 狀態=狀態, 在=專案).stdout

        assert "卡住的 1 件" in 印出來, 印出來

    def test_人看得懂的那份也要印出來(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        """JSON 是給狀態列讀的，**人要的是一句話**。"""
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")
        _敲一次(執行檔, "把某件事做完", 狀態=狀態, 專案=專案)

        印出來 = _跑("狀態", 狀態=狀態, 在=專案).stdout

        assert "上次醒來" in 印出來
        assert "護欄" in 印出來


def test_第一次跑的人不會看到錯誤(佈景: tuple[Path, Path]) -> None:
    """**還沒有狀態不是錯誤。** 回非零的話，狀態列會一直閃紅。"""
    狀態, 專案 = 佈景

    跑完 = _跑("狀態", 狀態=狀態, 在=專案)

    assert 跑完.returncode == 0
    assert "還沒" in 跑完.stdout


def test_狀態檔住在專案外面(佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
    """**會被餵回模型的東西，執行者不准碰**——狀態檔是下一輪的判斷依據之一。"""
    狀態, 專案 = 佈景
    執行檔, _ = 做假CLI("claude")
    _敲一次(執行檔, "把某件事做完", 狀態=狀態, 專案=專案)

    第一行 = _跑("狀態", 狀態=狀態, 在=專案).stdout.splitlines()[0]
    路徑 = Path(第一行.removeprefix("狀態檔：").strip())

    assert 專案 not in 路徑.parents

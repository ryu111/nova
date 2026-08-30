"""使用者說的那句話：**「把 shell 直接包進指令，變成高內聚的一部份就不會忘了。」**

## 為什麼這條要存在

2026-08-30 我把兩份研究用 `nohup uv run nova 問 … &` 丟到背景，
**使用者的介面上什麼都看不到**，只能靠我口頭回報「它在跑」。

我的修法是「以後改用 harness 的背景任務功能」——**那是懇求**，而且更糟：
`run_in_background` 是 Claude Code 的功能，換一個 harness 就沒了
（CLAUDE.md：你的邏輯不准住在別人的設定檔裡）。

背景化與可見性要**內聚在 `nova` 自己**：

| | 誰負責 | 換掉 harness 之後 |
|---|---|---|
| `nohup … &` ＋ 口頭回報 | 我記得 | 一樣不見 |
| harness 的背景任務 | Claude Code | **整個消失** |
| **`nova 問 --背景` ＋ `nova 狀態`** | **nova** | **照樣在** |

## 兩件事，缺一不可

1. **`nova 問 --背景`**：指令自己 fork 出去、立刻回、印出識別碼與輸出檔。
   我不必記得加什麼旗標到別人的工具上。
2. **`nova 狀態` 看得到還在跑的**：就算有人真的用 `nohup` 繞過去，
   帳本上「有開始沒有結束」那筆仍然會被看見。**這是兜底的那一層。**
"""

import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

nova執行檔 = Path(sys.executable).parent / "nova"
#: 執行識別碼長什麼樣。**驗值不驗標籤**——標籤可能來自暫存路徑裡的測試名稱。
_像執行識別碼 = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{6}")
做假CLI型 = Callable[..., tuple[Path, Path]]
_慢一點的假CLI = 3.0


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


class Test指令自己會背景化:
    def test_背景跑起來就立刻回(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        """**立刻回**，不然它就不是背景。"""
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")

        跑完 = _跑(
            "問",
            "--用",
            "claude",
            "--執行檔",
            str(執行檔),
            "--背景",
            "在嗎",
            狀態=狀態,
            在=專案,
        )

        assert 跑完.returncode == 0, 跑完.stderr
        # **不要用「花了幾秒」當判準**：假 CLI 快到前景跑也在一秒內結束，
        # 那個斷言分不出好壞（實測過，拿掉背景化它照樣綠）。
        # 分得出來的是：**模型的答案不在父程序的 stdout 上**——
        # 它被導進檔案了，那才是「丟出去了」的證據。
        assert "ok" not in 跑完.stdout, f"答案跑到前景來了，那不是背景：{跑完.stdout!r}"

    def test_印得出識別碼與輸出檔(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        """**印不出去哪找就等於沒派。** 使用者要拿得到那兩個字串。"""
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")

        跑完 = _跑(
            "問",
            "--用",
            "claude",
            "--執行檔",
            str(執行檔),
            "--背景",
            "在嗎",
            狀態=狀態,
            在=專案,
        )

        # **不准只找「識別碼」三個字**：`tmp_path` 的路徑裡有測試名稱，
        # 而這支測試就叫 `test_印得出識別碼與輸出檔`——那三個字在還沒實作的
        # 時候就已經在 stdout 裡了（實測，這支一開始是假綠的）。
        # 要驗的是**值**，不是標籤。
        識別 = 跑完.stdout.split("識別碼：")[1].splitlines()[0].strip()
        assert _像執行識別碼.fullmatch(識別), f"識別碼長得不對：{識別!r}"
        落點 = Path(跑完.stdout.split("輸出寫在：")[1].splitlines()[0].strip())
        assert 落點.is_file(), f"印了輸出檔卻不存在：{落點}"
        assert 落點.stem == 識別, "輸出檔名要就是識別碼，不然人拿著號碼找不到檔"

    def test_印出來的識別碼就是帳本上那個(
        self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型
    ) -> None:
        """**一件事只准有一個號碼。**

        背景那層自己編一個號、帳本另外編一個號的話，使用者拿到的識別碼
        在 `nova 帳本` 上查不到——而那看起來像「帳沒記」，不像「號碼對不上」。
        兩本帳漂移是 nova 自己最不能犯的錯。
        """
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")

        印出來 = _跑(
            "問",
            "--用",
            "claude",
            "--執行檔",
            str(執行檔),
            "--背景",
            "在嗎",
            狀態=狀態,
            在=專案,
        ).stdout
        識別 = 印出來.split("識別碼：")[1].splitlines()[0].strip()
        for _ in range(60):
            帳 = _跑("帳本", 狀態=狀態, 在=專案).stdout
            if 識別 in 帳:
                break
            time.sleep(0.2)

        assert 識別 in 帳, f"帳本上找不到 {識別}\n{帳}"


class Test狀態看得到還在跑的:
    def test_有開始沒結束的會被列出來(self, 佈景: tuple[Path, Path]) -> None:
        """**這是兜底那一層。**

        就算有人用 `nohup` 繞過 `--背景`，帳本上「有 call_started
        沒有 call_finished」那筆照樣看得見。
        """
        狀態, 專案 = 佈景
        # **問 nova 帳本在哪，不要在測試裡重算路徑**——算錯的話這支會
        # 因為「檔案寫到別的地方」而永遠綠，那是最難發現的假綠。
        第一行 = _跑("狀態", 狀態=狀態, 在=專案).stdout.splitlines()[0]
        專案目錄 = Path(第一行.removeprefix("狀態檔：").strip()).parent
        目錄 = 專案目錄 / "帳本"
        目錄.mkdir(parents=True, exist_ok=True)
        # 手工造一筆「發出去了但沒寫下結果」——那正是程序還在跑的樣子
        (目錄 / "20260830T012000Z-abcdef.jsonl").write_text(
            '{"run": "20260830T012000Z-abcdef", "seq": 1, "ts": "2026-08-30T01:20:00.000Z",'
            ' "event": "call_started", "call": 1, "family": "claude",'
            ' "model": "claude-fable-5", "permission": "read-only", "attempt": 1}\n',
            encoding="utf-8",
        )

        印出來 = _跑("狀態", 狀態=狀態, 在=專案).stdout

        assert "還在跑" in 印出來, 印出來
        assert "20260830T012000Z-abcdef" in 印出來, 印出來
        assert "claude" in 印出來, 印出來

    def test_都收尾了就不要吵(self, 佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
        """**沒事就不要印**。每次都印一行「還在跑 0 筆」會讓真的有事那次被忽略。"""
        狀態, 專案 = 佈景
        執行檔, _ = 做假CLI("claude")
        _跑("問", "--用", "claude", "--執行檔", str(執行檔), "在嗎", 狀態=狀態, 在=專案)

        印出來 = _跑("狀態", 狀態=狀態, 在=專案).stdout

        assert "還在跑" not in 印出來, 印出來

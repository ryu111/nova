"""使用者說的那句話：**「把你用錯的方法變成機械化的方式，不然就都只是記憶。」**

2026-08-30 我把長提示直接寫在雙引號字串裡派研究，反引號被 shell 吃掉，
交出一份對著殘缺題目寫的答案。我的第一個修法是寫進記憶——**那是懇求**。

這一支驗的是它變成了殼：**危險的通道對長提示走不通**。
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
_阻擋 = 2


def _跑(*參數: str, 餵: str = "", 在: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        input=餵,
        env={**os.environ, "XDG_STATE_HOME": str(在 / "state")},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def 專案(tmp_path: Path) -> Path:
    (tmp_path / "p").mkdir()
    return tmp_path / "p"


class Test組出來的提示走不了argv:
    def test_多行的當場擋下(self, 專案: Path, 做假CLI: 做假CLI型) -> None:
        """**擋在打出去之前**，不是打出去才發現題目殘缺。

        **一律帶假 CLI**：守衛沒生效的時候，這支測試會一路走到真的模型
        （實測過，六支紅的那次跑了 224 秒還燒了真 token）。
        測試在防護退化時的行為也是行為。
        """
        執行檔, _ = 做假CLI("claude")
        跑完 = _跑("問", "--用", "claude", "--執行檔", str(執行檔), "第一行\n第二行", 在=專案)

        assert 跑完.returncode == _阻擋, 跑完.stdout + 跑完.stderr
        assert "--提示檔" in 跑完.stderr, 跑完.stderr

    def test_太長的當場擋下(self, 專案: Path, 做假CLI: 做假CLI型) -> None:
        執行檔, _ = 做假CLI("claude")
        跑完 = _跑("問", "--用", "claude", "--執行檔", str(執行檔), "很長" * 2000, 在=專案)

        assert 跑完.returncode == _阻擋
        assert "--提示檔" in 跑完.stderr

    def test_人打得出來的照過(self, 專案: Path, 做假CLI: 做假CLI型) -> None:
        """**不能擋到正常用法**——擋過頭的閘會被繞過，繞過一次就等於不存在。"""
        執行檔, _ = 做假CLI("claude")

        跑完 = _跑("問", "--用", "claude", "--執行檔", str(執行檔), "在嗎", 在=專案)

        assert 跑完.returncode == 0, 跑完.stderr


class Test安全的兩條路不受限:
    def test_提示檔多行多長都可以(self, 專案: Path, 做假CLI: 做假CLI型) -> None:
        """檔案不經過 shell 解析，所以沒有那個危險。"""
        執行檔, _ = 做假CLI("claude")
        題 = 專案 / "題目.md"
        題.write_text("第一行\n第二行\n" + "很長" * 2000, encoding="utf-8")

        跑完 = _跑("問", "--用", "claude", "--執行檔", str(執行檔), "--提示檔", str(題), 在=專案)

        assert 跑完.returncode == 0, 跑完.stderr

    def test_提示檔裡的反引號原封不動送出去(self, 專案: Path, 做假CLI: 做假CLI型) -> None:
        """**這就是整條規則存在的理由。**"""
        執行檔, 紀錄 = 做假CLI("claude")
        題 = 專案 / "題目.md"
        題.write_text("請看 `docs/設計/` 底下那幾份", encoding="utf-8")

        _跑("問", "--用", "claude", "--執行檔", str(執行檔), "--提示檔", str(題), 在=專案)

        # **要解 JSON 再看**：紀錄檔是 JSON，非 ASCII 會被逃脫成 \\uXXXX，
        # 直接對字串比會永遠不相等——那樣這支測試在好壞兩種狀態下都紅，
        # 一樣分不出東西。
        送出去的 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"]
        assert any("`docs/設計/`" in 格 for 格 in 送出去的), 送出去的

    def test_stdin多行多長都可以(self, 專案: Path, 做假CLI: 做假CLI型) -> None:
        執行檔, _ = 做假CLI("claude")

        跑完 = _跑(
            "問",
            "--用",
            "claude",
            "--執行檔",
            str(執行檔),
            餵="第一行\n第二行\n" + "很長" * 2000,
            在=專案,
        )

        assert 跑完.returncode == 0, 跑完.stderr


class Test跑跟工作流也受同一條管:
    """**規則只寫一份。** 只擋 `問` 的話，同一個坑會在 `跑` 上重演一次。"""

    def test_跑也擋得住多行(self, 專案: Path, 做假CLI: 做假CLI型) -> None:
        執行檔, _ = 做假CLI("claude")
        跑完 = _跑(
            "跑",
            "--用",
            "claude",
            "--審查用",
            "codex",
            "--執行檔",
            str(執行檔),
            "--最多步數",
            "0",
            "第一行\n第二行",
            在=專案,
        )

        assert 跑完.returncode == _阻擋, 跑完.stdout + 跑完.stderr
        assert "--提示檔" in 跑完.stderr

    def test_工作流也擋得住多行(self, 專案: Path, 做假CLI: 做假CLI型) -> None:
        執行檔, _ = 做假CLI("claude")
        跑完 = _跑(
            "工作流",
            "--用",
            "claude",
            "--審查用",
            "codex",
            "--執行檔",
            str(執行檔),
            "--最多步數",
            "0",
            "第一行\n第二行",
            在=專案,
        )

        assert 跑完.returncode == _阻擋, 跑完.stdout + 跑完.stderr

"""使用者說的那句話：**丟一個檔進去，nova 就會把它做完。**

這是觸發層唯一被設計成「橋」的那一格。做完之後 nova 不必有人坐在終端機前面
也能開始工作——排程到期與 MCP 派票最後都該收斂成「往收件匣丟一個檔」。

**這一支守的是 CLI 有沒有真的接上。** 純函式那一半在 `tests/整合/test_收件.py`，
接線壞掉的話那邊照樣全綠。
"""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

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


def _收件匣(狀態: Path, 專案: Path) -> Path:
    """問 nova 自己收件匣在哪——**不要在測試裡重算一次路徑**。

    重算的話，落點改了測試不會紅，而那正是要守的東西之一。
    """
    第一行 = _跑("收件", 狀態=狀態, 在=專案).stdout.splitlines()[0]
    return Path(第一行.removeprefix("收件匣：").strip())


def _做一輪(執行檔: Path, *, 狀態: Path, 專案: Path) -> subprocess.CompletedProcess[str]:
    """`--最多步數 0` 一顆模型都不會叫，所以這條路不燒 token。

    兩家都要明講：不給就走派工表，派工表要 `找執行檔`，而 CI 沒裝三家 CLI。
    """
    return _跑(
        "工作流",
        "--從收件匣",
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


def test_丟一個檔進去就會被做掉(tmp_path: Path, 做假CLI: 做假CLI型) -> None:
    """而且**做完之後那一件不會再出現在佇列裡**——不然副作用會做第二次。"""
    執行檔, _ = 做假CLI("claude")
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()
    匣 = _收件匣(狀態, 專案)
    匣.mkdir(parents=True, exist_ok=True)
    (匣 / "一件.md").write_text("把某件事做完", encoding="utf-8")

    跑完 = _做一輪(執行檔, 狀態=狀態, 專案=專案)

    assert 跑完.returncode == _護欄碼, 跑完.stderr[:400]
    assert "一件.md" not in _跑("收件", 狀態=狀態, 在=專案).stdout


def test_成果帳上看得到收件匣那一件的內容(tmp_path: Path, 做假CLI: 做假CLI型) -> None:
    """檔案內容就是題目。成果帳上要看得到它，不然對不回是哪一件。"""
    執行檔, _ = 做假CLI("claude")
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()
    匣 = _收件匣(狀態, 專案)
    匣.mkdir(parents=True, exist_ok=True)
    (匣 / "一件.md").write_text("把程序收割做完", encoding="utf-8")

    _做一輪(執行檔, 狀態=狀態, 專案=專案)

    assert "把程序收割做完" in _跑("已處理", 狀態=狀態, 在=專案).stdout


def test_先丟的先做(tmp_path: Path, 做假CLI: 做假CLI型) -> None:
    """**一次只做一件**，而且是最前面那一件。

    一次做完所有的話，一個手滑丟進去的檔案會連著燒掉整批預算。
    """
    執行檔, _ = 做假CLI("claude")
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()
    匣 = _收件匣(狀態, 專案)
    匣.mkdir(parents=True, exist_ok=True)
    (匣 / "20260829-先.md").write_text("先丟的", encoding="utf-8")
    (匣 / "20260830-後.md").write_text("後丟的", encoding="utf-8")

    _做一輪(執行檔, 狀態=狀態, 專案=專案)

    成果 = _跑("已處理", 狀態=狀態, 在=專案).stdout
    assert "先丟的" in 成果
    assert "後丟的" not in 成果, "一次做掉兩件了"
    assert "20260830-後.md" in _跑("收件", 狀態=狀態, 在=專案).stdout


def test_空收件匣是正常狀態不是錯誤(tmp_path: Path, 做假CLI: 做假CLI型) -> None:
    """**回 0 不是 2。**

    排程每小時醒來一次，多數時候收件匣本來就是空的。回錯誤碼的話，
    排程的 log 會被永遠不會有人修的錯誤塞滿，然後真的錯誤就被淹掉了。
    """
    執行檔, _ = 做假CLI("claude")
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()

    跑完 = _做一輪(執行檔, 狀態=狀態, 專案=專案)

    assert 跑完.returncode == 0, 跑完.stderr[:300]
    assert "空的" in 跑完.stderr

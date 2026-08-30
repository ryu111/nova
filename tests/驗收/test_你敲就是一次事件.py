"""使用者說的那句話：**`nova 跑 "做某件事"` 就開始做，而且跟排程走同一條路。**

路線圖觸發層有四格：人在 Claude Code、你敲、時鐘到期、檔案出現。
「檔案出現」那一格的副標寫著**唯一的橋**——意思是另外三格最後都該收斂成
「往收件匣丟一個檔」，不是各自長一條路。

`nova 跑` 於是不是一條新的執行路徑，是**一個把你敲的字變成收件檔的動作**，
然後走 `工作流 --從收件匣`。另開一條的話，預算鎖、祕密載入、判準、單例鎖、
歸檔各會有兩份，而兩份遲早會不一樣——**而且不一樣的那天沒有人會發現**。

## 先落檔再跑，順序是有意義的

排程 15 分鐘一次而一輪可能跑 40 分鐘，所以 `nova 跑` 撞上鎖是常態。
先落檔的話，撞到鎖那一次題目還在佇列上，下一次醒來就做得到；
先搶鎖的話，撞到就整個掉了——**而使用者以為他派出去了**。
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from nova.載體.單例 import 只准一個

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
    """`--最多步數 0` 一顆模型都不會叫，所以這條路不燒 token。"""
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


def _收件匣(狀態: Path, 專案: Path) -> Path:
    """問 nova 自己收件匣在哪——**不要在測試裡重算一次路徑**。"""
    第一行 = _跑("收件", 狀態=狀態, 在=專案).stdout.splitlines()[0]
    return Path(第一行.removeprefix("收件匣：").strip())


def test_敲一句話就會被做掉(佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
    狀態, 專案 = 佈景
    執行檔, _ = 做假CLI("claude")

    跑完 = _敲一次(執行檔, "把某件事做完", 狀態=狀態, 專案=專案)

    assert 跑完.returncode == _護欄碼, 跑完.stderr[:400]
    assert "把某件事做完" in _跑("已處理", 狀態=狀態, 在=專案).stdout


def test_敲的那句話會先變成一個收件檔(佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
    """**檔案是唯一的橋。** 你敲的字要先落成檔案，才跟另外三種事件同形。

    直接把字串傳進工作流也會動，但那就是第二條路徑——
    而佇列上看不到、`ls` 查不到、撞到鎖就整個掉了。
    """
    狀態, 專案 = 佈景
    執行檔, _ = 做假CLI("claude")

    _敲一次(執行檔, "把某件事做完", 狀態=狀態, 專案=專案)

    收在 = list((_收件匣(狀態, 專案).parent / "已處理").glob("*.收件"))
    assert 收在, "沒有任何收件檔被歸檔——那句話沒有走過收件匣"
    assert "把某件事做完" in 收在[0].read_text(encoding="utf-8")


def test_撞到鎖時題目要留在佇列上(佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
    """**先落檔再跑。** 排程 15 分鐘一次而一輪可能跑 40 分鐘，撞到鎖是常態。

    先搶鎖的話，撞到就整個掉了——而使用者以為他派出去了。
    """
    狀態, 專案 = 佈景
    執行檔, _ = 做假CLI("claude")
    # 先把鎖佔住，模擬「排程那一輪還在跑」。
    鎖 = 狀態 / "nova" / "專案"
    _敲一次(執行檔, "先跑一次好讓路徑長出來", 狀態=狀態, 專案=專案)
    鎖檔們 = list(鎖.rglob("工作流.鎖"))
    assert 鎖檔們, "找不到單例鎖——這支測試沒有測到它想測的東西"

    with 只准一個(鎖檔們[0]):
        跑完 = _敲一次(執行檔, "撞到鎖的那一句", 狀態=狀態, 專案=專案)

    assert 跑完.returncode == 2, f"手動撞到鎖是真衝突：\n{跑完.stderr[:300]}"
    等著的 = _跑("收件", 狀態=狀態, 在=專案).stdout
    assert "撞到鎖的那一句" in "".join(
        路.read_text(encoding="utf-8") for 路 in _收件匣(狀態, 專案).iterdir() if 路.is_file()
    ), f"題目掉了：\n{等著的}"


def test_成果上看得出是誰觸發的(佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
    """**四個事件源收斂到同一個入口之後，就分不出是誰敲的了。**

    分不出來的話，「排程昨晚自己跑了什麼」跟「我手動派了什麼」混在同一本帳上，
    而那正是無人看管跑起來之後最需要分開的兩件事。
    """
    狀態, 專案 = 佈景
    執行檔, _ = 做假CLI("claude")

    _敲一次(執行檔, "把某件事做完", 狀態=狀態, 專案=專案)

    成果們 = list((_收件匣(狀態, 專案).parent / "已處理").glob("*.json"))
    assert 成果們
    一筆 = json.loads(成果們[0].read_text(encoding="utf-8"))
    assert 一筆["source"] == "typed", 一筆


def test_手丟的檔案來源是檔案不是你敲(佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
    """**這一支防的是全部都標成你敲。**

    來源是「誰造了這個收件檔」，不是「誰醒來把它撈起來」——
    排程把一個手丟的檔案做掉，那一件的來源仍然是檔案。
    """
    狀態, 專案 = 佈景
    執行檔, _ = 做假CLI("claude")
    匣 = _收件匣(狀態, 專案)
    匣.mkdir(parents=True, exist_ok=True)
    (匣 / "手丟的.md").write_text("我自己丟的", encoding="utf-8")

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

    成果們 = list((匣.parent / "已處理").glob("*.json"))
    assert 成果們
    assert json.loads(成果們[0].read_text(encoding="utf-8"))["source"] == "file"


def test_沒給題目是用法錯誤(佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
    狀態, 專案 = 佈景
    執行檔, _ = 做假CLI("claude")

    跑完 = _跑("跑", "--執行檔", str(執行檔), 狀態=狀態, 在=專案)

    assert 跑完.returncode == 2

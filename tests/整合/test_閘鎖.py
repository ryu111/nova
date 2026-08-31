"""跑閘的時候佔住這台機器。**資源是機器的，不是專案的。**

## 為什麼要跨程序的鎖

`規則表.py` 裡「一次只跑一條」管的是**一個閘內部**的規則順序。
三個 nova 各自開一個閘，那三個 pytest 就同時吃滿 CPU，而誰也不知道誰在跑。

代價不是慢，是**假紅**：`tests/負控/登記.py` 每把刀的 `最多秒` 是 2.0，
執行器用它當 `subprocess.timeout`。機器超載時刀跑不完就被殺，
判成「這把刀沒被殺掉」——一支好好的測試被報成壞的。

`規則表.py` 把平行測試設成吃 3/4 核心，所以兩條同時跑就超過機器容量，
三條是 2.25 倍。**這是算出來的、不是實測的**——寫這一行的時候
三條 nova 都還停在模型呼叫階段，還沒走到跑測試那一步。

## 為什麼鎖檔不能放在專案底下

每個 git worktree 被 nova 當成不同專案
（`~/.local/state/nova/專案/` 底下 `nova-wt-四欄-52dabea7` 自成一格）。
鎖檔跟著專案走的話，三個 worktree 各拿各的鎖——**三把鎖，零保護**，
而且看起來完全正常。

住整合層是因為它真的 fork 子程序才測得出「跨程序」。
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from nova.載體.閘鎖 import 佔住, 等待上限環境變數, 鎖檔路徑


def _搶鎖腳本(鎖目錄: Path, 最多等幾秒: float) -> str:
    return textwrap.dedent(f"""
        import sys
        from pathlib import Path
        from nova.載體.閘鎖 import 佔不到, 佔住
        try:
            with 佔住("閘", 最多等幾秒={最多等幾秒}, 鎖目錄=Path({str(鎖目錄)!r})):
                sys.exit(0)
        except 佔不到:
            sys.exit(9)
    """)


def _跑搶鎖(鎖目錄: Path, 最多等幾秒: float = 0.5) -> int:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", _搶鎖腳本(鎖目錄, 最多等幾秒)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    ).returncode


def test_沒人佔的時候拿得到(tmp_path: Path) -> None:
    assert _跑搶鎖(tmp_path) == 0


def test_有人佔著的時候別的程序拿不到(tmp_path: Path) -> None:
    """**這一支是這個模組存在的理由。**"""
    with 佔住("閘", 鎖目錄=tmp_path):
        assert _跑搶鎖(tmp_path) == 9


def test_放掉之後別人拿得到(tmp_path: Path) -> None:
    """**放不掉的鎖比沒有鎖更糟**：第一次跑完之後所有閘都卡死。

    **這一支登記不進負控**，而且理由本身值得記下來：放鎖靠的是 fd 的生命週期，
    不是任何一行「解鎖」的程式碼。實測把 `LOCK_UN` 與 `handle.close()`
    兩行**都**拿掉，這支測試照樣綠——CPython 的 refcount 在 `佔住` 收尾時
    就把檔案關掉了，而關 fd 就是放鎖。

    所以這裡守的是**行為**（離開 `with` 之後別人拿得到），而那個行為由
    Python 的語意保證，不是由我寫的某一行保證。留著 `handle.close()`
    是為了不依賴那個實作細節，不是因為它現在有在做事。
    """
    with 佔住("閘", 鎖目錄=tmp_path):
        pass
    assert _跑搶鎖(tmp_path) == 0


def test_例外也要放掉(tmp_path: Path) -> None:
    """閘紅是常態，那條路一定會拋例外——不在 finally 裡放鎖就會卡死整台機器。"""
    with pytest.raises(RuntimeError), 佔住("閘", 鎖目錄=tmp_path):
        raise RuntimeError
    assert _跑搶鎖(tmp_path) == 0


def test_不同名稱互不相干(tmp_path: Path) -> None:
    """閘跟別的資源不該互相擋。"""
    with 佔住("別的", 鎖目錄=tmp_path):
        assert _跑搶鎖(tmp_path) == 0


def test_鎖檔路徑不含專案識別() -> None:
    """**資源是機器的，不是專案的。**

    路徑裡出現專案識別的話，三個 worktree 各拿各的鎖——三把鎖，零保護。
    """
    路徑 = 鎖檔路徑("閘")
    assert "專案" not in 路徑.parts
    assert 路徑.name == "閘.lock"


@pytest.mark.serial
def test_有人佔著的時候閘回結果未知而不是閘紅(tmp_path: Path) -> None:
    """**閘沒跑 ≠ 閘紅。**

    回 1 的話「機器很忙」跟「程式壞了」長得一樣，而那兩件事的下一步相反：
    前者要等，後者要修。3 的語意正是「不知道做了沒」。

    `XDG_STATE_HOME` 指到 tmp_path，所以佔的是這次測試專屬的鎖，
    不會卡到別的地方正在跑的閘。
    """
    環境 = {**os.environ, "XDG_STATE_HOME": str(tmp_path), 等待上限環境變數: "1"}
    with 佔住("閘", 鎖目錄=tmp_path / "nova" / "鎖"):
        結果 = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "nova", "閘", "提交"],
            check=False,
            capture_output=True,
            text=True,
            env=環境,
            timeout=120,
        )
    assert 結果.returncode == 3, 結果.stdout + 結果.stderr
    assert "佔不到" in 結果.stderr or "閘沒有跑" in 結果.stderr

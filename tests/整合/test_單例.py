"""排程會踩到的那個坑：**跑太慢的時候，下一次排程會疊上來。**

排程每 15 分鐘叫一次 nova，而一輪工作流可能跑 40 分鐘。沒有單例鎖的話，
第 15 分鐘會開第二個、第 30 分鐘第三個——三個一起燒預算，一起改同一份原始碼。
而且**看起來完全正常**：每一個都在跑，每一個都有帳本。

`處理中/` 擋得住「兩個程序拿到同一件」，擋不住「兩個程序各拿一件同時跑」。
那是兩個不同的問題。

**疊上來不是錯誤。** 排程本來就會在忙的時候醒來，那時候該做的是安靜地讓開，
不是印一個錯誤——排程的 log 被永遠不會有人修的錯誤塞滿，真的錯誤就被淹掉了。

會開檔、會 fork，所以住整合層。
"""

import subprocess
import sys
from pathlib import Path

import pytest

from nova.載體.單例 import 只准一個


def test_拿得到鎖就跑得起來(tmp_path: Path) -> None:
    with 只准一個(tmp_path / "鎖"):
        pass


def test_同一個程序連續拿兩次也可以(tmp_path: Path) -> None:
    """前一個放掉之後，下一個要拿得到——**鎖不准洩漏**。"""
    with 只准一個(tmp_path / "鎖"):
        pass
    with 只准一個(tmp_path / "鎖"):
        pass


def test_鎖檔的目錄不存在會自己建(tmp_path: Path) -> None:
    with 只准一個(tmp_path / "還沒有" / "鎖"):
        pass


def test_另一個程序拿不到(tmp_path: Path) -> None:
    """**這是這一格的全部意義。**

    要真的開第二個程序才測得到——同一個程序裡 `flock` 是可重入的，
    在行程內測會得到假的綠。
    """
    鎖 = tmp_path / "鎖"
    旗 = tmp_path / "第二個的結果"
    腳本 = tmp_path / "第二個.py"
    腳本.write_text(
        f"""
import pathlib, sys
sys.path.insert(0, {str(Path(__file__).resolve().parent.parent.parent / "src")!r})
from nova.載體.單例 import 只准一個, 拿不到鎖
try:
    with 只准一個(pathlib.Path({str(鎖)!r})):
        pathlib.Path({str(旗)!r}).write_text("拿到了")
except 拿不到鎖:
    pathlib.Path({str(旗)!r}).write_text("拿不到")
""",
        encoding="utf-8",
    )

    with 只准一個(鎖):
        subprocess.run([sys.executable, str(腳本)], check=True, timeout=30)

    assert 旗.read_text(encoding="utf-8") == "拿不到"


def test_前一個放掉之後第二個拿得到(tmp_path: Path) -> None:
    """**這支防的是鎖放不掉。** 一個永遠鎖著的鎖會讓排程整個停擺，

    而症狀是「排程好像沒在跑」——那比疊在一起更難查。
    """
    鎖 = tmp_path / "鎖"
    旗 = tmp_path / "第二個的結果"
    腳本 = tmp_path / "第二個.py"
    腳本.write_text(
        f"""
import pathlib, sys
sys.path.insert(0, {str(Path(__file__).resolve().parent.parent.parent / "src")!r})
from nova.載體.單例 import 只准一個, 拿不到鎖
try:
    with 只准一個(pathlib.Path({str(鎖)!r})):
        pathlib.Path({str(旗)!r}).write_text("拿到了")
except 拿不到鎖:
    pathlib.Path({str(旗)!r}).write_text("拿不到")
""",
        encoding="utf-8",
    )

    with 只准一個(鎖):
        pass
    subprocess.run([sys.executable, str(腳本)], check=True, timeout=30)

    assert 旗.read_text(encoding="utf-8") == "拿到了"


def _裡面炸掉(鎖: Path) -> None:
    msg = "裡面炸了"
    with 只准一個(鎖):
        raise RuntimeError(msg)


def test_裡面炸掉鎖也要放掉(tmp_path: Path) -> None:
    """例外不准把鎖帶走——不然一次失敗會讓排程永遠停擺。"""
    鎖 = tmp_path / "鎖"
    with pytest.raises(RuntimeError):
        _裡面炸掉(鎖)

    with 只准一個(鎖):
        pass

"""**墊片證明的是轉遞形狀，不是可達性。**

單元層那幾支用一支叫 `pytest` 的殼腳本測「退出碼怎麼被翻譯」——那證明了映射，
沒證明 **pytest 真的用 5 表達「沒收集到任何測試」**。那個事實住在 pytest 那邊，
它變了我們就會靜默地把環境問題又當成紅。所以這裡真的跑一次 pytest。

放整合層不放單元層：真 pytest 要 fork、秒級。
"""

import subprocess
import sys
from pathlib import Path

from nova.契約.工作流 import 任務, 判準終局
from nova.載體.判準 import 建判準

_真pytest = (sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider")


def test_真pytest在沒有測試的目錄回跑不起來(tmp_path: Path) -> None:
    """**這正是「研究題誤進 TDD 工作流」的形狀**：沒有測試檔，所以永遠收集不到。

    當紅回報的話工作流會回去「再實作一次」，而實作要叫模型——一路燒到
    卡住偵測器第 3 次才停。
    """
    收場, 證據 = 建判準([*_真pytest, str(tmp_path)])(任務(描述="", 工作目錄=tmp_path))

    assert 收場 is 判準終局.跑不起來, 證據
    assert "跑不起來" in 證據


def test_真pytest旗標打錯回跑不起來(tmp_path: Path) -> None:
    """exit 4：改實作一百次也不會讓旗標變對。"""
    收場, 證據 = 建判準([*_真pytest, "--這個旗標不存在"])(任務(描述="", 工作目錄=tmp_path))

    assert 收場 is 判準終局.跑不起來, 證據
    assert "跑不起來" in 證據


def test_真pytest有測試沒過還是紅(tmp_path: Path) -> None:
    """**只改「沒驗到」那兩格。** 真的有測試沒過（exit 1）仍要回去改實作。"""
    (tmp_path / "test_一定紅.py").write_text("def test_紅():\n    assert False\n", encoding="utf-8")

    收場, 證據 = 建判準([*_真pytest, str(tmp_path)])(任務(描述="", 工作目錄=tmp_path))

    assert 收場 is 判準終局.紅, 證據


def test_pytest真的用5表達沒收集到(tmp_path: Path) -> None:
    """把「5 = no tests collected」這個外部事實釘在測試裡，別人改了會當場紅。"""
    結果 = subprocess.run(  # noqa: S603 —— 指令是本檔常數
        [*_真pytest, str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert 結果.returncode == 5, 結果.stdout + 結果.stderr

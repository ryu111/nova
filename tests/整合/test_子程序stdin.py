"""子程序的 stdin 一定要關掉，否則它會坐在那裡等到逾時。

**這支是被一次真實誤診逼出來的。** `gpt-5.6-sol` 兩次跑同一個題目、
兩次都「逾時且 0→0 token」，當時的結論是「題目太大、它想不完」。
錯了——真正的診斷是 codex 的 stderr 那一行：

    Reading additional input from stdin...

`跑cli` 沒給 `stdin`，子程序就繼承父程序的。父程序的 stdin 是一個
沒人會關的管線時（背景腳本、CI、某些 shell），codex 會**卡在讀 stdin**，
一個 token 都不會花，然後被 nova 當成「逾時」殺掉。

**它不是想太久，是根本沒開始。** 兩者長得一模一樣：都是逾時、都是 0 token。

診斷順序（CLAUDE.md 硬規則 6）：環境 → 回饋 → 流程。這是環境那一層。
"""

import subprocess
import sys
from pathlib import Path

import pytest

_子程序腳本 = """
import stat, subprocess, sys
from pathlib import Path
sys.path.insert(0, {src!r})
from nova.載體.模型.執行 import 跑cli

暫存 = Path({暫存!r})
假 = 暫存 / "會讀stdin"
假.write_text(
    "#!" + sys.executable + "\\n"
    "import sys\\n"
    "讀到 = sys.stdin.read()\\n"
    "sys.stdout.write(f'讀到{{len(讀到)}}個字元')\\n",
    encoding="utf-8",
)
假.chmod(假.stat().st_mode | stat.S_IEXEC)
print(跑cli(假, [], 逾時秒=10.0).標準輸出)
"""


@pytest.mark.serial
def test_子程序讀不到父程序的stdin(tmp_path: Path) -> None:
    """父程序的 stdin 有一大堆資料，子程序**一個字元都不該讀到**。

    負控：把 `跑cli` 裡的 `stdin=subprocess.DEVNULL` 拿掉，這支會讀到 6 個字元。

    為什麼要多包一層程序：pytest 自己的 stdin 已經被接管了，
    直接在測試裡跑會「剛好過」——那是測試沒碰到要守的東西，不是保證。
    """
    腳本 = _子程序腳本.format(
        src=str(Path(__file__).resolve().parents[2] / "src"), 暫存=str(tmp_path)
    )
    跑 = subprocess.run(  # noqa: S603
        [sys.executable, "-c", 腳本],
        input="有資料在這裡",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert 跑.returncode == 0, 跑.stderr
    assert "讀到0個字元" in 跑.stdout, f"子程序讀到了父程序的 stdin：{跑.stdout}"

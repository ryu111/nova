"""逾時要把整棵子程序樹殺乾淨，不留孤兒。

**這不是假想的失敗。** 2026-08-30 在本機 `ps -Ao pid,ppid,lstart,ucomm,args`
撈到兩組活著的孤兒，最舊的一組已經活了 21 小時：

    11551     1  8月/29 05:44  uv          uv run pytest tests/單元/test_工作流.py
    11554 11551  8月/29 05:44  python3.13  .venv/bin/pytest tests/單元/test_工作流.py
    52347     1  8月/30 01:15  python3.13  .venv/bin/pytest tests/整合/test_額度命令.py
    52348 52347  8月/30 01:15  python3.13  …/fake-mute-codex app-server

`subprocess.run(timeout=)` 逾時只殺**直接子程序**（CPython 的實作就是
`process.kill()`），孫程序會被 init 收養並繼續活著。nova 叫的每一家 CLI
都會再開自己的子程序，所以「殺子程序」在這裡等於沒殺。

會 fork，所以住整合層不住單元層。
"""

import os
import sys
import time
from pathlib import Path

import pytest

from nova.載體.模型.執行 import 執行逾時, 跑cli

_孫程序睡多久 = 300


def _還活著(pid: int) -> bool:
    """`kill(pid, 0)` 只探測不送訊號。PermissionError 代表它活著但不是我們的。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _等到消失(pid: int, *, 秒: float = 5.0) -> bool:
    """殺完到真的消失之間有空窗（要等 init 收屍），所以用輪詢不用單次斷言。"""
    截止 = time.monotonic() + 秒
    while time.monotonic() < 截止:
        if not _還活著(pid):
            return True
        time.sleep(0.05)
    return not _還活著(pid)


def _寫假cli(路徑: Path, 內文: str) -> Path:
    """假 CLI 用 `sys.executable` 當 shebang，跟本專案的 venv 綁在一起。"""
    路徑.write_text(f"#!{sys.executable}\n{內文}", encoding="utf-8")
    路徑.chmod(0o755)
    return 路徑


def test_逾時要連孫程序一起收掉(tmp_path: Path) -> None:
    """假 CLI 開一個睡很久的孫，然後自己也不回應。逾時之後孫必須也死了。

    孫的 stdout 指向 DEVNULL 是**刻意**的——讓它抓著父程序的管線會另外觸發
    「第二次 communicate 收不到 EOF」那個洞（由下一支測試守），
    兩個混在同一支測試裡會分不出紅的是哪一個。
    """
    孫pid檔 = tmp_path / "孫.pid"
    假cli = _寫假cli(
        tmp_path / "會生孫的假cli",
        f"""
import pathlib, subprocess, sys, time
孫 = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep({_孫程序睡多久})"],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
pathlib.Path({str(孫pid檔)!r}).write_text(str(孫.pid))
sys.stdout.write("孫開好了\\n")
sys.stdout.flush()
time.sleep({_孫程序睡多久})
""",
    )

    with pytest.raises(執行逾時):
        跑cli(假cli, [], 逾時秒=2.0)

    assert 孫pid檔.exists(), "假 CLI 還沒來得及生孫就被殺了，這支測試沒測到東西"
    孫pid = int(孫pid檔.read_text())
    活著 = _等到消失(孫pid)
    if not 活著:
        os.kill(孫pid, 9)  # 測試自己不要留孤兒
    assert 活著, f"孫程序 {孫pid} 逾時後還活著——只殺了直接子程序，沒有收割整棵"


def test_孫程序抓著管線不准讓收屍卡住(tmp_path: Path) -> None:
    """孫程序繼承 stdout 時，殺掉直接子程序不會讓管線 EOF。

    **這一支守的是未來，不是過去。** 量過：`subprocess.run` 在 POSIX 上逾時只做
    `process.wait()`，部分輸出在 `_communicate` 逾時當下就塞進例外了，
    所以舊實作沒有這個洞（實測 1.01 秒）。改成手動 Popen 之後才有：
    在收割後多寫一句沒有時限的 `程序.communicate()`，父程序就會一路等到
    孫自己放掉寫入端為止。

    **負控要兩項一起改才會紅。** 只加那句 `communicate()` 是綠的（實測 1.09 秒）
    ——收割已經把孫殺了，第二次讀立刻拿到 EOF。連 `start_new_session` 一起拿掉
    才紅（實測 4.4 秒）。所以這支測試真正守的是「不准有活著的後代抓著管線」，
    不是「不准再 communicate 一次」。

    孫只睡 4 秒（不是 300 秒），這樣即使紅了也只是慢，不會把測試吊死。
    """
    假cli = _寫假cli(
        tmp_path / "孫抓管線的假cli",
        """
import subprocess, sys, time
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"])
time.sleep(300)
""",
    )

    開始 = time.monotonic()
    with pytest.raises(執行逾時):
        跑cli(假cli, [], 逾時秒=1.0)
    花了 = time.monotonic() - 開始

    assert 花了 < 2.5, f"逾時 1 秒卻花了 {花了:.1f} 秒——被孫程序抓著的管線卡住了"


def test_部分輸出在收割之後仍然撿得回來(tmp_path: Path) -> None:
    """收割的改寫不准把 `執行逾時.部分標準輸出` 弄丟。

    那裡面有 sid，丟掉等於把「接續思考」自己封死（見 `執行逾時` 的 docstring）。
    """
    假cli = _寫假cli(
        tmp_path / "先吐再裝死的假cli",
        """
import sys, time
sys.stdout.write('{"type":"thread.started","thread_id":"t-1"}\\n')
sys.stdout.flush()
time.sleep(300)
""",
    )

    with pytest.raises(執行逾時) as 抓到:
        跑cli(假cli, [], 逾時秒=1.5)

    assert "t-1" in 抓到.value.部分標準輸出

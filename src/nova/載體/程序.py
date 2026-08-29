"""殺子程序要連整棵樹一起殺。

`Popen.kill()` 與 `subprocess.run(timeout=)` 都只送訊號給**直接子程序**，
孫程序會被 init 收養並繼續活著。nova 叫的每一家 CLI 都會再開自己的子程序
（node helper、language server、sandbox），所以「殺子程序」在這裡等於沒殺。

做法是讓子程序自己當一個 process group 的組長（`start_new_session=True`），
之後 `killpg` 就打得到它底下的所有後代。
"""

import contextlib
import os
import signal
import subprocess
from typing import Any

_預設寬限秒 = 0.5
"""SIGTERM 到 SIGKILL 之間留的時間。CLI 拿它寫 session 檔、關 socket。"""


def 收割整棵(程序: subprocess.Popen[Any], *, 寬限秒: float = _預設寬限秒) -> None:
    """把子程序連同它開出來的整棵樹殺乾淨，並收屍避免留 zombie。

    子程序必須是用 `start_new_session=True` 起的——那讓它的 pgid 等於自己的
    pid。**這個相等是安全檢查也是前提**：不相等就代表它跟我們同一組，
    這時候打整組會把 pytest（或 nova 自己）一起殺掉，所以退回只殺它一個。
    """
    可以打整組 = _自成一組(程序.pid)
    _送訊號(程序, signal.SIGTERM, 整組=可以打整組)
    _等一下(程序, 寬限秒)
    # **直接子程序先走不代表整棵都走了。** 組長被收屍之後 pgid 仍然不會被重用
    # （POSIX：process group 的生命週期到最後一個成員離開才結束），
    # 所以這一發補刀打到的一定還是同一組，不會誤傷別人。
    _送訊號(程序, signal.SIGKILL, 整組=可以打整組)
    _等一下(程序, 寬限秒)


def _等一下(程序: subprocess.Popen[Any], 寬限秒: float) -> None:
    """等不到就算了——這裡的職責是收屍，不是保證對方一定死。"""
    with contextlib.suppress(subprocess.TimeoutExpired):
        程序.wait(timeout=寬限秒)


def _自成一組(pid: int) -> bool:
    """它是不是自己那組的組長。已經死掉（含被收屍）時一律回 False。"""
    if pid <= 0:
        return False
    try:
        return os.getpgid(pid) == pid
    except (ProcessLookupError, PermissionError):
        return False


def _送訊號(程序: subprocess.Popen[Any], 訊號: signal.Signals, *, 整組: bool) -> None:
    """整組打不到就退回打單一程序。兩者都可能已經死了，死了不是錯。"""
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        if 整組:
            os.killpg(程序.pid, 訊號)
        elif 訊號 is signal.SIGKILL:
            程序.kill()
        else:
            程序.terminate()

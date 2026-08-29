"""子程序這一層的兩件事：殺得乾淨、看得出是誰。

## 殺得乾淨

`Popen.kill()` 與 `subprocess.run(timeout=)` 都只送訊號給**直接子程序**，
孫程序會被 init 收養並繼續活著。nova 叫的每一家 CLI 都會再開自己的子程序
（node helper、language server、sandbox），所以「殺子程序」在這裡等於沒殺。

做法是讓子程序自己當一個 process group 的組長（`start_new_session=True`），
之後 `killpg` 就打得到它底下的所有後代。

## 看得出是誰

活動監視器上的名字由 kernel 在 exec 當下依執行檔路徑決定，事後改不了。
shebang 腳本一律顯示直譯器的名字，所以 nova 用直譯器的硬連結 `nova-<角色>`
去跑它們。詳見 `具名啟動`。
"""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
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


_命名前綴 = "nova"
_角色字元 = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
_預設角色 = "cli"
_shebang前幾個位元組 = 256


def 具名啟動(執行檔: Path, 參數: Sequence[str]) -> tuple[list[str], str]:
    """組出 argv 與 `APP_ROLE`，讓子程序在活動監視器上看得出是誰。

    活動監視器讀 kernel 的 `p_comm`（等同 `ps -o ucomm`），而**那個名字在 exec
    當下依執行檔路徑決定，事後改不了**。`exec -a` 與 setproctitle 只改得動
    `ps` 的 args 欄，活動監視器完全不看。所以唯一的辦法是拿一個名字對的
    真執行檔去 exec。

    python shebang 腳本（pytest、mypy 這種 console script）→ 改用
    `nova-<角色>` 去跑它，那是直譯器的硬連結。
    真二進位（ruff、agy、codex）→ **原封不動**，它們本來就有自己的名字，
    包一層只會把真名字藏起來。

    角色不當參數收，直接用執行檔的檔名——`pytest`、`mypy`、`claude` 本來就是
    答案，多一個參數只會讓呼叫端有機會傳成不一樣的東西。
    """
    乾淨角色 = _整理角色(執行檔.name)
    環境值 = f"{_命名前綴}.{乾淨角色}"
    直譯器 = _shebang指到的直譯器(執行檔)
    if 直譯器 is None:
        return [str(執行檔), *參數], 環境值
    具名 = _備好具名直譯器(直譯器, 乾淨角色)
    if 具名 is None:
        # 準備不出來（venv 唯讀、跨檔案系統）就照舊跑。
        # **名字沒了比跑不動好**——這一層是可觀測性，不是功能。
        return [str(執行檔), *參數], 環境值
    return [str(具名), str(執行檔), *參數], 環境值


def _整理角色(角色: str) -> str:
    """執行檔名一律小寫 ASCII kebab：CJK 會讓 pkill 與 log 過濾的字串比對出問題。"""
    留下 = "".join(字 for 字 in 角色.lower() if 字 in _角色字元).strip("-")
    return 留下 or _預設角色


def _shebang指到的直譯器(執行檔: Path) -> Path | None:
    """讀第一行看它是不是 python 腳本。不是（或讀不到）就回 None。"""
    try:
        開頭 = 執行檔.open("rb").read(_shebang前幾個位元組)
    except OSError:
        return None
    if not 開頭.startswith(b"#!"):
        return None
    第一行 = 開頭.split(b"\n", 1)[0].decode("utf-8", errors="replace")
    第一個詞 = 第一行[2:].strip().split()[0] if 第一行[2:].strip() else ""
    直譯器 = Path(第一個詞)
    return 直譯器 if _是直譯器(直譯器) else None


def _是直譯器(路徑: Path) -> bool:
    """名字裡有 python，或者它根本就是本程序用的那一支。

    第二個條件不是多餘的：**nova 自己就會把 python 改名**，所以巢狀的時候
    （閘以 `nova-pytest` 在跑，它再開一支工具）shebang 上寫的是 `nova-pytest`，
    只比對 "python" 會整個漏判。實際踩到過，由
    `test_python腳本開出來的子程序在ps上叫得出名字` 在閘裡紅出來。
    """
    if "python" in 路徑.name:
        return True
    with contextlib.suppress(OSError):
        return 路徑.resolve() == Path(sys.executable).resolve()
    return False


def _具名目錄(直譯器: Path) -> Path | None:
    """具名連結一定要跟直譯器**同一個目錄**（`<venv>/bin/`），不准另開一層。

    試過放 `<venv>/程序名/`：`pyvenv.cfg` 照 PEP 405 往上一層找得到，
    `sys.prefix` 也對——**但 `sys.executable` 跟著搬家了**。
    而大量程式碼假設 `Path(sys.executable).parent` 就是 `<venv>/bin`，
    包括 nova 自己的 `規則表._外部指令`（它靠這條找 ruff／mypy／pytest）。
    搬走之後閘找不到工具、退回 PATH、然後 Popen 直接 FileNotFoundError，
    而且每次紅的測試都不一樣，很難查。

    代價是 `<venv>/bin/` 多幾個 `nova-*`。那個目錄本來就是放 console script 的，
    多幾支不會擋到誰；`sys.executable` 搬家會擋到所有人。

    找不到 `pyvenv.cfg`（不是 venv）就回 None：寧可不改名，
    也不要製造一支 import 不到 nova 的直譯器。
    """
    if not (直譯器.parent.parent / "pyvenv.cfg").exists():
        return None
    return 直譯器.parent


def _備好具名直譯器(直譯器: Path, 角色: str) -> Path | None:
    """準備 `<venv>/程序名/nova-<角色>`，是直譯器的硬連結。

    由 `test_改名之後venv還是原來那個` 背書——掉回系統 python 的話
    `import nova` 會整個爆掉，那比沒有名字嚴重得多。
    """
    目錄 = _具名目錄(直譯器)
    if 目錄 is None:
        return None
    目標 = 目錄 / f"{_命名前綴}-{角色}"
    if 目標.exists():
        return 目標
    目錄.mkdir(parents=True, exist_ok=True)
    真檔 = 直譯器.resolve()
    try:
        os.link(真檔, 目標)
    except FileExistsError:
        return 目標  # 兩條閘平行跑時會撞在一起，撞到代表別人做好了
    except OSError:
        try:
            shutil.copy2(真檔, 目標)
        except OSError:
            return None
    return 目標

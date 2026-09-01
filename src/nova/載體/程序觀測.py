"""`nova 線` 的程序清查與狀態觀測。"""

import os
import shlex
import subprocess
from pathlib import Path

from nova.契約.線觀測 import 程序清查, 程序資料

_PS欄位數 = 8
_PS欄位分割數 = 7
_PS命令欄 = 7
_PS_LSTART之前的欄數 = 2  # pid 與 etime


def 找nova程序() -> 程序清查 | None:
    """回傳已定位的程序，以及是否有程序無法定位工作目錄。"""
    try:
        結果 = subprocess.run(  # noqa: S603, S607 —— 只讀取系統程序清單
            ["ps", "-axo", "pid=,etime=,lstart=,command="],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if 結果.returncode != 0:
        return None
    程序們: list[程序資料] = []
    有無法定位 = False
    本身pid = os.getpid()
    for 行 in 結果.stdout.splitlines():
        程序, 未定位 = 解析一行ps(行, 本身pid)
        if 未定位:
            有無法定位 = True
        elif 程序 is not None:
            程序們.append(程序)
    return 程序清查(程序們=程序們, 有無法定位工作目錄的程序=有無法定位)


def 解析一行ps(行: str, 本身pid: int) -> tuple[程序資料 | None, bool]:
    """解析單行 ps 輸出。回傳 (程序資料, 是否未定位)。

    ps -axo pid=,etime=,lstart=,command= 輸出範例：
    12345 01:23:45 Mon Aug 31 00:00:00 2026 /path/to/nova 跑
    欄位分割 7 次得到 8 欄：pid(1) etime(1) lstart(5) command(1)
    """
    欄 = 行.split(None, _PS欄位分割數)
    if len(欄) != _PS欄位數:
        return None, False
    pid原文, 跑多久, 命令原文 = 欄[0], 欄[1], 欄[_PS命令欄]
    try:
        詞 = shlex.split(命令原文)
    except ValueError:
        # 命令列可能有未配對的引號（claude 子程序的提示文就是這樣），
        # 退回純空白切詞，別讓整行掉了。
        詞 = 命令原文.split()
    if not 是nova命令(詞):
        return None, False
    try:
        pid = int(pid原文)
    except ValueError:
        return None, False
    if pid == 本身pid:
        return None, False
    工作目錄 = 命令指定的工作目錄(詞) or _程序工作目錄(pid) or 裝在哪棵樹(詞)
    if 工作目錄 is None:
        return None, True
    程序 = 程序資料(
        工作目錄=工作目錄,
        跑多久=跑多久,
        啟動時間=_lstart原文(行, 命令原文),
    )
    return 程序, False


def _lstart原文(行: str, 命令: str) -> str:
    """從原始那一行裡切出 lstart 那段，連內部空白一起保留。

    `ps` 的 lstart 欄位自己就帶對齊用的空白（`二  9月/ 1 …`），
    先 split 再 join 會把它壓成單一空白，印出來跟 `ps` 看到的不一樣。
    """
    # 呼叫端已確認欄數是 8，這裡一定切得出這一段，而且 `命令` 一定是它的結尾
    lstart與命令 = 行.split(None, _PS_LSTART之前的欄數)[_PS_LSTART之前的欄數]
    return lstart與命令.removesuffix(命令).strip()


def 是nova命令(詞: list[str]) -> bool:
    """判斷這行程序是不是一條 nova 線。

    只認「被執行的那個程式」，不掃整行參數：claude 子程序的命令列裡有
    `--add-dir /Users/sbu/nova` 這種東西，掃整行會把它誤認成一條線。
    """
    if not 詞:
        return False
    第一個 = Path(詞[0]).name
    if _名字是nova(第一個):
        return True
    if 第一個.startswith("python"):
        # `python -m nova …` 與 `…/bin/python3 …/bin/nova 工作流 …` 兩種形狀
        return _接著跑的是nova(詞[1:])
    if 第一個 == "uv" and len(詞) > 1 and 詞[1] == "run":
        # `uv run nova 工作流 …`
        return _接著跑的是nova(詞[2:])
    return False


def _名字是nova(名: str) -> bool:
    return 名 == "nova" or 名.startswith(("nova-", "nova."))


def _接著跑的是nova(其餘: list[str]) -> bool:
    """看前導詞後面第一個實名的詞是不是 nova 本體；看到就下結論，不再往後掃。"""
    for 一詞 in 其餘:
        if 一詞.startswith("-"):  # 跳過 `-m` 這類開關，只看它後面要跑的東西
            continue
        return _名字是nova(Path(一詞).name)
    return False


def 命令指定的工作目錄(詞: list[str]) -> Path | None:
    """從命令列取出明確指定的工作目錄。"""
    for 編號, 一詞 in enumerate(詞):
        if 一詞 == "--工作目錄" and 編號 + 1 < len(詞):
            return Path(詞[編號 + 1]).resolve()
        if 一詞.startswith("--工作目錄="):
            return Path(一詞.split("=", 1)[1]).resolve()
    return None


def 裝在哪棵樹(詞: list[str]) -> Path | None:
    """命令列沒寫 `--工作目錄`、程序又已經不在時，退一步看它是從哪棵樹的 `.venv` 跑的。

    收件匣 daemon 是 `/Users/sbu/nova/.venv/bin/nova-inbox …` 這種形狀，
    裝在哪棵樹的 `.venv` 裡就算在那棵樹上跑。推不出來就回 `None`，維持「查不到」。
    """
    if not 詞:
        return None
    for 上層 in Path(詞[0]).parents:
        if 上層.name == ".venv":
            return 上層.parent.resolve()
    return None


def _程序工作目錄(pid: int) -> Path | None:
    proc = Path(f"/proc/{pid}/cwd")
    try:
        if proc.is_symlink():
            return proc.readlink().resolve()
    except OSError:
        pass
    try:
        結果 = subprocess.run(  # noqa: S603, S607 —— 只讀取程序的 cwd
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if 結果.returncode != 0:
        return None
    for 行 in 結果.stdout.splitlines():
        if 行.startswith("n"):
            return Path(行[1:]).resolve()
    return None


def 這條線的程序(
    工作樹: Path,
    清查: 程序清查 | None,
) -> 程序資料 | None:
    """從程序清查找出對應工作樹的程序。"""
    if 清查 is None:
        return None
    for 程序 in 清查.程序們:
        if 程序.工作目錄 == 工作樹:
            return 程序
    return None


def 是否在跑(
    工作樹: Path,
    清查: 程序清查 | None,
) -> bool | None:
    """判斷工作樹是否正在跑 nova；資料不足時回傳 `None`。"""
    if 清查 is None:
        return None
    if 這條線的程序(工作樹, 清查) is not None:
        return True
    if 清查.有無法定位工作目錄的程序:
        return None
    return False

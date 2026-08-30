"""`nova 線` 的唯讀查詢與排版。"""

import argparse
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from nova.契約.帳本 import 事件種類
from nova.契約.成果 import 成果
from nova.載體.git查詢 import 跑git
from nova.載體.已處理 import 列出成果, 已處理目錄
from nova.載體.帳本 import 預設帳本目錄
from nova.載體.帳本讀取 import 列出執行, 讀原始事件
from nova.載體.狀態檔 import 狀態檔, 讀現況

_PS欄位數 = 8
_PS欄位分割數 = 7
_LSTART欄數 = 5
_成功退出碼 = 0
_確定失敗退出碼 = 1
_結果未知退出碼 = 3
_護欄退出碼 = 4

_退出碼說明 = {
    _成功退出碼: "成功",
    _確定失敗退出碼: "確定失敗",
    _結果未知退出碼: "結果未知（不准重跑）",
    _護欄退出碼: "護欄生效（不是壞了）",
}


@dataclass(frozen=True, slots=True)
class 線資料:
    """一條工作線能從現有來源查到的資料。"""

    名字: str
    在跑嗎: bool | None
    跑多久: str | None
    啟動時間: str | None
    目前階段: str | None
    上一次: 成果 | None
    護欄原因: str | None
    未提交檔案數: int | None
    基底落後數: int | None


@dataclass(frozen=True, slots=True)
class _程序資料:
    """從 `ps` 確認到的一個 nova 程序。"""

    工作目錄: Path
    跑多久: str
    啟動時間: str


@dataclass(frozen=True, slots=True)
class _程序清查:
    """從 `ps` 清查到的 nova 程序與是否有無法定位工作目錄的程序。"""

    程序們: list[_程序資料]
    有無法定位工作目錄的程序: bool


def 查線(專案: Path) -> tuple[線資料, ...]:
    """查詢專案底下所有 worktree；不改工作區、不改任何帳本。"""
    根 = 專案.resolve()
    清查 = _找nova程序()
    工作樹清單 = _工作樹們(根)
    return tuple(_查一條(路徑, 分支, 清查) for 路徑, 分支 in 工作樹清單)


def 排版(線們: tuple[線資料, ...]) -> str:
    """把查詢結果排成給人看的看板。"""
    if not 線們:
        # 防禦性分支：正常情況 _工作樹們 至少回傳專案根目錄
        return "線：查不到（沒有 worktree）\n"
    區塊們 = [
        "\n".join(
            [
                f"線：{線.名字}",
                f"  在跑嗎：{_在跑的人話(線)}",
                f"  跑多久了：{_跑多久的人話(線)}",
                f"  現在在哪一階：{線.目前階段 or '查不到（事件帳本沒有可辨識的階段）'}",
                f"  上一次怎麼收的：{_上一次的人話(線)}",
                f"  工作區乾淨嗎：{_工作區的人話(線)}",
                f"  base 落後幾個 commit：{_基底的人話(線)}",
            ]
        )
        for 線 in 線們
    ]
    return "\n\n".join(區塊們) + "\n"


def 執行線(參數: argparse.Namespace) -> int:
    """把命令列參數交給工作線查詢。"""
    sys.stdout.write(排版(查線(Path(參數.根目錄))))
    return 0


def _查一條(
    工作樹: Path,
    分支: str,
    清查: _程序清查 | None,
) -> 線資料:
    成果們 = 列出成果(已處理目錄(工作樹))
    上一次 = 成果們[0] if 成果們 else None
    程序 = _這條線的程序(工作樹, 清查)
    名字 = 工作樹.name + (f"／{分支}" if 分支 else "")
    return 線資料(
        名字=名字,
        在跑嗎=_是否在跑(工作樹, 清查),
        跑多久=None if 程序 is None else 程序.跑多久,
        啟動時間=None if 程序 is None else 程序.啟動時間,
        目前階段=_目前階段(工作樹),
        上一次=上一次,
        護欄原因=_護欄原因(工作樹, 上一次),
        未提交檔案數=_未提交檔案數(工作樹),
        基底落後數=_基底落後(工作樹),
    )


def _工作樹們(專案: Path) -> list[tuple[Path, str]]:
    結果 = _git(專案, "worktree", "list", "--porcelain")
    if 結果 is None or 結果.returncode != 0:
        return [(專案, "")]
    工作樹清單: list[tuple[Path, str]] = []
    路徑: Path | None = None
    分支 = ""
    for 行 in 結果.stdout.splitlines():
        if 行.startswith("worktree "):
            if 路徑 is not None:
                工作樹清單.append((路徑, 分支))
            路徑 = Path(行.removeprefix("worktree ")).resolve()
            分支 = ""
        elif 行.startswith("branch "):
            分支 = 行.removeprefix("branch refs/heads/")
        elif 行 == "detached":
            分支 = "分離 HEAD"
    if 路徑 is not None:
        工作樹清單.append((路徑, 分支))
    return 工作樹清單 or [(專案, "")]


def _git(根目錄: Path, *參數: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return 跑git(根目錄, *參數)
    except OSError:
        return None


def _找nova程序() -> _程序清查 | None:
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
    程序們: list[_程序資料] = []
    有無法定位 = False
    本身pid = os.getpid()
    for 行 in 結果.stdout.splitlines():
        程序, 未定位 = _解析一行ps(行, 本身pid)
        if 未定位:
            有無法定位 = True
        elif 程序 is not None:
            程序們.append(程序)
    return _程序清查(程序們=程序們, 有無法定位工作目錄的程序=有無法定位)


def _解析一行ps(行: str, 本身pid: int) -> tuple[_程序資料 | None, bool]:
    """解析單行 ps 輸出。回傳 (程序資料, 是否未定位)。

    ps -axo pid=,etime=,lstart=,command= 輸出範例：
    12345 01:23:45 Mon Aug 31 00:00:00 2026 /path/to/nova 跑
    欄位分割 7 次得到 8 欄：pid(1) etime(1) lstart(5) command(1)
    """
    欄 = 行.split(None, _PS欄位分割數)
    if len(欄) != _PS欄位數:
        return None, False
    try:
        詞 = shlex.split(欄[7])
    except ValueError:
        詞 = 欄[7].split()
    if not _是nova命令(詞):
        return None, False
    try:
        pid = int(欄[0])
    except ValueError:
        return None, False
    if pid == 本身pid:
        return None, False
    工作目錄 = _命令指定的工作目錄(詞) or _程序工作目錄(pid)
    if 工作目錄 is None:
        return None, True
    啟動時間 = " ".join(欄[2 : 2 + _LSTART欄數])
    return _程序資料(工作目錄=工作目錄, 跑多久=欄[1], 啟動時間=啟動時間), False


def _是nova命令(詞: list[str]) -> bool:
    if not 詞:
        return False
    第一個 = Path(詞[0]).name
    if 第一個 == "nova" or 第一個.startswith("nova-"):
        return True
    if 第一個.startswith("python"):
        for 編號, 一詞 in enumerate(詞):
            if 一詞 == "-m" and 編號 + 1 < len(詞) and 詞[編號 + 1].startswith("nova"):
                return True
    return False


def _命令指定的工作目錄(詞: list[str]) -> Path | None:
    for 編號, 一詞 in enumerate(詞):
        if 一詞 == "--工作目錄" and 編號 + 1 < len(詞):
            return Path(詞[編號 + 1]).resolve()
        if 一詞.startswith("--工作目錄="):
            return Path(一詞.split("=", 1)[1]).resolve()
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


def _這條線的程序(
    工作樹: Path,
    清查: _程序清查 | None,
) -> _程序資料 | None:
    if 清查 is None:
        return None
    for 程序 in 清查.程序們:
        if 程序.工作目錄 == 工作樹:
            return 程序
    return None


def _是否在跑(
    工作樹: Path,
    清查: _程序清查 | None,
) -> bool | None:
    if 清查 is None:
        return None
    if _這條線的程序(工作樹, 清查) is not None:
        return True
    if 清查.有無法定位工作目錄的程序:
        return None
    return False


def _目前階段(專案: Path) -> str | None:
    """查最近一次執行的目前階段。

    `列出執行` 依時間由新到舊排列。只讀最新一本可讀帳本的階段資訊；
    若該本帳無階段記錄，即代表該次執行未記錄階段，不往舊帳本回溯。
    """
    for 路徑 in 列出執行(預設帳本目錄(專案)):
        try:
            事件們 = 讀原始事件(路徑)
        except OSError:
            continue
        return _這本帳的階段(事件們)
    return None


def _這本帳的階段(事件們: list[dict[str, object]]) -> str | None:
    最後: str | None = None
    開著: dict[int, str] = {}
    for 事 in 事件們:
        階段 = 事.get("stage")
        if not isinstance(階段, str):
            continue
        最後 = 階段
        編號 = 事.get("call")
        if 事.get("event") == 事件種類.階段開始.value and isinstance(編號, int):
            開著[編號] = 階段
        elif 事.get("event") == 事件種類.階段結束.value and isinstance(編號, int):
            開著.pop(編號, None)
    return next(reversed(開著.values())) if 開著 else 最後


def _護欄原因(工作樹: Path, 成果紀錄: 成果 | None) -> str | None:
    if 成果紀錄 is None or 成果紀錄.退出碼 != _護欄退出碼:
        return None
    現況 = 讀現況(狀態檔(工作樹))
    if 現況 is None or 現況.上次執行識別碼 != 成果紀錄.執行識別碼:
        return None
    return 現況.上次理由 or None


def _未提交檔案數(專案: Path) -> int | None:
    結果 = _git(專案, "status", "--porcelain=v1")
    if 結果 is None or 結果.returncode != 0:
        return None
    return len([行 for 行 in 結果.stdout.splitlines() if 行])


def _基底落後(專案: Path) -> int | None:
    基底 = _上游預設分支(專案)
    if 基底 is None:
        return None
    結果 = _git(專案, "rev-list", "--count", f"HEAD..{基底}")
    if 結果 is None or 結果.returncode != 0:
        return None
    try:
        return int(結果.stdout.strip())
    except ValueError:
        return None


def _上游預設分支(專案: Path) -> str | None:
    結果 = _git(專案, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if 結果 is not None and 結果.returncode == 0:
        參照 = 結果.stdout.strip()
        if 參照.startswith("refs/remotes/"):
            return 參照.removeprefix("refs/remotes/")
    return None


def _在跑的人話(線: 線資料) -> str:
    if 線.在跑嗎 is None:
        return "查不到（無法讀取 ps）"
    return "是" if 線.在跑嗎 else "否"


def _跑多久的人話(線: 線資料) -> str:
    if 線.在跑嗎 is None:
        return "查不到（無法確認程序）"
    if 線.在跑嗎 is False:
        return "不適用（目前沒有活著的 nova 程序）"
    return f"{線.跑多久 or '查不到'}（啟動於 {線.啟動時間 or '查不到'}）"


def _上一次的人話(線: 線資料) -> str:
    if 線.上一次 is None:
        return "查不到（沒有成果帳本）"
    碼 = 線.上一次.退出碼
    說法 = _退出碼說明.get(碼, f"查不到（未定義的退出碼 {碼}）")
    if 碼 == _護欄退出碼:
        原因 = 線.護欄原因 or "查不到（現有帳本沒有記錄護欄原因）"
        return f"退出碼 {碼}：{說法}；護欄原因：{原因}"
    return f"退出碼 {碼}：{說法}"


def _工作區的人話(線: 線資料) -> str:
    if 線.未提交檔案數 is None:
        return "查不到（git status 無法讀取）"
    乾淨 = "是" if 線.未提交檔案數 == 0 else "否"
    return f"{乾淨}（{線.未提交檔案數} 個未提交檔案）"


def _基底的人話(線: 線資料) -> str:
    if 線.基底落後數 is None:
        return "查不到（沒有可確認的上游預設分支）"
    return str(線.基底落後數)

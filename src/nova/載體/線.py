"""`nova 線` 的唯讀查詢與排版。"""

import argparse
import os
import shlex
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nova.契約.帳本 import 事件種類
from nova.契約.成果 import 成果
from nova.載體.git查詢 import 跑git
from nova.載體.已處理 import 列出成果, 已處理目錄
from nova.載體.帳本 import 預設帳本目錄
from nova.載體.帳本讀取 import 列出執行, 讀原始事件
from nova.載體.狀態檔 import 狀態檔, 讀現況
from nova.載體.重構護欄 import 不拍的目錄

_PS欄位數 = 8
_PS欄位分割數 = 7
_PS命令欄 = 7
_PS_LSTART之前的欄數 = 2  # pid 與 etime
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


#: 比對用的基底一律是本地這條 ref；查詢不連網，所以它可能是舊的。
_基底參照 = "origin/main"
_基底說明_有 = f"以本地 {_基底參照} 為準（查詢不連網，這份 ref 可能不是最新的）"
_基底說明_無 = f"查不到本地 {_基底參照} 這個 ref，領先／落後留空（不是已同步）"


@dataclass(frozen=True, slots=True)
class 線現況:
    """一條工作線（worktree 或主工作區）的唯讀快照。

    這是一條線唯一的資料入口：程序、階段、成果、基底、mtime 都在這一份裡，
    呼叫端不必再兜第二次查詢。

    算不出來的欄位一律留空（`None`），不准拿 0 頂替——
    「查不到基底」跟「差 0 個 commit」是兩件事。
    """

    名字: str
    在跑嗎: bool | None
    跑多久: str | None
    啟動時間: str | None
    目前階段: str | None
    上一次: 成果 | None
    護欄原因: str | None
    #: 未提交的檔案數。乾不乾淨從這一份衍生，不另外存一份會分歧的布林值。
    未提交檔案數: int | None
    #: 落後基底幾個 commit。這是落後數唯一的存放處，`落後基底數` 由它衍生。
    #: 詞序跟 `領先基底數` 不一致是既有呼叫端綁著的：排版那邊用 `基底落後數` 建構，
    #: 並行查詢那邊跟 `領先基底數` 對稱地讀，兩邊都不在這一格的寫入範圍內。
    基底落後數: int | None
    #: 這條線的工作區路徑；查不到就留空，不拿目前目錄頂替。
    路徑: Path | None = None
    是主工作區: bool = False
    目前commit: str | None = None
    基底參照: str | None = None
    基底說明: str = _基底說明_無
    領先基底數: int | None = None
    最後改動時間: datetime | None = None

    @property
    def 落後基底數(self) -> int | None:
        """`基底落後數` 的唯讀別名，讓呼叫端能跟 `領先基底數` 對稱地讀。"""
        return self.基底落後數

    @property
    def 工作區乾淨嗎(self) -> bool | None:
        """有沒有未提交的改動；數不出來（`未提交檔案數` 留空）時一併留空。"""
        return None if self.未提交檔案數 is None else self.未提交檔案數 == 0


#: 舊名。同一個型別，留著讓既有排版呼叫端不必跟著改。
線資料 = 線現況


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


@dataclass(frozen=True, slots=True)
class _基底比較:
    """一條線跟本地基底 ref 比出來的結果。查不到基底時領先／落後一律留空。"""

    參照: str | None
    說明: str
    領先: int | None
    落後: int | None


#: 比不出來時一律回這一份：領先／落後留空，說明講明是查不到，不是差 0 個。
_查不到基底 = _基底比較(參照=None, 說明=_基底說明_無, 領先=None, 落後=None)


def 查並行現況(專案: Path) -> tuple[線現況, ...]:
    """查專案底下每一條線的現況。唯讀：不 fetch、不 checkout、不動任何工作區。"""
    根 = 專案.resolve()
    清查 = _找nova程序()
    # `git worktree list` 第一筆固定是主工作區，`_工作樹們` 也保證至少回一筆
    (主路徑, 主分支), *其餘工作樹 = _工作樹們(根)
    return (
        _查一條(主路徑, 主分支, 清查, 是主工作區=True),
        *(_查一條(路徑, 分支, 清查, 是主工作區=False) for 路徑, 分支 in 其餘工作樹),
    )


def 排版(線們: tuple[線現況, ...]) -> str:
    """把查詢結果排成給人看的看板。"""
    if not 線們:
        # 防禦性分支：正常情況 _工作樹們 至少回傳專案根目錄
        return "線：查不到（沒有 worktree）\n"
    return "\n\n".join(_一條的區塊(線) for 線 in 線們) + "\n"


def _一條的區塊(線: 線現況) -> str:
    """一條線在看板上的那一段。"""
    return "\n".join(
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


def 執行線(參數: argparse.Namespace) -> int:
    """把命令列參數交給工作線查詢。"""
    sys.stdout.write(排版(查並行現況(Path(參數.根目錄))))
    return 0


def _查一條(
    工作樹: Path,
    分支: str,
    清查: _程序清查 | None,
    *,
    是主工作區: bool,
) -> 線現況:
    成果們 = 列出成果(已處理目錄(工作樹))
    上一次 = 成果們[0] if 成果們 else None
    程序 = _這條線的程序(工作樹, 清查)
    名字 = 工作樹.name + (f"／{分支}" if 分支 else "")
    基底 = _比對基底(工作樹)
    return 線現況(
        名字=名字,
        在跑嗎=_是否在跑(工作樹, 清查),
        跑多久=None if 程序 is None else 程序.跑多久,
        啟動時間=None if 程序 is None else 程序.啟動時間,
        目前階段=_目前階段(工作樹),
        上一次=上一次,
        護欄原因=_護欄原因(工作樹, 上一次),
        未提交檔案數=_未提交檔案數(工作樹),
        基底落後數=基底.落後,
        路徑=工作樹.resolve(),
        是主工作區=是主工作區,
        目前commit=_目前commit(工作樹),
        基底參照=基底.參照,
        基底說明=基底.說明,
        領先基底數=基底.領先,
        最後改動時間=_最後改動時間(工作樹),
    )


def _比對基底(工作樹: Path) -> _基底比較:
    """跟本地基底 ref 比。沒有那條 ref、或數不出來，都當作比不出來。"""
    領先, 落後 = _領先落後(工作樹)
    if 領先 is None or 落後 is None:
        return _查不到基底
    return _基底比較(參照=_基底參照, 說明=_基底說明_有, 領先=領先, 落後=落後)


def _目前commit(工作樹: Path) -> str | None:
    """這條線停在哪個 commit；查不到就留空。

    不用共用的 `git查詢.目前commit`：這支查詢連 git 跑不起來（`OSError`）都要留空收下，
    整條線的其他欄位才不會被一條查不到的 ref 整份炸掉。
    """
    輸出 = _git輸出(工作樹, "rev-parse", "HEAD")
    if 輸出 is None:
        return None
    return 輸出.strip() or None


def _領先落後(工作樹: Path) -> tuple[int | None, int | None]:
    """跟本地 `origin/main` 比。查不到那條 ref 就兩個都留空。

    只下這一道：本地沒有 `origin/main` 時 `rev-list` 自己就會非零退出，
    不必先用 `rev-parse` 探一次——那一道問不出多的事，只是每條線多一次子程序。
    """
    # `HEAD...基底` 的左邊是只有 HEAD 有的（領先），右邊是只有基底有的（落後）
    輸出 = _git輸出(工作樹, "rev-list", "--count", "--left-right", f"HEAD...{_基底參照}")
    if 輸出 is None:
        return None, None
    try:
        領先, 落後 = 輸出.split()
        return int(領先), int(落後)
    except ValueError:
        # `--count --left-right` 應該固定回兩個數字；回不出來就是算不出來，留空
        return None, None


def _最後改動時間(工作樹: Path) -> datetime | None:
    """工作區檔案的最新 mtime；算不出來（走不到任何檔）就留空。"""
    最新 = max(_工作區檔案的mtime們(工作樹), default=None)
    return None if 最新 is None else datetime.fromtimestamp(最新, tz=UTC)


def _工作區檔案的mtime們(工作樹: Path) -> Iterator[float]:
    """走訪工作區檔案的 mtime；`不拍的目錄` 底下的工具產物不算人的改動。"""
    for 目前, 子目錄們, 檔名們 in os.walk(工作樹):
        子目錄們[:] = [名 for 名 in 子目錄們 if 名 not in 不拍的目錄]
        for 檔名 in 檔名們:
            try:
                yield Path(目前, 檔名).stat().st_mtime
            except OSError:
                continue


def _工作樹們(專案: Path) -> list[tuple[Path, str]]:
    輸出 = _git輸出(專案, "worktree", "list", "--porcelain")
    if 輸出 is None:
        return [(專案, "")]
    工作樹清單: list[tuple[Path, str]] = []
    路徑: Path | None = None
    分支 = ""
    for 行 in 輸出.splitlines():
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


def _git輸出(根目錄: Path, *參數: str) -> str | None:
    """跑一道唯讀 git 並回傳 stdout；跑不起來或非零退出碼一律回 `None`（＝算不出來）。"""
    try:
        結果 = 跑git(根目錄, *參數)
    except OSError:
        return None
    if 結果.returncode != 0:
        return None
    return 結果.stdout


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
    pid原文, 跑多久, 命令原文 = 欄[0], 欄[1], 欄[_PS命令欄]
    try:
        詞 = shlex.split(命令原文)
    except ValueError:
        # 命令列可能有未配對的引號（claude 子程序的提示文就是這樣），
        # 退回純空白切詞，別讓整行掉了。
        詞 = 命令原文.split()
    if not _是nova命令(詞):
        return None, False
    try:
        pid = int(pid原文)
    except ValueError:
        return None, False
    if pid == 本身pid:
        return None, False
    工作目錄 = _命令指定的工作目錄(詞) or _程序工作目錄(pid) or _裝在哪棵樹(詞)
    if 工作目錄 is None:
        return None, True
    程序 = _程序資料(
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


def _是nova命令(詞: list[str]) -> bool:
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


def _命令指定的工作目錄(詞: list[str]) -> Path | None:
    for 編號, 一詞 in enumerate(詞):
        if 一詞 == "--工作目錄" and 編號 + 1 < len(詞):
            return Path(詞[編號 + 1]).resolve()
        if 一詞.startswith("--工作目錄="):
            return Path(一詞.split("=", 1)[1]).resolve()
    return None


def _裝在哪棵樹(詞: list[str]) -> Path | None:
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
    輸出 = _git輸出(專案, "status", "--porcelain=v1")
    if 輸出 is None:
        return None
    return len([行 for 行 in 輸出.splitlines() if 行])


def _在跑的人話(線: 線現況) -> str:
    if 線.在跑嗎 is None:
        return "查不到（無法讀取 ps）"
    return "是" if 線.在跑嗎 else "否"


def _跑多久的人話(線: 線現況) -> str:
    if 線.在跑嗎 is None:
        return "查不到（無法確認程序）"
    if 線.在跑嗎 is False:
        return "不適用（目前沒有活著的 nova 程序）"
    return f"{線.跑多久 or '查不到'}（啟動於 {線.啟動時間 or '查不到'}）"


def _上一次的人話(線: 線現況) -> str:
    if 線.上一次 is None:
        return "查不到（沒有成果帳本）"
    碼 = 線.上一次.退出碼
    說法 = _退出碼說明.get(碼, f"查不到（未定義的退出碼 {碼}）")
    if 碼 == _護欄退出碼:
        原因 = 線.護欄原因 or "查不到（現有帳本沒有記錄護欄原因）"
        return f"退出碼 {碼}：{說法}；護欄原因：{原因}"
    return f"退出碼 {碼}：{說法}"


def _工作區的人話(線: 線現況) -> str:
    if 線.未提交檔案數 is None:
        return "查不到（git status 無法讀取）"
    乾淨 = "是" if 線.未提交檔案數 == 0 else "否"
    return f"{乾淨}（{線.未提交檔案數} 個未提交檔案）"


def _基底的人話(線: 線現況) -> str:
    if 線.基底落後數 is None:
        return "查不到（沒有可確認的上游預設分支）"
    return str(線.基底落後數)

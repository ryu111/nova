"""`nova 線` 的工作樹與 git 狀態觀測。"""

import os
from collections.abc import Collection, Iterator
from datetime import UTC, datetime
from pathlib import Path

from nova.契約.線觀測 import _基底參照, _基底說明_有, 基底比較, 查不到基底
from nova.載體.git查詢 import 跑git
from nova.載體.重構護欄 import 不拍的目錄


def 工作樹們(專案: Path) -> list[tuple[Path, str]]:
    """列出專案的主工作區與附加 worktree。"""
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


def 比對基底(工作樹: Path) -> 基底比較:
    """跟本地基底 ref 比。沒有那條 ref、或數不出來，都當作比不出來。"""
    領先, 落後 = 領先落後(工作樹)
    if 領先 is None or 落後 is None:
        return 查不到基底
    return 基底比較(參照=_基底參照, 說明=_基底說明_有, 領先=領先, 落後=落後)


def 目前commit(工作樹: Path) -> str | None:
    """這條線停在哪個 commit；查不到就留空。

    不用共用的 `git查詢.目前commit`：這支查詢連 git 跑不起來（`OSError`）都要留空收下，
    整條線的其他欄位才不會被一條查不到的 ref 整份炸掉。
    """
    輸出 = _git輸出(工作樹, "rev-parse", "HEAD")
    if 輸出 is None:
        return None
    return 輸出.strip() or None


def 領先落後(工作樹: Path) -> tuple[int | None, int | None]:
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


def 最後改動時間(
    工作樹: Path,
    排除目錄: Collection[str] | None = None,
) -> datetime | None:
    """工作區檔案的最新 mtime；算不出來（走不到任何檔）就留空。"""
    最新 = max(_工作區檔案的mtime們(工作樹, 排除目錄), default=None)
    return None if 最新 is None else datetime.fromtimestamp(最新, tz=UTC)


def _工作區檔案的mtime們(
    工作樹: Path,
    排除目錄: Collection[str] | None = None,
) -> Iterator[float]:
    """走訪工作區檔案的 mtime；`不拍的目錄` 底下的工具產物不算人的改動。"""
    不拍 = 不拍的目錄 if 排除目錄 is None else 排除目錄
    for 目前, 子目錄們, 檔名們 in os.walk(工作樹):
        子目錄們[:] = [名 for 名 in 子目錄們 if 名 not in 不拍]
        for 檔名 in 檔名們:
            try:
                yield Path(目前, 檔名).stat().st_mtime
            except OSError:
                continue


def 未提交檔案數(專案: Path) -> int | None:
    """回傳專案的未提交檔案數；無法查詢時回傳 `None`。"""
    輸出 = _git輸出(專案, "status", "--porcelain=v1")
    if 輸出 is None:
        return None
    return len([行 for 行 in 輸出.splitlines() if 行])


def _git輸出(根目錄: Path, *參數: str) -> str | None:
    """跑一道唯讀 git 並回傳 stdout；跑不起來或非零退出碼一律回 `None`（＝算不出來）。"""
    try:
        結果 = 跑git(根目錄, *參數)
    except OSError:
        return None
    if 結果.returncode != 0:
        return None
    return 結果.stdout

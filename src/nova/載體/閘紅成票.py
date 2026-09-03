"""把符合條件的閘紅落成收件匣裡的一張票。

只收「權威 repo 的 main、由排程喚醒、而且確定閘紅」：工作樹的紅是 TDD
正常狀態，手動與 CI 也各有自己的回饋管道；把它們都丟進收件匣只會淹掉真正
需要下一輪處理的問題。

## 這張票的驗收是「那個閘要轉綠」

`丟一件` 對自主來源要求機械驗收（`載體/收件.py` 的 `要驗收嗎`），
而閘紅票的驗收剛好不必發明：**紅的是哪個閘，驗收就是那個閘**。

少了這一行，這張票沒有停止條件——修到模型自己說好了為止，
而那正是硬規則第 2 條擋的東西。
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, Unpack

from nova.契約.檢查結果 import 檢查結果
from nova.契約.觸發 import 喚醒來源 as 喚醒來源契約
from nova.載體.git查詢 import 跑git
from nova.載體.收件 import 丟一件, 收件匣與處理中的票, 收件目錄, 時鐘


@dataclass(frozen=True, slots=True)
class 閘紅現場:
    """一張閘紅票需要的追查事實。"""

    閘點: str
    分支: str
    權威repo: bool
    喚醒來源: 喚醒來源契約
    commit: str
    發生時間: str


class 閘紅現場欄位(TypedDict, total=False):
    """直接傳欄位時的現場資料。"""

    閘點: str
    分支: str
    權威repo: bool
    喚醒來源: 喚醒來源契約 | str
    commit: str
    發生時間: str


def 建閘紅現場(專案: Path, *, 閘點: str, 喚醒來源: 喚醒來源契約 | str) -> 閘紅現場:
    """從目前 repo 讀出閘紅票的現場事實。讀不到 git 就讓權威判定失敗。"""
    git目錄 = _git輸出(專案, "rev-parse", "--git-dir")
    共用git目錄 = _git輸出(專案, "rev-parse", "--git-common-dir")
    權威repo = bool(
        git目錄 and 共用git目錄 and _絕對路徑(專案, git目錄) == _絕對路徑(專案, 共用git目錄)
    )
    return 閘紅現場(
        閘點=閘點,
        分支=_git輸出(專案, "branch", "--show-current") or "",
        權威repo=權威repo,
        喚醒來源=喚醒來源契約(喚醒來源),
        commit=_git輸出(專案, "rev-parse", "HEAD") or "",
        發生時間=datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    )


def 落成閘紅票們(
    結果們: Iterable[檢查結果],
    *,
    閘點: str,
    喚醒來源: 喚醒來源契約 | str,
    專案: Path,
) -> tuple[Path, ...]:
    """把這次閘跑出的紅規則逐條落成票。

    這裡只落維護票，刻意不經健康度閘；紅的時候修理路徑必須永遠放行。
    """
    紅的 = tuple(結果 for 結果 in 結果們 if not 結果.通過)
    if not 紅的:
        return ()
    來源 = 喚醒來源契約(喚醒來源)
    if 來源 is not 喚醒來源契約.排程到期:
        return ()
    現場 = 建閘紅現場(專案, 閘點=閘點, 喚醒來源=來源)
    目錄 = 收件目錄(專案)
    票們: list[Path] = []
    for 結果 in 紅的:
        票 = 落成閘紅票(結果=結果, 現場=現場, 目錄=目錄)
        if 票 is not None:
            票們.append(票)
    return tuple(票們)


def 落成閘紅票(
    *,
    結果: 檢查結果,
    目錄: Path,
    現場: 閘紅現場 | None = None,
    **現場欄位: Unpack[閘紅現場欄位],
) -> Path | None:
    """符合觸發條件才落成票。"""
    if 結果.通過:
        return None

    現場 = 現場 or 閘紅現場(
        閘點=現場欄位.get("閘點", ""),
        分支=現場欄位.get("分支", ""),
        權威repo=現場欄位.get("權威repo", False),
        喚醒來源=喚醒來源契約(現場欄位.get("喚醒來源", 喚醒來源契約.人手動敲)),
        commit=現場欄位.get("commit", ""),
        發生時間=現場欄位.get("發生時間", ""),
    )
    if not _符合落票條件(現場):
        return None

    機器鍵 = f"# 閘紅：{結果.代碼}\n\n- 閘點：{現場.閘點}\n"
    if _已有同一張閘紅票(目錄, 機器鍵):
        return None

    內容 = (
        f"{機器鍵}"
        f"- 分支：{現場.分支}\n"
        f"- commit：{現場.commit}\n"
        f"- 發生時間：{現場.發生時間}\n\n"
        f"<!--nova:驗收 uv run nova 閘 {現場.閘點}-->\n\n"
        f"## 紅在哪\n\n"
        f"{結果.證據}"
    )
    return 丟一件(內容, 來源=時鐘, 目錄=目錄)


def _符合落票條件(現場: 閘紅現場) -> bool:
    """排除 TDD 工作樹、手動執行、CI 與無法追查的現場。"""
    是權威repo = 現場.權威repo
    是main = 現場.分支 == "main"
    是排程 = 現場.喚醒來源 == 喚醒來源契約.排程到期
    有commit = bool(現場.commit)
    有時間 = bool(現場.發生時間)
    return all((是權威repo, 是main, 是排程, 有commit, 有時間))


def _已有同一張閘紅票(目錄: Path, 機器鍵: str) -> bool:
    """收件匣或處理中的同一條閘紅票存在，就不重複落成。"""
    for 票 in 收件匣與處理中的票(目錄):
        try:
            內容 = 票.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if 內容.startswith(機器鍵):
            return True
    return False


def _git輸出(專案: Path, *參數: str) -> str | None:
    try:
        結果 = 跑git(專案, *參數)
    except OSError:
        return None
    return 結果.stdout.strip() if 結果.returncode == 0 else None


def _絕對路徑(專案: Path, 路徑: str) -> Path:
    原路徑 = Path(路徑)
    return (原路徑 if 原路徑.is_absolute() else 專案 / 原路徑).resolve()

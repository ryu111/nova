"""`nova 線` 的 composition adapter：組合觀測來源與呈現。"""

import argparse
import os
import sys
from pathlib import Path

from nova.契約.帳本 import 事件種類
from nova.契約.成果 import 成果
from nova.契約.線觀測 import (
    _基底參照,
    基底比較,
    程序清查,
    程序資料,
    線現況,
)
from nova.載體.工作樹觀測 import (
    工作樹們,
    最後改動時間,
    未提交檔案數,
    比對基底,
    目前commit,
)
from nova.載體.已處理 import 列出成果, 已處理目錄
from nova.載體.帳本 import 專案識別, 預設帳本目錄
from nova.載體.帳本讀取 import 列出執行, 讀原始事件
from nova.載體.狀態 import 狀態根目錄
from nova.載體.狀態檔 import 狀態檔, 讀現況
from nova.載體.程序觀測 import (
    找nova程序,
    是否在跑,
    解析一行ps,
    這條線的程序,
)
from nova.載體.線呈現 import 排版 as _呈現排版
from nova.載體.重構護欄 import 不拍的目錄

_護欄退出碼 = 4
_基底說明_無 = f"查不到本地 {_基底參照} 這個 ref，領先／落後留空（不是已同步）"

#: 舊名相容別名
線資料 = 線現況
_程序資料 = 程序資料
_程序清查 = 程序清查
_基底比較 = 基底比較
_是否在跑 = 是否在跑
_解析一行ps = 解析一行ps

__all__ = ["執行線", "排版", "查並行現況", "線資料", "線現況"]


def 查並行現況(專案: Path) -> tuple[線現況, ...]:
    """查專案底下每一條線的現況。唯讀：不 fetch、不 checkout、不動任何工作區。"""
    根 = 專案.resolve()
    清查 = 找nova程序()
    # `git worktree list` 第一筆固定是主工作區，`工作樹們` 也保證至少回一筆
    (主路徑, 主分支), *其餘工作樹 = 工作樹們(根)
    return (
        _查一條(主路徑, 主分支, 清查, 是主工作區=True, 主專案=主路徑),
        *(_查一條(路徑, 分支, 清查, 是主工作區=False, 主專案=主路徑) for 路徑, 分支 in 其餘工作樹),
    )


def 執行線(參數: argparse.Namespace) -> int:
    """把命令列參數交給工作線查詢。"""
    sys.stdout.write(排版(查並行現況(Path(參數.根目錄))))
    return 0


def 排版(線們: tuple[線現況, ...]) -> str:
    """保留舊門面，實際排版委派給呈現層。"""
    for 線 in 線們:
        if 線.上一次 is None:
            continue
        str(線.上一次.退出碼)
    return _呈現排版(線們)


def _查一條(
    工作樹: Path,
    分支: str,
    清查: 程序清查 | None,
    *,
    是主工作區: bool,
    主專案: Path | None = None,
) -> 線現況:
    成果們 = 列出成果(已處理目錄(工作樹))
    上一次 = 成果們[0] if 成果們 else None
    程序 = 這條線的程序(工作樹, 清查)
    名字 = 工作樹.name + (f"／{分支}" if 分支 else "")
    基底 = 比對基底(工作樹)
    在跑 = 是否在跑(工作樹, 清查)
    return 線現況(
        名字=名字,
        在跑嗎=在跑,
        跑多久=None if 程序 is None else 程序.跑多久,
        啟動時間=None if 程序 is None else 程序.啟動時間,
        目前階段=_目前階段(工作樹, 主專案=主專案, 上一次=上一次, 在跑=在跑),
        上一次=上一次,
        護欄原因=_護欄原因(工作樹, 上一次),
        未提交檔案數=未提交檔案數(工作樹),
        基底落後數=基底.落後,
        路徑=工作樹.resolve(),
        是主工作區=是主工作區,
        目前commit=目前commit(工作樹),
        基底參照=基底.參照,
        基底說明=_基底說明_無 if 基底.參照 is None else 基底.說明,
        領先基底數=基底.領先,
        最後改動時間=最後改動時間(工作樹, 不拍的目錄),
    )


def _目前階段(
    專案: Path,
    *,
    主專案: Path | None = None,
    上一次: 成果 | None = None,
    在跑: bool | None = None,
) -> str | None:
    """查最近一次執行的目前階段。

    `列出執行` 依時間由新到舊排列。只讀最新一本可讀帳本的階段資訊；
    若該本帳無階段記錄，即代表該次執行未記錄階段，退回讀背景輸出檔。
    """
    if 在跑 is False and 上一次 is not None and 上一次.退出碼 == _護欄退出碼:
        return "護欄"
    for 路徑 in 列出執行(預設帳本目錄(專案)):
        try:
            事件們 = 讀原始事件(路徑)
        except OSError:
            continue
        階段 = _這本帳的階段(事件們)
        if 階段 is not None:
            return 階段
        break
    return _讀背景階段(專案, 主專案=主專案)


def _背景檔候選(專案: Path, 主專案: Path | None = None) -> list[Path]:
    檔名們 = [f"{專案.name.removeprefix('nova-wt-')}.md", f"{專案.name}.md"]
    專案清單 = [專案]
    if 主專案 is not None and 主專案 != 專案:
        專案清單.insert(0, 主專案)

    候選: list[Path] = []
    根目錄們 = [狀態根目錄()]
    if 根 := os.environ.get("XDG_STATE_HOME"):
        根目錄們.append(Path(根))

    for 目錄 in 根目錄們:
        for 對象 in 專案清單:
            識別 = 專案識別(對象)
            候選.extend(目錄 / "專案" / 識別 / "背景" / 檔名 for 檔名 in 檔名們)
    return 候選


def _讀背景階段(專案: Path, 主專案: Path | None = None) -> str | None:
    for 路徑 in _背景檔候選(專案, 主專案=主專案):
        try:
            內容 = 路徑.read_text(encoding="utf-8")
        except OSError:
            continue
        if 階段 := _解析背景階段(內容):
            return 階段
    return None


def _解析背景階段(內容: str) -> str | None:
    階段: str | None = None
    for 行 in 內容.splitlines():
        條 = 行.strip()
        if 條.startswith("→"):
            片段 = 條.removeprefix("→").strip().split()
            if 片段:
                階段 = 片段[0]
    return 階段


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

"""儀表板的資料層：**只呼叫既有的公開讀取器**，組出一份 `契約.儀表板`。

這個檔是儀表板唯一碰世界的地方。每一格都指得出是哪個讀取器回的，
所以「這個數字哪來的」有唯一答案——不是某段 shell 歷史。

三值原則（票 09）在這裡是硬性行為：契約裡沒有的格子這裡不生（未接線由模板喊），
問不到的留 `None`，**算不出成本的執行要數出來不准當 0**——
低報的成本比沒有成本更危險，因為它看起來像個數字。

`查線們` 由參數注入：查一條線要開 `ps` 與 git 子程序，注入之後
「線現況 → 契約」那段轉換才測得動（etime 解成秒、退出碼分佈、票標題從哪張票讀）。
"""

from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

from nova.契約.儀表板 import (
    一家用量,
    一條線,
    一階,
    儀表板,
    失敗碼,
    帳本可見度,
    收件匣,
    負控覆蓋,
    退出碼分佈,
)
from nova.契約.工作流 import 階段代碼
from nova.契約.帳本 import 事件種類, 摘要, 欄位對應
from nova.契約.成果 import 成果
from nova.契約.線觀測 import 線現況
from nova.契約.退出碼 import 放行, 未知, 護欄碼, 閘紅
from nova.契約.遮罩 import 已遮罩文字
from nova.載體.工作樹觀測 import 工作樹們, 目前commit
from nova.載體.已處理 import 已處理目錄
from nova.載體.帳本 import 預設帳本目錄
from nova.載體.帳本讀取 import 列出執行, 讀一次執行, 讀原始事件, 跨專案盤點, 跨專案盤點結果
from nova.載體.收件 import 卡住的, 待處理, 收件目錄
from nova.載體.狀態 import 狀態根目錄
from nova.載體.狀態檔 import 現在幾點
from nova.載體.線 import 查並行現況
from nova.載體.自己動手 import 繞過目錄
from nova.載體.規則表 import 建規則表
from nova.載體.遮罩 import 遮罩

#: 「處理中的都算」——這一格問的是現況不是殘骸，所以門檻是零。
_全部都算 = timedelta(0)

#: 補滿之後的樣子是 `hh:mm:ss` 三段。
_時分秒共幾段 = 3

#: `ps` 的 `etime` 進來時可能少了小時那段：`mm:ss` 或 `hh:mm:ss`
#: （天數在破折號前面，另外拆）。
_可接受的段數 = (2, _時分秒共幾段)

#: 失敗碼那一區寫的是「前七名」。
_前幾名 = 7


def 組儀表板(
    專案: Path,
    *,
    查線們: Callable[[Path], tuple[線現況, ...]] = 查並行現況,
) -> 儀表板:
    """把讀取器問到的東西收成一份儀表板。**唯讀**：不搬檔、不連網、不叫模型。"""
    狀態根 = 狀態根目錄()
    盤點 = 跨專案盤點(狀態根)
    執行們 = 盤點.執行們
    執行摘要們 = [讀一次執行(檔) for _識別, 檔 in 執行們]
    線現況們 = 查線們(專案)
    總token, 總成本美金, 無成本執行數, 呼叫次數 = _統計帳本(執行摘要們)
    return 儀表板(
        產生時間=現在幾點(),
        工作目錄=str(專案),
        目前commit=目前commit(專案),
        總token=總token,
        總成本美金=總成本美金,
        算不出成本的執行數=無成本執行數,
        呼叫次數=呼叫次數,
        繞過次數=len(list(繞過目錄(專案).glob("*.md"))),
        在跑的線=_在跑的非主線數(線現況們),
        退出碼=_退出碼分佈(線現況們),
        收件匣=_收件匣現況(專案),
        工作樹數=max(len(工作樹們(專案)) - 1, 0),
        線們=tuple(_一條線(現) for 現 in 線現況們),
        各家=_各家用量(執行摘要們),
        可見度=_可見度(專案, 狀態根, 盤點, 總token),
        失敗碼們=_失敗碼們(檔 for _識別, 檔 in 執行們),
        負控=_負控覆蓋(專案),
    )


def _在跑的非主線數(現況們: Iterable[線現況]) -> int:
    """只計算明確在跑、且不是主工作區的線。"""
    return sum(1 for 現況 in 現況們 if 現況.在跑嗎 is True and not 現況.是主工作區)


def _統計帳本(摘要們: Iterable[摘要]) -> tuple[int, float | None, int, int]:
    """收成標頭需要的四個帳本數字：token、成本、缺成本執行數、呼叫次數。"""
    總token = 0
    成本們: list[float] = []
    無成本執行數 = 0
    呼叫次數 = 0
    for 摘 in 摘要們:
        總token += 摘.總token
        if 摘.總成本美金 is None:
            無成本執行數 += 1
        else:
            成本們.append(摘.總成本美金)
        呼叫次數 += sum(家.次數 for 家 in 摘.各家)
    # 一本都沒回成本時答案是「不知道」不是「零」；成本語意只看摘要欄位。
    總成本美金 = sum(成本們) if 成本們 else None
    return 總token, 總成本美金, 無成本執行數, 呼叫次數


def _收件匣現況(專案: Path) -> 收件匣:
    """收件匣的四格。**已完成數只認 `已處理/` 底下的 `*.收件`**——

    人手搬出來的 `收件/已完成/` 不是 nova 的概念，`ls 已處理 | wc -l`
    則會把旁邊的成果 `.json` 一起算進去。
    """
    收 = 收件目錄(專案)
    卡 = 卡住的(收, 多久算卡住=_全部都算)
    return 收件匣(
        等著=len(待處理(收)),
        處理中=len(卡) + 卡.跳過幾個,
        已完成=len(list(已處理目錄(專案).glob("*.收件"))),
        讀不動=卡.跳過幾個,
    )


def _退出碼分佈(現況們: Iterable[線現況]) -> 退出碼分佈:
    """已收線的退出碼各幾條。還在跑的、沒有成果帳的都不算——它們還沒有碼。

    **問不到程序狀態（`在跑嗎 is None`）也不算**：那條線還沒有這一輪的退出碼，
    拿上一次那個頂替等於讓上一輪的結果冒充這一輪的。
    """
    退出碼次數: Counter[int] = Counter()
    for 現 in 現況們:
        if 現.在跑嗎 is False and 現.上一次 is not None:
            退出碼次數[現.上一次.退出碼] += 1
    可辨識退出碼 = (放行, 閘紅, 未知, 護欄碼)
    return 退出碼分佈(
        成功=退出碼次數[放行],
        確定失敗=退出碼次數[閘紅],
        未知=退出碼次數[未知],
        護欄=退出碼次數[護欄碼],
        其他=sum(次 for 碼, 次 in 退出碼次數.items() if 碼 not in 可辨識退出碼),
    )


def _一條線(現: 線現況) -> 一條線:
    """一條線的現況 → 儀表板上那一列。查不到的欄位留 `None`，不拿 0 頂替。"""
    工作區 = 現.路徑
    上一次 = 現.上一次
    return 一條線(
        名字=現.名字,
        路徑=str(工作區) if 工作區 is not None else "",
        票標題=None if 現.是主工作區 or 工作區 is None else _票標題(工作區, 上一次),
        目前階段=現.目前階段,
        在跑嗎=現.在跑嗎,
        跑了幾秒=_幾秒(現.跑多久),
        啟動時間=現.啟動時間,
        退出碼=None if 上一次 is None else 上一次.退出碼,
        護欄原因=None if 現.護欄原因 is None else 遮罩(現.護欄原因).文字,
        未提交檔案數=現.未提交檔案數,
        七階=() if 工作區 is None else _七階(工作區),
    )


def _票標題(工作區: Path, 上一次: 成果 | None) -> 已遮罩文字 | None:
    """這條線在做哪張票。**主工作區不走這裡**：它的收件匣是整個專案的匣。

    落盤前一定過遮罩——儀表板是兩個新的磁碟落點，漏遮一個字都不會有人說。
    """
    for 內容 in _看得到的票(收件目錄(工作區)):
        標 = _第一個標題(內容)
        if 標 is not None:
            return 遮罩(標).文字
    if 上一次 is not None and 上一次.任務:
        return 遮罩(上一次.任務.splitlines()[0]).文字
    return None


def _看得到的票(收件: Path) -> Iterator[str]:
    """先看這條線收下的（`處理中/`），再看還等著的第一張。"""
    for 一件 in 卡住的(收件, 多久算卡住=_全部都算):
        yield 一件.題目
    for 檔 in 待處理(收件)[:1]:
        try:
            yield 檔.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return


def _第一個標題(內容: str) -> str | None:
    """票的題目：第一個 `# ` 行。沒有就回 None，不拿第一行頂替。"""
    for 行 in 內容.splitlines():
        if 行.startswith("# "):
            return 行[2:].strip()
    return None


def _幾秒(跑多久: str | None) -> int | None:
    """ps 的 `etime`（`[[dd-]hh:]mm:ss`）→ 秒數。**解不動是 `None` 不是 0。**"""
    if 跑多久 is None:
        return None
    日, 時分秒 = 跑多久.split("-", 1) if "-" in 跑多久 else ("0", 跑多久)
    段們 = 時分秒.split(":")
    if "-" in 跑多久 and len(段們) != _時分秒共幾段:
        return None
    if len(段們) not in _可接受的段數 or not all(段.isdigit() for 段 in (日, *段們)):
        return None
    時, 分, 秒 = ["0"] * (_時分秒共幾段 - len(段們)) + 段們
    return ((int(日) * 24 + int(時)) * 60 + int(分)) * 60 + int(秒)


def _這種事件(檔: Path, 種類: 事件種類) -> Iterator[dict[str, Any]]:
    """一本帳上的某一種事件。**鍵名從 `欄位對應` 取**，不在這裡寫死字串。

    帳本一律走 `讀原始事件`，不自己開 jsonl——讀不動的行怎麼跳過只有一個答案。
    """
    for 事 in 讀原始事件(檔):
        if 事.get(欄位對應["種類"]) == 種類.value:
            yield 事


def _七階(工作區: Path) -> tuple[一階, ...]:
    """這條線最新一本帳上的 `stage_finished`。沒有帳就是空的，不是七個空格。"""
    帳們 = 列出執行(預設帳本目錄(工作區))
    if not 帳們:
        return ()
    出: list[一階] = []
    for 事 in _這種事件(帳們[0], 事件種類.階段結束):
        綠 = 事.get(欄位對應["判準綠"])
        出.append(
            一階(
                階段=str(事.get(欄位對應["階段"], "")),
                終局=str(事.get(欄位對應["終局"], "")),
                判準綠=綠 if isinstance(綠, bool) else None,
            )
        )
    return tuple(出)


def _各家用量(摘要們: Iterable[摘要]) -> tuple[一家用量, ...]:
    """各家跨執行的用量。`token` 只算輸入＋輸出，跟 `摘要.總token` 不是同一個數。"""
    次數: Counter[str] = Counter()
    token: Counter[str] = Counter()
    for 摘 in 摘要們:
        for 家 in 摘.各家:
            次數[家.供應商] += 家.次數
            token[家.供應商] += 家.輸入token + 家.輸出token
    總 = sum(token.values())
    return tuple(
        一家用量(
            供應商=名,
            次數=次數[名],
            token=token[名],
            佔比=token[名] / 總 if 總 else 0.0,
            平均每次=token[名] // 次數[名] if 次數[名] else 0,
        )
        for 名 in sorted(token, key=lambda 名: (-token[名], 名))
    )


def _失敗碼們(檔們: Iterable[Path]) -> tuple[失敗碼, ...]:
    """跨執行的失敗代碼**前七名**。**鍵名從 `欄位對應` 取**，不在這裡寫死字串。

    截成七筆是介面上那一區的定義：帳本會一直長，全部回出去的話
    「最常見的是哪幾個」——那一區存在的唯一理由——反而看不出來。
    """
    數: Counter[str] = Counter()
    for 檔 in 檔們:
        for 事 in _這種事件(檔, 事件種類.呼叫結束):
            碼 = 事.get(欄位對應["失敗代碼"])
            if isinstance(碼, str):
                數[碼] += 1
    排好的 = sorted(數, key=lambda 碼: (-數[碼], 碼))[:_前幾名]
    return tuple(失敗碼(代碼=碼, 次數=數[碼]) for 碼 in 排好的)


def _可見度(專案: Path, 狀態根: Path, 盤點: 跨專案盤點結果, 全部token: int) -> 帳本可見度:
    """帳本看得見多少。**「沒有帳」跟「沒有這個專案」是兩件事**，兩個數字分開。

    `狀態根` 由呼叫端傳進來：同一份儀表板上的每個數字要來自同一次問狀態目錄。
    """
    專案們 = 狀態根 / "專案"
    有目錄 = [路 for 路 in 專案們.iterdir() if 路.is_dir()] if 專案們.is_dir() else []
    return 帳本可見度(
        本專案token=sum(讀一次執行(檔).總token for 檔 in 列出執行(預設帳本目錄(專案))),
        全部token=全部token,
        專案鍵總數=len(有目錄),
        有內容的專案鍵=len({識別 for 識別, _檔 in 盤點.執行們}),
        跳過的檔=盤點.跳過的檔,
    )


def _負控覆蓋(專案: Path) -> 負控覆蓋:
    """負控的覆蓋面。**是檔數不是刀數**——刀數要 import tests，src 不准。"""
    登記們 = 專案 / "tests" / "負控" / "登記們"
    return 負控覆蓋(
        登記檔數=len([路 for 路 in 登記們.glob("*.py") if 路.name != "__init__.py"]),
        紀錄檔數=len(list((專案 / "docs" / "負控紀錄").glob("*.md"))),
        閘規則數=len(建規則表(專案)),
        階段數=len(階段代碼),
    )

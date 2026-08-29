"""讀取端：把一串事件收斂成一次執行的摘要。

寫端（`nova.載體.帳本`）與讀端分開，因為兩邊的要求不一樣：
寫端要在**程序被殺的當下**還可靠（每筆 flush、失敗不往上丟），
讀端只要**讀得動壞掉的檔**。

`收斂` 是純函式（吃字串、吐資料類別），所以它的測試不碰磁碟。
`讀一次執行` 只是加一層開檔。
"""

import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from nova.契約.帳本 import 一家的帳, 一條規則的帳, 事件種類, 摘要

_開始的 = {事件種類.呼叫開始.value, 事件種類.階段開始.value, 事件種類.規則開始.value}
_結束的 = {事件種類.呼叫結束.value, 事件種類.階段結束.value, 事件種類.規則結束.value}
_認得的 = _開始的 | _結束的


def 收斂(行們: Iterable[str], *, 預設識別碼: str = "") -> 摘要:
    """一串 jsonl 行 → 一份摘要。

    **壞行跳過但要記數**：失敗模型明講不防「磁碟滿留下半行」，
    所以讀不動的行一定會出現。整份讀不動比少一行糟得多——
    那等於一次磁碟意外洗掉整次執行的證據。
    """
    收 = _收集器(預設識別碼)
    for 行 in 行們:
        if not 行.strip():
            continue  # 檔尾的換行不是損壞
        事 = _解析(行)
        if 事 is None:
            收.壞行 += 1
            continue
        收.吃(事)
    return 收.收成()


def 讀一次執行(路徑: Path) -> 摘要:
    """讀一個帳本檔。`收斂` 加一層開檔，外加**用檔名當識別碼的後備**。

    執行一開始就被殺的那次，帳本是空檔——但檔名就是執行識別碼。
    不補的話那次執行在讀取端變成無名氏，而「開了檔卻一筆都沒寫」
    正是最需要被看見的那種死法。
    """
    with 路徑.open(encoding="utf-8") as 檔:
        return 收斂(檔, 預設識別碼=路徑.stem)


def 列出執行(目錄: Path) -> list[Path]:
    """目錄裡的帳本檔，新的在前。檔名開頭是時戳所以字典序就是時序。"""
    if not 目錄.is_dir():
        return []
    return sorted(目錄.glob("*.jsonl"), reverse=True)


def _解析(行: str) -> dict[str, Any] | None:
    """一行 → 事件，認不得就回 None。

    **fail-closed**：默默忽略會讓「格式改過了」看起來像「那次沒發生」。
    """
    try:
        事 = json.loads(行)
    except json.JSONDecodeError:
        return None
    if not isinstance(事, dict) or 事.get("event") not in _認得的:
        return None
    return 事


class _收集器:
    """一邊掃一邊累加。用可變物件是因為這是折疊的中間狀態，不是對外的形狀。"""

    def __init__(self, 預設識別碼: str = "") -> None:
        """`預設識別碼` 是**後備**，另外存：檔案裡有就以檔案裡的為準。

        直接拿它當 `識別` 的初值不行——`吃()` 用的是 `識別 or 事件裡的`，
        初值一有東西，檔案自己記的那個就永遠蓋不進來。
        """
        self.壞行 = 0
        self.預設識別碼 = 預設識別碼
        self.識別 = ""
        self.起 = ""
        self.迄 = ""
        self.階段: list[str] = []
        self.開著: dict[int, None] = {}
        self.次數: Counter[str] = Counter()
        self.終局: Counter[tuple[str, str]] = Counter()
        self.token: Counter[tuple[str, str]] = Counter()

    def 吃(self, 事: dict[str, Any]) -> None:
        self.識別 = self.識別 or str(事.get("run", ""))
        時 = str(事.get("ts", ""))
        self.起 = self.起 or 時
        self.迄 = 時 or self.迄
        種 = 事["event"]
        編號 = 事.get("call")
        if 種 in _開始的 and isinstance(編號, int):
            self.開著[編號] = None
        elif isinstance(編號, int):
            self.開著.pop(編號, None)
        if 種 == 事件種類.階段開始.value:
            self.階段.append(str(事.get("stage", "")))
        if 種 == 事件種類.呼叫結束.value:
            self._記一次呼叫(事)

    def _記一次呼叫(self, 事: dict[str, Any]) -> None:
        """累加一次模型呼叫。

        **只有呼叫結束會加 token**：階段結束帶的是它裡面那幾次呼叫的加總，
        兩邊都加就變兩倍。
        """
        家 = str(事.get("family", ""))
        self.次數[家] += 1
        self.終局[家, str(事.get("outcome", ""))] += 1
        for 欄 in ("input_tokens", "output_tokens"):
            值 = 事.get(欄)
            if isinstance(值, int):
                self.token[家, 欄] += 值

    def 收成(self) -> 摘要:
        各家 = tuple(
            一家的帳(
                供應商=家,
                次數=self.次數[家],
                成功=self.終局[家, "success"],
                失敗=self.終局[家, "failed"],
                未知=self.終局[家, "unknown"],
                輸入token=self.token[家, "input_tokens"],
                輸出token=self.token[家, "output_tokens"],
            )
            for 家 in self.次數
        )
        return 摘要(
            執行識別碼=self.識別 or self.預設識別碼,
            起=self.起,
            迄=self.迄,
            各家=各家,
            階段們=tuple(self.階段),
            沒收尾的呼叫=tuple(self.開著),
            壞掉的行=self.壞行,
            總token=sum(家.輸入token + 家.輸出token for 家 in 各家),
        )


def 統計規則(目錄: Path) -> tuple[一條規則的帳, ...]:
    """把目錄裡所有帳本的規則事件跨執行加總。

    **只算結束事件**：開始事件不代表跑完了，兩邊都算會讓次數變兩倍。

    這是「這條規則有沒有在守東西」唯一的資料來源。在此之前 nova 的 9 條規則
    一條都沒有觸發率資料——只能憑印象。
    """
    跑過: Counter[tuple[str, str]] = Counter()
    紅過: Counter[tuple[str, str]] = Counter()
    for 檔 in 列出執行(目錄):
        for 行 in 檔.read_text(encoding="utf-8").splitlines():
            事 = _解析(行)
            if 事 is None or 事["event"] != 事件種類.規則結束.value:
                continue
            鍵 = (str(事.get("rule", "")), str(事.get("gate_point", "")))
            跑過[鍵] += 1
            if 事.get("gate_green") is False:
                紅過[鍵] += 1
    return tuple(
        一條規則的帳(規則=規則, 閘點=閘點, 跑過=次, 紅過=紅過[規則, 閘點])
        for (規則, 閘點), 次 in sorted(跑過.items())
    )

"""帳本的契約：一次執行裡發生過什麼，寫成一串事件。

規格 §2.1 的「可觀測性」那一格。現在 nova 的證據只活在 stdout——
程序一結束就沒了，`nova 問` 花了多少、哪一顆腦接力接到第幾顆、
哪個階段一直摔，事後全部問不出來。

**這一層只定形狀，不碰檔案。** 落盤在 `nova.載體.帳本`（依賴反轉：
高層決定需要什麼形狀，低層去符合）。

## 為什麼是 Callable 別名，不是 Protocol

目前只有一種 sink（append 到 jsonl）。一個實作不寫 interface
（`寫程式.md`）。出現第二種（stderr、SQLite、遠端）再依三次法則抽——
到那時候才知道正確的形狀。

## 為什麼事件要成對

只記結束事件的話，nova 被逾時殺掉時那一筆永遠不會寫出來——
於是「哪一家正在跑、跑了多久」在最需要知道的那次剛好沒有。
開始事件是**副作用發生之前**寫的，所以它一定寫得出去。

配對靠 `呼叫編號`，不靠「相鄰兩行」——接力鏈是巢狀的，
腦 A 的開始與結束中間會夾著別的事件。
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from nova.契約.遮罩 import 已遮罩文字


class 事件種類(StrEnum):
    """帳本記哪幾種事。值 ASCII——跨程序（別的程式會讀這個檔）。"""

    呼叫開始 = "call_started"
    呼叫結束 = "call_finished"
    階段開始 = "stage_started"
    階段結束 = "stage_finished"
    #: 閘跑一條規則。**這是「哪條規則在守東西」唯一的資料來源**——
    #: 從來不紅的規則是刪除候選，常紅的是該補指引的地方。
    規則開始 = "rule_started"
    規則結束 = "rule_finished"


@dataclass(frozen=True, slots=True)
class 事件:
    """一件發生過的事。

    除了 `種類` 之外全部可以是 None——一個事件用得到的欄位是少數，
    用不到的**不落盤**（不是落成 null）。補零或補 null 會讓
    「沒這個概念」跟「值是零」長得一樣。

    **模型講了什麼記在 `文字`，而且一定是遮罩過的**（`載體.遮罩`）。
    以前不記，理由是 repo public 而遮罩不存在；遮罩做出來之後那個理由消失了。
    `遮掉幾處` 是誠實欄位——0 代表這是原文，大於 0 代表你看到的缺了幾塊。

    **提示不記，一個字都不記。** 兩邊不對稱是刻意的：提示裡有前情、進度檔、
    nova 自己組進去的檔案內容，外洩面大得多，而且它答不了
    「模型說了什麼」那個問題。
    """

    種類: 事件種類
    #: 成對事件的配對鍵。同一次執行裡遞增，開始與結束共用一個。
    呼叫編號: int | None = None
    供應商: str | None = None
    模型: str | None = None
    權限: str | None = None
    #: 接力鏈的第幾顆（從 1 起算）。沒有這格就分不出「第一顆掛了換第二顆」
    #: 與「同一顆被叫了兩次」。
    接力第幾顆: int | None = None
    階段: str | None = None
    #: 閘跑的那條規則的代碼。
    規則: str | None = None
    #: 哪個閘點（提交／ci）。同一條規則在兩個閘點的觸發率可以差很多。
    閘點: str | None = None
    終局: str | None = None
    失敗代碼: str | None = None
    輸入token: int | None = None
    輸出token: int | None = None
    #: 只有 claude 給得出來。**不准為了三家對稱而自己估算**——
    #: 猜出來的成本比沒有成本更危險。給不出來就不落盤。
    成本美金: float | None = None
    #: 從發出去到回來多久。逾時的診斷靠它——沒有耗時就分不出
    #: 「一秒就掛」與「跑滿 30 分鐘被殺」。
    耗時毫秒: int | None = None
    判準綠: bool | None = None
    審查結論: str | None = None
    #: 形狀：長度與雜湊。**長度永遠是原始長度**，截斷之後也一樣——
    #: 少了它，截斷過的全文會長得像模型只講了這麼多。
    #: 雜湊取前 16 個十六進位字元，用途是「跟上次一不一樣」，
    #: 不是密碼學上的抗碰撞。
    文字長度: int | None = None
    文字雜湊: str | None = None
    #: 模型講的話，遮罩過。`--不記全文` 的時候是 None。
    #: **型別是 `已遮罩文字` 不是 `str`**：忘了遮就編不過（決策 0002）。
    文字: 已遮罩文字 | None = None
    #: 遮掉幾處。**誠實欄位**：0 是原文，大於 0 代表缺了幾塊。
    遮掉幾處: int | None = None
    #: 太長被截掉了。沒截就不落盤這一格（不是落 false）。
    文字截斷: bool | None = None


#: 中文欄位名 → 落盤用的 ASCII 鍵。**單一來源**，由
#: `test_每個欄位都有對應` 窮舉背書：少一格就紅。
#:
#: 為什麼不用 `dataclasses.asdict` 直接吐中文鍵：這個檔會被別的程式讀
#: （grep、jq、之後的 reducer），中文鍵在 shell 裡很難打，
#: 屬於 CLAUDE.md 的「event／schema 欄位名」ASCII 例外。
欄位對應: dict[str, str] = {
    "種類": "event",
    "呼叫編號": "call",
    "供應商": "family",
    "模型": "model",
    "權限": "permission",
    "接力第幾顆": "attempt",
    "階段": "stage",
    "規則": "rule",
    "閘點": "gate_point",
    "終局": "outcome",
    "失敗代碼": "failure_code",
    "輸入token": "input_tokens",
    "輸出token": "output_tokens",
    "成本美金": "cost_usd",
    "耗時毫秒": "duration_ms",
    "判準綠": "gate_green",
    "審查結論": "verdict",
    "文字長度": "text_len",
    "文字雜湊": "text_sha256",
    "文字": "text",
    "遮掉幾處": "redactions",
    "文字截斷": "text_truncated",
}

#: sink 自己補上去的三個鍵，事件本身不准有同名欄位
#: （撞名的話事件會蓋掉序號，整個檔就失去順序）。
落盤時加的鍵: tuple[str, ...] = ("run", "seq", "ts")


#: 記一筆帳。**只有寫**——讀由 `nova.載體.帳本讀取` 那一邊做，
#: 兩件事分開是因為寫端要能在被殺掉的當下還可靠，讀端不必。
記一筆 = Callable[[事件], None]


@dataclass(frozen=True, slots=True)
class 一家的帳:
    """某一家在這次執行裡的總帳。

    `失敗` 與 `未知` 分開不是為了好看：那兩者的重試政策相反
    （見 `模型回應.終局`），加在一起就看不出「這次到底能不能重跑」。
    """

    供應商: str
    次數: int
    成功: int
    失敗: int
    未知: int
    輸入token: int
    輸出token: int
    成本美金: float | None = None


@dataclass(frozen=True, slots=True)
class 一條規則的帳:
    """一條規則**跨執行**的紀錄。

    一次執行看不出觸發率——每條規則一趟只跑一次。要跨執行加總才有意義：
    從來不紅的是刪除候選，常紅的是該補指引的地方。

    `閘點` 一起當鍵：同一條規則在提交閘與 CI 的觸發率可以差很多，
    混在一起就看不出來。
    """

    規則: str
    閘點: str
    跑過: int
    紅過: int


@dataclass(frozen=True, slots=True)
class 摘要:
    """一次執行收斂之後長什麼樣。

    `沒收尾的呼叫` 是最值錢的一格：有開始沒有結束＝那次呼叫發出去了、
    但 nova 沒能寫下結果（多半是被殺掉）。**少了這一格，
    帳本看起來就像那次呼叫沒發生過**——而它可能已經改了檔案。

    `壞掉的行` 是誠實欄位：讀不動的行不准默默跳過不講，
    否則「證據不完整」會長得跟「事情沒發生」一樣。
    """

    執行識別碼: str
    起: str
    迄: str
    各家: tuple[一家的帳, ...]
    階段們: tuple[str, ...]
    沒收尾的呼叫: tuple[int, ...]
    壞掉的行: int
    總token: int
    總成本美金: float | None = None

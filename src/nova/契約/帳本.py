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


class 事件種類(StrEnum):
    """帳本記哪幾種事。值 ASCII——跨程序（別的程式會讀這個檔）。"""

    呼叫開始 = "call_started"
    呼叫結束 = "call_finished"
    階段開始 = "stage_started"
    階段結束 = "stage_finished"


@dataclass(frozen=True, slots=True)
class 事件:
    """一件發生過的事。

    除了 `種類` 之外全部可以是 None——一個事件用得到的欄位是少數，
    用不到的**不落盤**（不是落成 null）。補零或補 null 會讓
    「沒這個概念」跟「值是零」長得一樣。

    **這裡沒有模型講了什麼。** repo 是 public，遮罩機制還不存在，
    把模型全文寫進帳本等於多開一條外洩路徑。要對照輸出改變與否，
    `文字長度` 加 `文字雜湊` 就夠了。
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
    終局: str | None = None
    失敗代碼: str | None = None
    輸入token: int | None = None
    輸出token: int | None = None
    #: 從發出去到回來多久。逾時的診斷靠它——沒有耗時就分不出
    #: 「一秒就掛」與「跑滿 30 分鐘被殺」。
    耗時毫秒: int | None = None
    判準綠: bool | None = None
    審查結論: str | None = None
    #: 只記形狀不記內容：長度與雜湊。雜湊取前 16 個十六進位字元——
    #: 用途是「跟上次一不一樣」，不是密碼學上的抗碰撞。
    文字長度: int | None = None
    文字雜湊: str | None = None


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
    "終局": "outcome",
    "失敗代碼": "failure_code",
    "輸入token": "input_tokens",
    "輸出token": "output_tokens",
    "耗時毫秒": "duration_ms",
    "判準綠": "gate_green",
    "審查結論": "verdict",
    "文字長度": "text_len",
    "文字雜湊": "text_sha256",
}

#: sink 自己補上去的三個鍵，事件本身不准有同名欄位
#: （撞名的話事件會蓋掉序號，整個檔就失去順序）。
落盤時加的鍵: tuple[str, ...] = ("run", "seq", "ts")


#: 記一筆帳。**只有寫，沒有讀**——讀取端是另一個問題（reducer／checkpoint），
#: 還沒做；在它做完之前不准宣稱 nova 補了 State。
記一筆 = Callable[[事件], None]

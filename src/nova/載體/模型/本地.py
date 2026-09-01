"""本地模型：介面的基準形狀。

**它跑得動，才證明真的沒綁定任何一家。** claude／codex／agy 各自帶著一整套載體
（工具、sandbox、session）；本地模型只有腦。`語言模型` Protocol 只要求
`名稱` 與 `詢問`——這一格裝得進去，就證明那個 Protocol 是**模型形狀**
不是 CLI 形狀。

形狀是 OpenAI 相容的 HTTP 端點：本機的 omlx-server、llama.cpp、ollama、vllm
都長這樣。用標準庫的 `urllib` 不用 `requests`——nova 的 `dependencies` 是空的，
為了一個 POST 加一個相依不划算（`寫程式.md` 的階梯：標準庫那一階就停）。

## 做不到的事一律明講

本地模型沒有 session。默默忽略 `續接` 的話，工作流會以為 session 還在，
然後在驗證階段才發現什麼都沒發生——而那時候看起來像是「模型做錯了」，
不是「這顆腦根本做不到」。**診斷順序會整個被帶歪。**

工具由 nova 自行跑迴圈（OpenAI tools 規格），每筆工具呼叫會留證據進帳本。

## 成本是 0 不是 None

本地跑沒有 API 帳單，那是**事實不是估算**（「不准為了三家對稱而自己估算」
管的是估算）。回 None 的話，一次混著本地與 claude 的執行會整個算不出成本
——而那次其實算得出來。
"""

import json
import urllib.error
import urllib.request
from collections.abc import Collection
from dataclasses import dataclass
from os import environ
from pathlib import Path
from typing import Any

from nova.契約.帳本 import 事件, 事件種類, 記一筆
from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.契約.角色 import 呼叫選項, 預設選項
from nova.載體.模型.本地工具 import 工具箱, 工具錯誤

#: 本機推論伺服器的預設位置。`NOVA_LOCAL_URL` 蓋得掉——
#: 那是**設定不是邏輯**（一個網址），所以放環境變數沒有違反
#: 「你的邏輯不准住在別人的設定檔裡」。
預設網址 = "http://127.0.0.1:8000/v1"
網址環境變數 = "NOVA_LOCAL_URL"

#: 家族名。ASCII——它會流進帳本的 `family` 欄位被 grep，
#: 屬於 CLAUDE.md 的「跨程序 semantic id」例外。
家族名 = "local"

_探型號逾時秒 = 5.0

#: 一次 `詢問` 裡最多讓模型發幾回合工具呼叫。
#:
#: **沒有停止規則的迴圈是成本漏洞**（`AGENT_ARCHITECTURE` §3.2）。模型可以一直
#: 發同一個呼叫——不是因為壞了，是因為它覺得還沒讀夠。本地跑不燒 API 額度，
#: 但燒時間與電，而且卡住的樣子是「nova 沒有回應」。
#:
#: 8 → 16（2026-09-01）。**這次是量出來的，不是拍腦袋**：帳本全量顯示本地腦
#: 撞上限 19 次、燒掉 1,931,437 token 而零產出——撞上限的那一輪等於整段白跑。
#: 8 對「讀三四個檔再改一處」剛好，對 TDD 的實作階段不夠。
#:
#: 天花板還在：16 一樣是常數，一樣可能不夠。要再調之前先量同一個數字
#: （撞上限次數與它的 token），別憑感覺加。
最多工具回合 = 16
#: 剩幾回合開始催收尾。**這是迴圈的責任不是提示的責任**——
#: 提示裡的是懇求，包住執行者的程式碼裡才是保證。
#:
#: 為什麼需要它：實測兩個 run 共 28 次工具呼叫、`write_file` **零次**，
#: 全部撞上回合上限。回合 1-4 就讀完該讀的了，5-8 在 grep 自己
#: 幻想出來的函式名（`docs/負控紀錄/0001-既有紀錄.md` 有完整序列）。
#: 病不是「規則被上下文淹掉」——重複讀取比例只有 7.1%／0.0%——
#: 是**不知道該收尾了**。
剩幾回合開始催 = 3
#: 最後幾回合把找東西的工具收掉。**倒數提醒是懇求，收掉工具才是保證**——
#: 模型連發出 `grep` 的形狀都沒有。留 2 回合是為了「催了還有兩次機會動手」。
收尾幾回合只准寫 = 2


def 審查資格理由(家們: Collection[str]) -> str | None:
    """本地腦不能成為工作流唯一的審查點。"""
    if 家族名 in 家們:
        return f"{家族名} 沒有審查資格：9B 本地模型不能當審查員"
    return None


def 預設本地網址() -> str:
    """本機推論伺服器在哪。環境變數蓋得掉，因為那是設定不是邏輯。"""
    return environ.get(網址環境變數) or 預設網址


@dataclass(frozen=True, slots=True)
class 本地腦:
    """一個 OpenAI 相容的 HTTP 端點。"""

    網址: str
    #: 工具呼叫記帳的 callback。
    #:
    #: **為什麼是 callback 不是讓 `記帳腦` 去撈**：工具迴圈在 `本地腦` 內部跑，
    #: 只有內部知道每回合呼叫了什麼工具與執行結果。`本地腦` 絕不准自行 import
    #: `nova.載體.帳本`（否則載體分層會倒過來），只依賴 `nova.契約.帳本` 的 `記一筆`。
    #:
    #: 限制：`呼叫編號` 由外層 `記帳腦` 產生，內層拿不到，因此工具呼叫事件不帶
    #: `呼叫編號`——這是為了維持分層乾淨的設計取捨。
    記: 記一筆 | None = None

    @property
    def 名稱(self) -> str:
        """家族名。包一層不換身分——接力鏈印出來的「試過誰」要看得出是它。"""
        return 家族名

    def 詢問(self, 提示: str, *, 選項: 呼叫選項 = 預設選項) -> 回應:
        """問一次。**做不到的事在打出去之前就明講。**"""
        做不到 = _做不到的地方(選項)
        if 做不到 is not None:
            return _建立失敗回應(做不到, 失敗代碼.用法錯誤, 結束碼=2)
        try:
            型號 = 選項.模型 or self._第一個型號(選項.逾時秒)
            return self._跑工具迴圈(提示, 型號=型號, 選項=選項)
        except TimeoutError:
            # **請求可能已經出門了。** 確定失敗會讓上層放心重跑，而那會重做副作用。
            return _建立失敗回應(
                f"{self.網址} 超過 {選項.逾時秒} 秒沒回應", 失敗代碼.逾時, 未知=True
            )
        except urllib.error.HTTPError as 錯:
            return _建立失敗回應(f"{self.網址} 回 HTTP {錯.code}", 失敗代碼.上游, 結束碼=錯.code)
        except (urllib.error.URLError, OSError) as 錯:
            return _處理連線錯誤(self.網址, 選項.逾時秒, 錯)
        except (ValueError, KeyError, IndexError) as 錯:
            return _建立失敗回應(f"{self.網址} 的回應看不懂（{錯}）", 失敗代碼.上游)

    def _跑工具迴圈(self, 提示: str, *, 型號: str, 選項: 呼叫選項) -> 回應:
        """送 tools → 收 tool_calls → 執行 → 塞回 messages → 再問，直到它收尾。

        **每一回合的用量都要加總**：`接力腦` 踩過一模一樣的坑——只回最後一次的
        用量，前面幾回合燒掉的在 `單次最多token` 的檢查裡憑空消失。
        """
        # **沒給工作目錄就不給工具**（fail-closed）——「沒指定範圍」不是「範圍是這裡」。
        箱 = 工具箱(Path(選項.工作目錄) if 選項.工作目錄 else None, 選項.權限)
        對話: list[dict[str, Any]] = [{"role": "user", "content": 提示}]
        入計 = 出計 = 0
        for 回合 in range(1, 最多工具回合 + 1):
            只留寫入 = 回合 > 最多工具回合 - 收尾幾回合只准寫
            資料 = self._送出對話(
                對話, 型號=型號, 逾時秒=選項.逾時秒, 工具們=箱.規格(只留寫入=只留寫入)
            )
            用了 = 資料.get("usage") or {}
            入計 += int(用了.get("prompt_tokens", 0))
            出計 += int(用了.get("completion_tokens", 0))
            訊息 = 資料["choices"][0]["message"]
            呼叫們 = 訊息.get("tool_calls") or []
            if not 呼叫們:
                return _讀成回應(資料, 入計=入計, 出計=出計)
            對話.append(訊息)
            對話.extend(_做完工具(箱, 呼叫們, 回合=回合, 記=self.記))
            if (催 := _催收尾(回合, 寫過檔=箱.寫過檔了嗎)) is not None:
                對話.append(催)
        return _建立失敗回應(
            f"工具呼叫超過 {最多工具回合} 回合還沒收尾，停止（沒有停止規則的迴圈是成本漏洞）",
            失敗代碼.用法錯誤,
            結束碼=4,
            用了=用量(輸入token=入計, 輸出token=出計, 成本美金=0.0),
        )

    def _第一個型號(self, 逾時秒: float) -> str:
        """**不寫死型號**——寫死的話換一顆模型就要改 nova 的原始碼。"""
        模型清單 = self._發出請求(
            f"{self.網址}/models", 內容=None, 逾時秒=min(逾時秒, _探型號逾時秒)
        )
        return str(模型清單["data"][0]["id"])

    def _送出對話(
        self,
        對話: list[dict[str, Any]],
        *,
        型號: str,
        逾時秒: float,
        工具們: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._發出請求(
            f"{self.網址}/chat/completions",
            內容={"model": 型號, "messages": 對話, "tools": 工具們},
            逾時秒=逾時秒,
        )

    def _發出請求(self, 網址: str, *, 內容: dict[str, Any] | None, 逾時秒: float) -> dict[str, Any]:
        身體 = None if 內容 is None else json.dumps(內容).encode("utf-8")
        請求 = urllib.request.Request(  # noqa: S310 —— 網址由設定給定，不吃模型輸出
            網址, data=身體, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(請求, timeout=逾時秒) as 回:  # noqa: S310 —— 同上
            讀到: dict[str, Any] = json.loads(回.read().decode("utf-8"))
        return 讀到


#: 參數摘要最多留 200 字。`write_file` 等工具的參數可能包含大量文字，
#: 整份落盤會讓帳本膨脹。
_工具參數摘要上限 = 200


def _催收尾(回合: int, *, 寫過檔: bool) -> dict[str, str] | None:
    """回合快用完、而且一個檔都還沒寫時，回一則要塞進對話的提醒。

    **不催的三種情況**：已經在寫檔（它在做正事，催是噪音）、
    還早（前幾回合是正常探索）、已經是最後一回合（後面沒有下一次請求了，
    催了只是白付一次 token）。
    """
    剩 = 最多工具回合 - 回合
    if 寫過檔 or 剩 > 剩幾回合開始催 or 剩 <= 0:
        return None
    return {
        "role": "user",
        "content": (
            f"還剩 {剩} 個回合就會被停掉，而且到現在一個檔案都還沒寫。"
            "看夠了就現在寫；還缺什麼就直接說缺什麼，不要再找了。"
        ),
    }


def _做完工具(
    箱: 工具箱,
    呼叫們: list[dict[str, Any]],
    *,
    回合: int,
    記: 記一筆 | None,
) -> list[dict[str, Any]]:
    """跑完這一批工具呼叫，把結果做成 `role: "tool"` 的訊息。

    **工具出錯不讓整輪垮掉**——模型會叫不存在的檔案、會給越界的路徑，那是正常的
    不是異常。把錯誤訊息回給它，下一回合它就能改；整輪垮掉的話那次呼叫全白費。
    """
    結果們: list[dict[str, Any]] = []
    for 呼 in 呼叫們:
        函 = 呼.get("function") or {}
        名稱 = str(函.get("name", ""))
        引數原始 = 函.get("arguments") or "{}"
        內容, 成功 = _執行工具(箱, 名稱, 引數原始)
        _記工具事件(記, 名稱=名稱, 引數原始=引數原始, 回合=回合, 成功=成功)
        結果們.append({"role": "tool", "tool_call_id": 呼.get("id", ""), "content": 內容})
    return 結果們


def _記工具事件(
    記: 記一筆 | None,
    *,
    名稱: str,
    引數原始: str,
    回合: int,
    成功: bool,
) -> None:
    """工具呼叫留證據進帳本。"""
    if 記 is None:
        return
    記(
        事件(
            種類=事件種類.工具呼叫,
            供應商=家族名,
            工具名稱=名稱,
            工具參數摘要=引數原始[:_工具參數摘要上限],
            工具回合=回合,
            工具成功=成功,
        )
    )


def _執行工具(箱: 工具箱, 名稱: str, 引數原始: str) -> tuple[str, bool]:
    """執行單一工具呼叫，回傳（結果內容, 是否成功）。

    工具執行失敗或參數解析失敗皆視為正常反饋，不丟出例外。
    """
    try:
        參數 = json.loads(引數原始)
        return 箱.執行(名稱, 參數), True
    except 工具錯誤 as 錯:
        return f"工具失敗：{錯}", False
    except json.JSONDecodeError as 錯:
        return f"工具參數不是合法 JSON（{錯}）", False


def _做不到的地方(選項: 呼叫選項) -> str | None:
    """這顆腦撐不起來的要求。回 None ＝ 都撐得起來。

    **可編輯不再擋**（2026-08-31）：端點吃 OpenAI 相容的 `tools`，模型會發
    `tool_calls` 也吃得下 `role: "tool"` 的結果——「本地模型沒有工具」是
    nova 沒給它工具，不是模型不會用。
    """
    if 選項.續接:
        return "本地模型沒有 session，接不下去。要續接就換一顆有 session 的腦"
    return None


def _處理連線錯誤(網址: str, 逾時秒: float, 錯誤: urllib.error.URLError | OSError) -> 回應:
    """把連線失敗分成「未安裝」與「結果未知」。"""
    是逾時 = isinstance(錯誤, urllib.error.URLError) and isinstance(錯誤.reason, TimeoutError)
    if 是逾時:
        return _建立失敗回應(f"{網址} 超過 {逾時秒} 秒沒回應", 失敗代碼.逾時, 未知=True)
    return _建立失敗回應(f"連不上 {網址}（{錯誤}）", 失敗代碼.未安裝)


def _建立失敗回應(
    訊息: str,
    代碼: 失敗代碼,
    *,
    結束碼: int = 1,
    未知: bool = False,
    用了: 用量 | None = None,
) -> 回應:
    """`用了` 給撞上限的那條路徑用——**失敗也花了 token**，不填就等於漏記。"""
    return 回應(
        文字=訊息,
        終局=終局.結果未知 if 未知 else 終局.確定失敗,
        失敗代碼=代碼,
        原始結束碼=結束碼,
        對話識別碼=None,
        用量=用了 or 用量(輸入token=0, 輸出token=0, 成本美金=0.0),
    )


def _讀成回應(回應資料: dict[str, Any], *, 入計: int = 0, 出計: int = 0) -> 回應:
    """`入計`／`出計` 是**整條工具迴圈**的加總，不是最後一回合的。

    只算最後一回合的話，前面幾回合燒掉的在 `單次最多token` 的檢查裡憑空消失
    ——`接力腦` 踩過一模一樣的坑：算錯的上限也是成本漏洞。
    """
    用量資料 = 回應資料.get("usage") or {}
    這回合入 = int(用量資料.get("prompt_tokens", 0))
    這回合出 = int(用量資料.get("completion_tokens", 0))
    return 回應(
        文字=str(回應資料["choices"][0]["message"]["content"]),
        終局=終局.成功,
        失敗代碼=失敗代碼.無,
        原始結束碼=0,
        對話識別碼=回應資料.get("id"),
        用量=用量(
            輸入token=入計 or 這回合入,
            輸出token=出計 or 這回合出,
            # 本地跑沒有 API 帳單。**事實不是估算。**
            成本美金=0.0,
        ),
    )

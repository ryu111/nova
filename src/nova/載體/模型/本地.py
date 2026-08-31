"""本地模型：介面的基準形狀。

**它跑得動，才證明真的沒綁定任何一家。** claude／codex／agy 各自帶著一整套載體
（工具、sandbox、session）；本地模型只有腦。`語言模型` Protocol 只要求
`名稱` 與 `詢問`——這一格裝得進去，就證明那個 Protocol 是**模型形狀**
不是 CLI 形狀。

形狀是 OpenAI 相容的 HTTP 端點：本機的 omlx-server、llama.cpp、ollama、vllm
都長這樣。用標準庫的 `urllib` 不用 `requests`——nova 的 `dependencies` 是空的，
為了一個 POST 加一個相依不划算（`寫程式.md` 的階梯：標準庫那一階就停）。

## 做不到的事一律明講

本地模型沒有工具、沒有 session。默默忽略 `權限` 與 `續接` 的話，工作流會以為
檔案改好了，然後在驗證階段才發現什麼都沒發生——而那時候看起來像是
「模型做錯了」，不是「這顆腦根本做不到」。**診斷順序會整個被帶歪。**

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
#: 從簡：8 是拍腦袋的常數，不是量出來的。天花板是「複雜任務可能真的需要更多回合」；
#: 要調的話先量「撞上限的比例」，別憑感覺加。
最多工具回合 = 8


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
        箱 = 工具箱(Path(選項.工作目錄) if 選項.工作目錄 else Path.cwd(), 選項.權限)
        對話: list[dict[str, Any]] = [{"role": "user", "content": 提示}]
        入計 = 出計 = 0
        for _ in range(最多工具回合):
            資料 = self._送出對話(對話, 型號=型號, 逾時秒=選項.逾時秒, 工具們=箱.規格())
            用了 = 資料.get("usage") or {}
            入計 += int(用了.get("prompt_tokens", 0))
            出計 += int(用了.get("completion_tokens", 0))
            訊息 = 資料["choices"][0]["message"]
            呼叫們 = 訊息.get("tool_calls") or []
            if not 呼叫們:
                return _讀成回應(資料, 入計=入計, 出計=出計)
            對話.append(訊息)
            對話.extend(_做完工具(箱, 呼叫們))
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


def _做完工具(箱: 工具箱, 呼叫們: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """跑完這一批工具呼叫，把結果做成 `role: "tool"` 的訊息。

    **工具出錯不讓整輪垮掉**——模型會叫不存在的檔案、會給越界的路徑，那是正常的
    不是異常。把錯誤訊息回給它，下一回合它就能改；整輪垮掉的話那次呼叫全白費。
    """
    結果們: list[dict[str, Any]] = []
    for 呼 in 呼叫們:
        函 = 呼.get("function") or {}
        try:
            參數 = json.loads(函.get("arguments") or "{}")
            內容 = 箱.執行(str(函.get("name", "")), 參數)
        except 工具錯誤 as 錯:
            內容 = f"工具失敗：{錯}"
        except json.JSONDecodeError as 錯:
            內容 = f"工具參數不是合法 JSON（{錯}）"
        結果們.append({"role": "tool", "tool_call_id": 呼.get("id", ""), "content": 內容})
    return 結果們


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

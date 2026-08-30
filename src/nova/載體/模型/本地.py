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
from dataclasses import dataclass
from os import environ
from typing import Any

from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.契約.角色 import 呼叫選項, 權限, 預設選項

#: 本機推論伺服器的預設位置。`NOVA_LOCAL_URL` 蓋得掉——
#: 那是**設定不是邏輯**（一個網址），所以放環境變數沒有違反
#: 「你的邏輯不准住在別人的設定檔裡」。
預設網址 = "http://127.0.0.1:8000/v1"
網址環境變數 = "NOVA_LOCAL_URL"

#: 家族名。ASCII——它會流進帳本的 `family` 欄位被 grep，
#: 屬於 CLAUDE.md 的「跨程序 semantic id」例外。
家族名 = "local"

_探型號逾時秒 = 5.0


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
            回來 = self._送出對話(提示, 型號=型號, 逾時秒=選項.逾時秒)
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
        return _讀成回應(回來)

    def _第一個型號(self, 逾時秒: float) -> str:
        """**不寫死型號**——寫死的話換一顆模型就要改 nova 的原始碼。"""
        表 = self._打(f"{self.網址}/models", 內容=None, 逾時秒=min(逾時秒, _探型號逾時秒))
        return str(表["data"][0]["id"])

    def _送出對話(self, 提示: str, *, 型號: str, 逾時秒: float) -> dict[str, Any]:
        return self._打(
            f"{self.網址}/chat/completions",
            內容={"model": 型號, "messages": [{"role": "user", "content": 提示}]},
            逾時秒=逾時秒,
        )

    def _打(self, 網址: str, *, 內容: dict[str, Any] | None, 逾時秒: float) -> dict[str, Any]:
        身體 = None if 內容 is None else json.dumps(內容).encode("utf-8")
        求 = urllib.request.Request(  # noqa: S310 —— 網址由設定給定，不吃模型輸出
            網址, data=身體, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(求, timeout=逾時秒) as 回:  # noqa: S310 —— 同上
            讀到: dict[str, Any] = json.loads(回.read().decode("utf-8"))
        return 讀到


def _做不到的地方(選項: 呼叫選項) -> str | None:
    """這顆腦撐不起來的要求。回 None ＝ 都撐得起來。"""
    if 選項.權限 is not 權限.唯讀:
        return (
            f"本地模型沒有工具，做不到 {選項.權限.value}——"
            "它只會回文字，不會編輯檔案。要改檔案就換一顆有工具的腦"
        )
    if 選項.續接:
        return "本地模型沒有 session，接不下去。要續接就換一顆有 session 的腦"
    return None


def _處理連線錯誤(網址: str, 逾時秒: float, 錯誤: urllib.error.URLError | OSError) -> 回應:
    """把連線失敗分成「未安裝」與「結果未知」。"""
    是逾時 = isinstance(錯誤, urllib.error.URLError) and isinstance(錯誤.reason, TimeoutError)
    if 是逾時:
        return _建立失敗回應(f"{網址} 超過 {逾時秒} 秒沒回應", 失敗代碼.逾時, 未知=True)
    return _建立失敗回應(f"連不上 {網址}（{錯誤}）", 失敗代碼.未安裝)


def _建立失敗回應(訊息: str, 代碼: 失敗代碼, *, 結束碼: int = 1, 未知: bool = False) -> 回應:
    return 回應(
        文字=訊息,
        終局=終局.結果未知 if 未知 else 終局.確定失敗,
        失敗代碼=代碼,
        原始結束碼=結束碼,
        對話識別碼=None,
        用量=用量(輸入token=0, 輸出token=0, 成本美金=0.0),
    )


def _讀成回應(回來: dict[str, Any]) -> 回應:
    用 = 回來.get("usage") or {}
    return 回應(
        文字=str(回來["choices"][0]["message"]["content"]),
        終局=終局.成功,
        失敗代碼=失敗代碼.無,
        原始結束碼=0,
        對話識別碼=回來.get("id"),
        用量=用量(
            輸入token=int(用.get("prompt_tokens", 0)),
            輸出token=int(用.get("completion_tokens", 0)),
            # 本地跑沒有 API 帳單。**事實不是估算。**
            成本美金=0.0,
        ),
    )

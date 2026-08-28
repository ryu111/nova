"""三家 LLM CLI 共用的證據 schema。

規格 §4.3：跨層傳遞一律 schema 化。自由段落會逼下游重建上游語意，
多階段之後歧義累積會改變結論——所以錯誤分類在這一層做完一次，不往下游丟原始訊息。

設計決定見 `docs/設計/02-統一LLM介面.md`。
"""

from dataclasses import dataclass, field
from typing import Any, Literal

# 失敗代碼要跨程序流動（CLI 輸出、日誌、CI），用 ASCII——CLAUDE.md 的 failure code 例外。
全部失敗代碼 = (
    "none",  # 沒有失敗
    "auth",  # 認證失敗
    "model-not-found",  # 指定的模型不存在
    "usage",  # 用法錯誤：旗標錯、參數錯
    "timeout",  # 逾時，由 nova 這邊殺掉
    "interrupted",  # 被中斷
    "upstream",  # 上游錯誤：429、5xx
    "unknown",  # 解析不出來。**這是 fail-closed 的落點**，不是「大概沒事」
)
失敗代碼 = Literal[
    "none",
    "auth",
    "model-not-found",
    "usage",
    "timeout",
    "interrupted",
    "upstream",
    "unknown",
]

# 終局是 at-most-once 的地基：**結果未知 ≠ 確定失敗**。
# 殺掉子程序時工作可能已經做了一半，把它當確定失敗，重試就會把可能做過的事再做一次。
全部終局 = ("success", "failed", "unknown")
終局 = Literal["success", "failed", "unknown"]

# 分界線是「請求出門了沒」——出門了就可能已經產生副作用。
# 寫成表不是寫成 if 鏈：加一個失敗代碼＝加一列，不是回來改判斷（開放封閉）。
# `全部失敗代碼` 的每一個都必須在這裡有一列，由 test_每個失敗代碼都要有明確的終局 背書。
_終局表: dict[str, 終局] = {
    "none": "success",
    "auth": "failed",  # 認證就被擋，沒出門
    "model-not-found": "failed",  # 模型不存在，沒出門
    "usage": "failed",  # 旗標錯，CLI 自己就退了
    "upstream": "unknown",  # 429／5xx：出門了，對面做了什麼不知道
    "timeout": "unknown",  # 被我們殺掉，可能做了一半
    "interrupted": "unknown",  # 同上
    "unknown": "unknown",  # 解析不出來，最保守的那一格
}


def 終局判定(代碼: 失敗代碼) -> 終局:
    """這個失敗可不可以重試？

    表裡沒有的代碼一律當 `unknown`——fail-closed。猜「大概可以重試」會重做副作用。

    從簡：`upstream` 把 429（確定沒做）和 5xx（可能做了）壓在一起，所以連 429 都
    不准重試。要放寬就把 `upstream` 拆成兩個代碼，等真的有重試迴圈嫌它太保守再拆。
    """
    return _終局表.get(代碼, "unknown")


@dataclass(frozen=True, slots=True)
class 用量:
    """一次呼叫花了多少。

    只有 claude 給成本，codex 與 agy 只有 token 數，所以 `成本美金` 可以是 None。
    **不准為了讓三家對稱而自己估算**——猜出來的成本比沒有成本更危險。
    """

    輸入token: int
    輸出token: int
    快取讀取token: int | None = None
    思考token: int | None = None
    成本美金: float | None = None


@dataclass(frozen=True, slots=True)
class 回應:
    """一次 LLM CLI 呼叫的結構化結果。

    兩件事刻意不做：

    1. **沒有 `成功` 欄位。** 三家 CLI 實測，模型拒答或答錯一律 exit 0——
       結束碼只分「跑完 vs 基礎設施壞掉」。任務成敗要由迴圈用證據判定（§3.2），
       不能由這一層給，否則就是「以模型說完成了當停止條件」。
    2. **`終局` 不是布林。** 布林會把「結果未知」壓成「確定失敗」，
       而那兩者的重試政策相反。
    """

    文字: str
    終局: 終局
    失敗代碼: 失敗代碼
    原始結束碼: int
    對話識別碼: str | None
    用量: 用量
    結構化輸出: dict[str, Any] | None = None
    #: 逃生艙：認不得的欄位不解析也要留著，下游要挖細節時才有東西可挖。
    原始輸出: tuple[dict[str, Any], ...] = field(default=())

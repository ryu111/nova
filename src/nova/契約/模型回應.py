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

    `執行成功` 刻意不叫 `成功`：三家 CLI 實測，模型拒答或答錯一律 exit 0，
    結束碼只分「跑完 vs 基礎設施壞掉」。任務成敗要由迴圈用證據判定（§3.2），
    不能由這一層給——那會變成「以模型說完成了當停止條件」。
    """

    文字: str
    執行成功: bool
    失敗代碼: 失敗代碼
    原始結束碼: int
    對話識別碼: str | None
    用量: 用量
    結構化輸出: dict[str, Any] | None = None
    #: 逃生艙：認不得的欄位不解析也要留著，下游要挖細節時才有東西可挖。
    原始輸出: tuple[dict[str, Any], ...] = field(default=())

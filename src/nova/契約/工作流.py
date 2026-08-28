"""工作流的契約：階段、步驟結果、結束。

規格 §4.3：跨層傳遞一律 schema 化。控制流程要能印進 journal，
所以階段與轉移都是**資料**，不是藏在函式裡的分支。

同 `模型回應`：全部用 `StrEnum`，識別字中文、值 ASCII。
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from nova.契約.模型回應 import 終局


class 階段代碼(StrEnum):
    """TDD 的五個階段。值跨程序流動（journal、CLI 輸出）所以是 ASCII。"""

    測試 = "test"
    驗證紅 = "verify-red"
    實作 = "impl"
    驗證綠 = "verify-green"
    審查 = "review"


class 種類(StrEnum):
    """這個階段由誰做。"""

    模型 = "llm"
    判準 = "gate"


class 結束代碼(StrEnum):
    """`中止` 不是「做壞了」，是「不該再往下走了」。"""

    完成 = "done"
    中止 = "aborted"


@dataclass(frozen=True, slots=True)
class 任務:
    """要被做完的一件事。"""

    描述: str
    工作目錄: Path


@dataclass(frozen=True, slots=True)
class 結束:
    """工作流的終點。"""

    代碼: 結束代碼
    原因: str


@dataclass(frozen=True, slots=True)
class 步驟結果:
    """一個階段跑完的結果。

    `終局` 回答「這一步跑完了嗎」（三值）；`判準綠` 回答「機械閘是綠的嗎」——
    只有判準階段有，模型階段是 None。兩個問題分開，因為答案會不一致：
    閘跑完了（終局成功）但結果是紅的。
    """

    階段: 階段代碼
    終局: 終局
    判準綠: bool | None
    證據: str


@dataclass(frozen=True, slots=True)
class 階段定義:
    """一個階段，以及它做完之後往哪走。

    `綠`／`紅` 指的是**達到期望與否**，不是「成功失敗」：
    `驗證紅` 期望的是紅，所以真的紅了才走 `綠` 那條路。
    """

    代碼: 階段代碼
    名稱: str
    種類: 種類
    #: 判準階段才有：True 期望全綠、False 期望紅。模型階段是 None。
    期望綠: bool | None
    綠: "階段代碼 | 結束"
    紅: "階段代碼 | 結束"

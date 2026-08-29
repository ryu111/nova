"""工作流的契約：階段、步驟結果、結束。

規格 §4.3：跨層傳遞一律 schema 化。控制流程要能印進 journal，
所以階段與轉移都是**資料**，不是藏在函式裡的分支。

同 `模型回應`：全部用 `StrEnum`，識別字中文、值 ASCII。
"""

from collections.abc import Callable
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
    """這個階段由誰做，以及**驗收權在誰手上**。

    這三個對應 Fowler 那套分類的三格（見 docs/設計/04-載體要長什麼樣.md）：

    | 種類 | 對應 | 驗收 |
    |---|---|---|
    | `模型` | inferential guide——它去做事 | 跑完就算 |
    | `判準` | computational sensor——機械跑一條指令 | 看退出碼 |
    | `審查` | inferential sensor——另一顆腦來挑毛病 | **看它給的判定** |

    `審查` 一度被歸在 `模型` 裡，後果是「跑完就算通過」——
    見 `審查判定` 的 docstring。
    """

    模型 = "llm"
    判準 = "gate"
    審查 = "review"


class 審查判定(StrEnum):
    """審查員給的結論。**沒給就是沒給，不准當成通過。**

    這個型別是被一次真實的假成功逼出來的：審查階段原本歸在 `種類.模型`，
    而模型階段的規則是「跑完就算達到期望」——所以審查員回
    「設計有重大問題，不通過」，只要 CLI 結束碼是 0，工作流照樣宣布
    「全綠且通過審查」。

    CLAUDE.md 硬規則第 4 條說不得以「模型說完成了」當停止條件。
    原本的實作比那還鬆：**它連模型有沒有說完成都不看，只看子程序有沒有跑完。**
    """

    通過 = "pass"
    要求修改 = "changes-requested"
    #: 讀不出約定的標記。fail-closed——由狀態機中止，不往下走也不重做。
    沒給結論 = "no-verdict"


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
    #: 只有審查階段有。同 `判準綠`——不適用的階段是 None。
    #: **欄位名不能跟型別名一樣**：dataclass 的 annotation 在 class 內部求值，
    #: 同名會讓 `審查判定 | None` 變成 `None | None`，當場 TypeError。
    審查結論: "審查判定 | None" = None


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


#: 跑一個階段。收軌跡是為了讓角色看得到前面發生什麼（七欄位的 Memory）。
執行器 = Callable[[階段定義, 任務, tuple[步驟結果, ...]], 步驟結果]
#: 機械判準：跑完回 (全綠嗎, 證據)。**不是模型**——驗收權不在執行者手上。
判準 = Callable[[任務], tuple[bool, str]]

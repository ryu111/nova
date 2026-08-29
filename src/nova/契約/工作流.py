"""工作流的契約：階段、步驟結果、結束。

規格 §4.3：跨層傳遞一律 schema 化。控制流程要能印進 journal，
所以階段與轉移都是**資料**，不是藏在函式裡的分支。

同 `模型回應`：全部用 `StrEnum`，識別字中文、值 ASCII。
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from nova.契約.模型回應 import 用量, 終局


class 階段代碼(StrEnum):
    """TDD 的五個階段。值跨程序流動（journal、CLI 輸出）所以是 ASCII。"""

    測試 = "test"
    驗證紅 = "verify-red"
    實作 = "impl"
    驗證綠 = "verify-green"
    #: 只清乾淨、不改行為。**做完一定要再驗一次綠**，否則「行為沒變」沒有背書。
    重構 = "refactor"
    #: 跟 `驗證綠` 長得一樣但**去處不同**——重用同一個代碼的話，
    #: 轉移函式就得記得「我是第幾次來的」，純函式當場破功。
    驗證重構 = "verify-refactor"
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
    #: 這一步花了多少。判準階段不叫模型，所以是 None——
    #: 補一個零上去會讓「沒花錢」跟「沒問到」長得一樣。
    花費: "用量 | None" = None


#: 預設走幾步就強制停。
#: 七個階段加三條回頭邊，最壞路徑約 16 步（測試↔驗證紅、實作↔驗證綠、審查→實作各一次）。
#: 抓 20 留一點餘裕。**加階段就要重算這個數**，不然一加就撞上限。
預設最多步數 = 20
#: 預設的 token 上限。**忘了傳不能等於沒有上限**——沒有預設的保證是懇求，不是保證。
#:
#: 這個數字的來源：02 實測十來字的提示，codex 一次要 17,341 input token、
#: agy 14,515（三家都自帶 system prompt，關不掉）。TDD 一輪最多 12 步、其中
#: 至多 8 步會叫模型，真實任務的提示又比實測大，所以抓每次 ~60k、共 500k。
#: 這是「跑得完正常一輪、擋得住失控」的量，不是精算。要改就在呼叫端明講。
預設最多token = 500_000


@dataclass(frozen=True, slots=True)
class 停止條件:
    """迴圈七欄位裡的 stop rule（§3.2）。缺它的不是迴圈，是成本漏洞。

    **兩個不同的洞，所以是兩個旋鈕**：步數擋「來回幾次」，token 擋「花多少」。
    一步可以很貴，光有步數上限對成本沒有任何保證。

    包成一個資料類別不是為了好看——stop rule 是契約的一部分，
    要能整包印進 journal、整包換掉，而不是散在函式簽章上的兩個 int。
    """

    最多步數: int = 預設最多步數
    最多token: int = 預設最多token


#: 不傳就是這個。frozen 且沒有可變欄位，所以共用一份是安全的
#: （ruff B008 不准把建構式寫進參數預設值，理由就是可變的預設會被共享）。
預設停止 = 停止條件()


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

"""節點與邊的契約：結構化輸入、輸出、證據與終局。"""

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import NewType, Protocol

from nova.契約.工作流 import 任務
from nova.契約.模型回應 import 失敗代碼, 用量

執行識別碼 = NewType("執行識別碼", str)
工作流識別碼 = NewType("工作流識別碼", str)
節點識別碼 = NewType("節點識別碼", str)
分支識別碼 = NewType("分支識別碼", str)
邊識別碼 = NewType("邊識別碼", str)
結構識別碼 = NewType("結構識別碼", str)


class 結果代碼(IntEnum):
    """節點的四種終局退出碼。"""

    成功 = 0
    確定失敗 = 1
    結果未知 = 3
    護欄 = 4


class 護欄原因(StrEnum):
    """節點因停止政策而停止的原因。"""

    預算 = "budget"
    步數 = "steps"
    逾時 = "timeout"
    無進展 = "stagnation"
    扇出超限 = "fanout-limit"
    輸出不合約 = "invalid-output"


@dataclass(frozen=True, slots=True)
class 停止政策:
    """節點可使用的資源與重跑政策。"""

    最多呼叫: int
    最多token: int
    最多秒: float
    最多無進展: int
    結果未知不重跑: bool = True


@dataclass(frozen=True, slots=True)
class 證據來源:
    """證據的執行追溯來源。"""

    執行: 執行識別碼
    工作流: 工作流識別碼 | None
    分支: 分支識別碼
    節點: 節點識別碼
    嘗試: int
    父邊: tuple[邊識別碼, ...]


@dataclass(frozen=True, slots=True)
class 邊包[輸入]:
    """沿邊傳遞的具版本結構化內容。"""

    結構: 結構識別碼
    版本: int
    內容: 輸入
    來源: 證據來源


@dataclass(frozen=True, slots=True)
class 節點錯誤:
    """節點失敗的結構化診斷。"""

    代碼: 失敗代碼
    診斷: str
    可能已產生副作用: bool


@dataclass(frozen=True, slots=True)
class 證據項:
    """節點結果引用的證據摘要。"""

    識別碼: 邊識別碼
    類型: 結構識別碼
    摘要: str


@dataclass(frozen=True, slots=True)
class 節點成功[輸出]:
    """節點成功時可交給下游的結果。"""

    產出: 邊包[輸出]
    證據: tuple[證據項, ...]
    用量: 用量 | None

    @property
    def 結果(self) -> 結果代碼:
        """回傳成功終局。"""
        return 結果代碼.成功


@dataclass(frozen=True, slots=True)
class 節點確定失敗:
    """節點已確定失敗的結果。"""

    錯誤: 節點錯誤
    證據: tuple[證據項, ...]

    @property
    def 結果(self) -> 結果代碼:
        """回傳確定失敗終局。"""
        return 結果代碼.確定失敗


@dataclass(frozen=True, slots=True)
class 節點結果未知:
    """節點是否完成無法確定的結果。"""

    錯誤: 節點錯誤
    已知證據: tuple[證據項, ...]
    用量: 用量 | None

    @property
    def 結果(self) -> 結果代碼:
        """回傳結果未知終局。"""
        return 結果代碼.結果未知


@dataclass(frozen=True, slots=True)
class 節點護欄:
    """節點因護欄政策停止的結果。"""

    原因: 護欄原因
    已知證據: tuple[證據項, ...]
    用量: 用量 | None

    @property
    def 結果(self) -> 結果代碼:
        """回傳護欄終局。"""
        return 結果代碼.護欄


type 節點結果[輸出] = 節點成功[輸出] | 節點確定失敗 | 節點結果未知 | 節點護欄


@dataclass(frozen=True, slots=True)
class 節點上下文:
    """由呼叫者明傳給節點的任務、追溯與停止政策。"""

    任務: 任務
    執行: 執行識別碼
    工作流: 工作流識別碼 | None
    節點: 節點識別碼
    分支: 分支識別碼
    父邊: tuple[邊識別碼, ...]
    嘗試: int
    停止: 停止政策


class 節點[輸入, 輸出, 依賴](Protocol):
    """可被單獨呼叫或組裝的節點介面。"""

    @property
    def 識別碼(self) -> 節點識別碼:
        """回傳節點識別碼。"""
        ...

    def 執行(
        self,
        輸入: 邊包[輸入],
        *,
        上下文: 節點上下文,
        依賴: 依賴,
    ) -> 節點結果[輸出]:
        """以呼叫者提供的上下文與依賴執行節點。"""
        ...


def 執行節點[輸入, 輸出, 依賴](
    節點: 節點[輸入, 輸出, 依賴],
    輸入: 邊包[輸入],
    *,
    上下文: 節點上下文,
    依賴: 依賴,
) -> 節點結果[輸出]:
    """用明傳的上下文與依賴執行一個節點。"""
    return 節點.執行(輸入, 上下文=上下文, 依賴=依賴)

"""扇出節點的分支、政策與結果契約。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from nova.契約.節點 import 分支識別碼, 節點結果, 結果代碼, 邊包


@dataclass(frozen=True, slots=True)
class 分支工作[輸入, 依賴]:
    """一顆分支要執行的輸入與依賴。"""

    分支: 分支識別碼
    輸入: 邊包[輸入]
    依賴: 依賴
    必要: bool


class 扇出模式(StrEnum):
    """扇出結果的交付形狀；串流保留給第二版，runner 目前拒絕。"""

    屏障 = "barrier"
    串流 = "stream"


@dataclass(frozen=True, slots=True)
class 扇出政策:
    """扇出數量、並行度與成本上限；目前每個分支最多派送一次。"""

    最大分支數: int
    最大並行數: int
    最少成功數: int
    必要分支: frozenset[分支識別碼]
    每分支最多token: int
    階段最多token: int
    最多秒: float
    最多呼叫: int
    模式: 扇出模式 = 扇出模式.屏障


@dataclass(frozen=True, slots=True)
class 分支結果[輸出]:
    """一顆分支的結果。"""

    分支: 分支識別碼
    結果: 節點結果[輸出]


@dataclass(frozen=True, slots=True)
class 扇出結果[輸出]:
    """屏障收齊後的扇出結果；缺口包含未回來或已回來但不成功的分支。"""

    分支結果: tuple[分支結果[輸出], ...]
    成功產出: tuple[邊包[輸出], ...]
    缺口: tuple[分支識別碼, ...]
    終局: 結果代碼

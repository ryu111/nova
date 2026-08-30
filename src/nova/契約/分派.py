"""可驗證的分派單契約。"""

from dataclasses import dataclass
from enum import StrEnum

from nova.契約.節點 import 停止政策, 分支識別碼, 節點識別碼, 結構識別碼


class 分派問題代碼(StrEnum):
    """分派單可以被拒絕的原因。"""

    未知節點 = "unknown-node"
    輸入結構錯誤 = "input-schema-mismatch"
    依賴不存在 = "dependency-missing"
    重複項目 = "duplicate-item"
    循環前置 = "cyclic-predecessor"
    超出扇出上限 = "fanout-limit"
    超出預算 = "budget-limit"
    缺停止政策 = "missing-stop-policy"
    缺驗收條件 = "missing-acceptance"
    權限不足 = "permission-denied"
    空分派單 = "empty-plan"


@dataclass(frozen=True, slots=True)
class 分派單問題:
    """一個可供 host 診斷的分派單問題。"""

    代碼: 分派問題代碼
    項目: str | None
    診斷: str


@dataclass(frozen=True, slots=True)
class 分派項目:
    """分派單中的一格工作。"""

    識別碼: str
    節點: 節點識別碼
    輸入結構: 結構識別碼
    前置項目: tuple[str, ...]
    分支: 分支識別碼 | None
    必要: bool
    停止: 停止政策 | None
    驗收出口: tuple[str, ...]
    需要網路: bool = False
    需要編輯: bool = False


@dataclass(frozen=True, slots=True)
class 分派單:
    """PlanWorker 交給 host 驗證的有限分派資料。"""

    版本: int
    項目: tuple[分派項目, ...]
    最大分支數: int
    總停止: 停止政策 | None

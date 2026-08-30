"""PlanWorker 的輸入資料與分派單確定性驗證。"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nova.契約.分派 import 分派問題代碼, 分派單, 分派單問題, 分派項目
from nova.契約.模型回應 import 用量
from nova.契約.節點 import (
    停止政策,
    節點上下文,
    節點成功,
    節點結果,
    節點識別碼,
    結構識別碼,
    證據來源,
    證據項,
    邊包,
)


@dataclass(frozen=True, slots=True)
class 工件參照:
    """PlanWorker 可引用的既有工件。"""

    識別碼: str
    結構: 結構識別碼
    路徑: Path | None


@dataclass(frozen=True, slots=True)
class 工作現況:
    """PlanWorker 看到的工作現況。"""

    工作目錄: Path
    已有工件: tuple[工件參照, ...]
    已有證據: tuple[證據項, ...]
    目前節點: 節點識別碼 | None
    缺口: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class 執行限制:
    """host 交給 PlanWorker 的執行限制。"""

    停止: 停止政策
    允許網路: bool
    允許編輯: bool
    可用節點: tuple[節點識別碼, ...]
    可用結構: tuple[結構識別碼, ...]
    最大分支數: int


@dataclass(frozen=True, slots=True)
class 規劃輸入:
    """PlanWorker 的結構化輸入。"""

    目標: str
    現況: 工作現況
    限制: 執行限制
    可用工件: tuple[工件參照, ...]
    架構: object | None


type 計畫結果 = 節點結果[分派單]
type 計畫產生器 = Callable[[規劃輸入], 分派單 | tuple[分派單, 用量 | None]]

分派單結構 = 結構識別碼("分派單")
分派單版本 = 1


def 執行計畫員(
    輸入: 邊包[規劃輸入],
    *,
    上下文: 節點上下文,
    依賴: 計畫產生器,
) -> 計畫結果:
    """只產出一張候選分派單；host 仍須先呼叫驗證器。"""
    產出 = 依賴(輸入.內容)
    if isinstance(產出, tuple):
        候選, 使用量 = 產出
    else:
        候選, 使用量 = 產出, None
    來源 = 證據來源(
        執行=上下文.執行,
        工作流=上下文.工作流,
        分支=上下文.分支,
        節點=上下文.節點,
        嘗試=上下文.嘗試,
        父邊=上下文.父邊,
    )
    return 節點成功(
        產出=邊包(
            結構=分派單結構,
            版本=分派單版本,
            內容=候選,
            來源=來源,
        ),
        證據=(),
        用量=使用量,
    )


def 驗證分派單(
    候選: 分派單,
    *,
    限制: 執行限制 | None = None,
    可用節點: frozenset[節點識別碼] | None = None,
    可用結構: frozenset[結構識別碼] | None = None,
    總限制: 停止政策 | None = None,
) -> tuple[分派單問題, ...]:
    """以固定順序找出所有不能執行的分派單問題。

    `限制` 是正式介面，包含所有 host 清單與上限。其餘 keyword 只保留給既有
    呼叫者相容；同時提供 `限制` 時，以 `限制` 為準。相容路徑沒有 host 扇出
    上限，含分支的候選會直接被拒絕，不會採用候選自己的上限。
    """
    主機停止政策: 停止政策 | None
    主機最大分支數: int | None
    if 限制 is not None:
        可用節點 = frozenset(限制.可用節點)
        可用結構 = frozenset(限制.可用結構)
        主機停止政策 = 限制.停止
        主機最大分支數 = 限制.最大分支數
    else:
        主機停止政策 = 總限制
        主機最大分支數 = None
    可用節點 = frozenset() if 可用節點 is None else 可用節點
    可用結構 = frozenset() if 可用結構 is None else 可用結構
    問題: list[分派單問題] = []
    問題.extend(_檢查項目識別碼(候選.項目))
    問題.extend(_檢查節點與結構(候選.項目, 可用節點, 可用結構))
    問題.extend(_檢查前置(候選.項目))
    問題.extend(_檢查停止與驗收(候選))
    問題.extend(_檢查權限(候選.項目, 限制))
    問題.extend(_檢查扇出(候選, 主機最大分支數))
    問題.extend(_檢查預算(候選, 主機停止政策))
    return tuple(問題)


def _檢查項目識別碼(項目們: tuple[分派項目, ...]) -> tuple[分派單問題, ...]:
    """檢查項目識別碼是否唯一。"""
    已見: set[str] = set()
    問題: list[分派單問題] = []
    for 項目 in 項目們:
        if 項目.識別碼 in 已見:
            問題.append(
                分派單問題(
                    分派問題代碼.重複項目,
                    項目.識別碼,
                    f"項目識別碼重複：{項目.識別碼}",
                )
            )
        已見.add(項目.識別碼)
    return tuple(問題)


def _檢查節點與結構(
    項目們: tuple[分派項目, ...],
    可用節點: frozenset[節點識別碼],
    可用結構: frozenset[結構識別碼],
) -> tuple[分派單問題, ...]:
    """檢查節點與輸入結構是否由 host 宣告。"""
    問題: list[分派單問題] = []
    for 項目 in 項目們:
        if 項目.節點 not in 可用節點:
            問題.append(
                分派單問題(
                    分派問題代碼.未知節點,
                    項目.識別碼,
                    f"節點不在 host 清單：{項目.節點}",
                )
            )
        if 項目.輸入結構 not in 可用結構:
            問題.append(
                分派單問題(
                    分派問題代碼.輸入結構錯誤,
                    項目.識別碼,
                    f"輸入結構不在 host 清單：{項目.輸入結構}",
                )
            )
    return tuple(問題)


def _檢查前置(項目們: tuple[分派項目, ...]) -> tuple[分派單問題, ...]:
    """檢查前置項目存在且沒有循環。"""
    項目識別碼們 = {項目.識別碼 for 項目 in 項目們}
    問題: list[分派單問題] = []
    for 項目 in 項目們:
        問題.extend(
            分派單問題(
                分派問題代碼.依賴不存在,
                項目.識別碼,
                f"前置項目不存在：{前置}",
            )
            for 前置 in 項目.前置項目
            if 前置 not in 項目識別碼們
        )
    if _有循環(項目們):
        問題.append(分派單問題(分派問題代碼.循環前置, None, "前置項目形成循環"))
    return tuple(問題)


def _有循環(項目們: tuple[分派項目, ...]) -> bool:
    """回傳前置圖是否有循環。"""
    前置圖 = {項目.識別碼: 項目.前置項目 for 項目 in 項目們}
    已完成: set[str] = set()

    def 檢查路徑(識別碼: str, 目前路徑: frozenset[str]) -> bool:
        if 識別碼 in 目前路徑:
            return True
        if 識別碼 in 已完成:
            return False
        新路徑 = 目前路徑 | {識別碼}
        if any(檢查路徑(前置, 新路徑) for 前置 in 前置圖.get(識別碼, ())):
            return True
        已完成.add(識別碼)
        return False

    return any(檢查路徑(項目.識別碼, frozenset()) for 項目 in 項目們)


def _檢查權限(
    項目們: tuple[分派項目, ...],
    限制: 執行限制 | None,
) -> tuple[分派單問題, ...]:
    """檢查項目要求的權限沒有超過 host 限制。"""
    if 限制 is None:
        return tuple(
            分派單問題(
                分派問題代碼.權限不足,
                項目.識別碼,
                "項目要求權限，但未提供 host 權限限制",
            )
            for 項目 in 項目們
            if 項目.需要網路 or 項目.需要編輯
        )
    問題: list[分派單問題] = []
    for 項目 in 項目們:
        if 項目.需要網路 and not 限制.允許網路:
            問題.append(
                分派單問題(
                    分派問題代碼.權限不足,
                    項目.識別碼,
                    "項目需要網路，但 host 未允許網路",
                )
            )
        if 項目.需要編輯 and not 限制.允許編輯:
            問題.append(
                分派單問題(
                    分派問題代碼.權限不足,
                    項目.識別碼,
                    "項目需要編輯，但 host 未允許編輯",
                )
            )
    return tuple(問題)


def _檢查停止與驗收(候選: 分派單) -> tuple[分派單問題, ...]:
    """檢查總停止政策、逐項停止政策與驗收出口。"""
    問題: list[分派單問題] = []
    if not 候選.項目:
        問題.append(分派單問題(分派問題代碼.空分派單, None, "分派單不可為空"))
    if 候選.總停止 is None:
        問題.append(分派單問題(分派問題代碼.缺停止政策, None, "分派單缺少總停止政策"))
    for 項目 in 候選.項目:
        if 項目.停止 is None:
            問題.append(分派單問題(分派問題代碼.缺停止政策, 項目.識別碼, "項目缺少停止政策"))
        if not 項目.驗收出口:
            問題.append(分派單問題(分派問題代碼.缺驗收條件, 項目.識別碼, "項目缺少驗收出口"))
    return tuple(問題)


def _檢查扇出(候選: 分派單, 主機最大分支數: int | None) -> tuple[分派單問題, ...]:
    """檢查實際與候選宣告的分支數沒有超過 host 上限。"""
    分支數 = sum(項目.分支 is not None for 項目 in 候選.項目)
    if 分支數 == 0:
        return ()
    if 主機最大分支數 is None or 分支數 > 主機最大分支數 or 候選.最大分支數 > 主機最大分支數:
        上限 = "未提供" if 主機最大分支數 is None else str(主機最大分支數)
        return (
            分派單問題(
                分派問題代碼.超出扇出上限,
                None,
                f"分支數 {分支數} 超過 host 分支上限 {上限}",
            ),
        )
    return ()


def _檢查預算(候選: 分派單, 主機停止政策: 停止政策 | None) -> tuple[分派單問題, ...]:
    """分開檢查自報總額與項目加總；最多無進展不可跨項目相加。"""
    分派單總停止 = 候選.總停止
    if 分派單總停止 is None:
        return ()
    if 主機停止政策 is None:
        return (
            分派單問題(
                分派問題代碼.超出預算,
                None,
                "驗證分派單缺少 host 預算限制",
            ),
        )
    分派單總額超過主機 = (
        分派單總停止.最多呼叫 > 主機停止政策.最多呼叫
        or 分派單總停止.最多token > 主機停止政策.最多token
        or 分派單總停止.最多秒 > 主機停止政策.最多秒
    )
    項目停止政策們 = tuple(項目.停止 for 項目 in 候選.項目 if 項目.停止 is not None)
    項目總呼叫 = sum(政策.最多呼叫 for 政策 in 項目停止政策們)
    項目總token = sum(政策.最多token for 政策 in 項目停止政策們)
    項目總秒數 = sum(政策.最多秒 for 政策 in 項目停止政策們)
    項目總額超過分派單 = (
        項目總呼叫 > 分派單總停止.最多呼叫
        or 項目總token > 分派單總停止.最多token
        or 項目總秒數 > 分派單總停止.最多秒
    )
    問題: list[分派單問題] = []
    if 分派單總額超過主機:
        問題.append(
            分派單問題(
                分派問題代碼.超出預算,
                None,
                "分派單自報總額超過主機上限",
            )
        )
    if 項目總額超過分派單:
        問題.append(
            分派單問題(
                分派問題代碼.超出預算,
                None,
                "項目預算加總超過分派單自報總額",
            )
        )
    return tuple(問題)

"""扇出節點 runner：有界派送，固定以屏障收斂。"""

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from time import monotonic

from nova.契約.扇出 import 分支工作, 分支結果, 扇出政策, 扇出模式, 扇出結果
from nova.契約.節點 import (
    分支識別碼,
    節點上下文,
    節點成功,
    節點確定失敗,
    節點結果,
    節點護欄,
    結果代碼,
)


@dataclass(slots=True)
class _用量累計:
    """扇出 runner 自己持有的階段總用量。"""

    總token: int = 0

    def 加入[輸出](self, 結果: 節點結果[輸出]) -> int:
        """記下結果的用量；確定失敗沒有用量，不計入總額。"""
        if isinstance(結果, 節點確定失敗):
            return 0
        if 結果.用量 is None:
            return 0
        花費 = 結果.用量.總token
        self.總token += 花費
        return 花費


def 執行扇出[輸入, 輸出, 依賴](
    工作: tuple[分支工作[輸入, 依賴], ...],
    *,
    執行一顆: Callable[
        [分支工作[輸入, 依賴], 節點上下文],
        節點結果[輸出],
    ],
    上下文: 節點上下文,
    政策: 扇出政策,
) -> 扇出結果[輸出]:
    """執行分支並等屏障收齊，再決定整階終局。"""
    _驗證輸入(工作, 政策)
    已回收結果: dict[分支識別碼, 節點結果[輸出]] = {}
    進行中: dict[Future[節點結果[輸出]], 分支工作[輸入, 依賴]] = {}
    下一個 = 0
    用量累計 = _用量累計()
    已呼叫 = 0
    已觸發護欄 = False
    開始 = monotonic()

    def _盡量派送() -> None:
        nonlocal 下一個, 已呼叫, 已觸發護欄
        while 下一個 < len(工作) and len(進行中) < 政策.最大並行數 and not 已觸發護欄:
            if _上限阻止再派一顆(已呼叫, 用量累計.總token, len(進行中), 開始, 政策):
                已觸發護欄 = True
                break
            工作項 = 工作[下一個]
            下一個 += 1
            未來 = 執行池.submit(
                執行一顆,
                工作項,
                replace(上下文, 分支=工作項.分支),
            )
            進行中[未來] = 工作項
            已呼叫 += 1

    with ThreadPoolExecutor(max_workers=max(1, 政策.最大並行數)) as 執行池:
        while 下一個 < len(工作) or 進行中:
            _盡量派送()

            if not 進行中:
                break

            本批觸發護欄 = _收回完成分支(
                進行中,
                已回收結果,
                用量累計,
                政策,
            )
            已觸發護欄 = 已觸發護欄 or 本批觸發護欄

            if monotonic() - 開始 >= 政策.最多秒:
                已觸發護欄 = True

    return _收斂(工作, 已回收結果, 已觸發護欄, 政策)


def _驗證輸入[輸入, 依賴](
    工作: tuple[分支工作[輸入, 依賴], ...],
    政策: 扇出政策,
) -> None:
    """拒絕無法完整執行的扇出計畫。"""
    if 政策.模式 is not 扇出模式.屏障:
        訊息 = "第一版扇出只接受屏障模式"
        raise ValueError(訊息)
    if (
        政策.最大分支數 < 0
        or 政策.最大並行數 <= 0
        or 政策.最多呼叫 < 0
        or 政策.最少成功數 < 0
        or 政策.最多秒 < 0
        or 政策.每分支最多token < 0
        or 政策.階段最多token < 0
    ):
        訊息 = "扇出政策的上限與並行數必須有效"
        raise ValueError(訊息)
    if len(工作) > 政策.最大分支數:
        訊息 = "扇出分支數超過固定上限"
        raise ValueError(訊息)
    if len({工作項.分支 for 工作項 in 工作}) != len(工作):
        訊息 = "扇出分支識別碼不可重複"
        raise ValueError(訊息)
    實際必要 = frozenset(工作項.分支 for 工作項 in 工作 if 工作項.必要)
    if 實際必要 != 政策.必要分支:
        訊息 = "扇出必要分支與分派資料不一致"
        raise ValueError(訊息)
    if len(工作) * 政策.每分支最多token > 政策.階段最多token:
        訊息 = "扇出階段總預算無法容納全部分支"
        raise ValueError(訊息)


def _收回完成分支[輸入, 輸出, 依賴](
    進行中: dict[Future[節點結果[輸出]], 分支工作[輸入, 依賴]],
    已回收結果: dict[分支識別碼, 節點結果[輸出]],
    用量累計: _用量累計,
    政策: 扇出政策,
) -> bool:
    """整理一批完成的分支，並更新 runner 持有的階段總額。"""
    完成, _ = wait(進行中, return_when=FIRST_COMPLETED)
    本批觸發護欄 = False
    for 未來 in 完成:
        工作項 = 進行中.pop(未來)
        結果 = 未來.result()
        已回收結果[工作項.分支] = 結果
        花費 = 用量累計.加入(結果)
        if 花費 > 政策.每分支最多token:
            本批觸發護欄 = True
        if 用量累計.總token > 政策.階段最多token or isinstance(結果, 節點護欄):
            本批觸發護欄 = True
    return 本批觸發護欄


def _上限阻止再派一顆(
    已呼叫: int,
    已花token: int,
    進行中數: int,
    開始: float,
    政策: 扇出政策,
) -> bool:
    """判斷政策上限是否阻止再派一顆分支。"""
    預留中的分支數 = 進行中數 + 1
    return (
        已呼叫 >= 政策.最多呼叫
        or 已花token >= 政策.階段最多token
        or 已花token + 預留中的分支數 * 政策.每分支最多token > 政策.階段最多token
        or monotonic() - 開始 >= 政策.最多秒
    )


def _收斂[輸入, 輸出, 依賴](
    工作: tuple[分支工作[輸入, 依賴], ...],
    已回收結果: dict[分支識別碼, 節點結果[輸出]],
    已觸發護欄: bool,
    政策: 扇出政策,
) -> 扇出結果[輸出]:
    """整理已回收結果，再委派終局判定。"""
    已回收分支結果: list[分支結果[輸出]] = []
    成功產出 = []
    未成功分支: list[分支識別碼] = []
    必要分支未回 = False
    必要分支結果代碼: set[結果代碼] = set()
    成功數 = 0

    for 工作項 in 工作:
        結果 = 已回收結果.get(工作項.分支)
        if 結果 is None:
            未成功分支.append(工作項.分支)
            必要分支未回 |= 工作項.必要
            continue

        已回收分支結果.append(分支結果(分支=工作項.分支, 結果=結果))
        if isinstance(結果, 節點成功):
            成功數 += 1
            成功產出.append(結果.產出)
        else:
            未成功分支.append(工作項.分支)

        if 工作項.必要:
            必要分支結果代碼.add(結果.結果)

    終局 = _決定終局(
        已觸發護欄=已觸發護欄,
        必要分支未回=必要分支未回,
        必要分支結果代碼=必要分支結果代碼,
        成功數=成功數,
        政策=政策,
    )

    return 扇出結果(
        分支結果=tuple(已回收分支結果),
        成功產出=tuple(成功產出),
        缺口=tuple(未成功分支),
        終局=終局,
    )


def _決定終局(
    *,
    已觸發護欄: bool,
    必要分支未回: bool,
    必要分支結果代碼: set[結果代碼],
    成功數: int,
    政策: 扇出政策,
) -> 結果代碼:
    """依未知、護欄、確定失敗、成功的風險順序決定整階終局。"""
    if 結果代碼.結果未知 in 必要分支結果代碼:
        return 結果代碼.結果未知
    if 已觸發護欄 or 必要分支未回 or 結果代碼.護欄 in 必要分支結果代碼:
        return 結果代碼.護欄
    if 結果代碼.確定失敗 in 必要分支結果代碼 or 成功數 < 政策.最少成功數:
        return 結果代碼.確定失敗
    return 結果代碼.成功

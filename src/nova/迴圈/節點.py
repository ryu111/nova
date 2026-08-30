"""節點的單獨執行器。"""

from time import monotonic

from nova.契約.工作流 import 任務
from nova.契約.模型回應 import 用量
from nova.契約.節點 import (
    停止政策,
    分支識別碼,
    執行節點,
    執行識別碼,
    節點上下文,
    節點成功,
    節點確定失敗,
    節點結果,
    節點結果未知,
    節點識別碼,
    節點護欄,
    證據來源,
    證據項,
    護欄原因,
    邊包,
)
from nova.契約.節點 import 節點 as 節點介面


def 根上下文(
    任務: 任務,
    節點: 節點識別碼,
    執行: 執行識別碼,
    停止: 停止政策,
) -> 節點上下文:
    """建立單獨執行固定使用的 root 上下文。"""
    return 節點上下文(
        任務=任務,
        執行=執行,
        工作流=None,
        節點=節點,
        分支=分支識別碼("root"),
        父邊=(),
        嘗試=1,
        停止=停止,
    )


def 單獨執行[輸入, 輸出, 依賴](
    節點: 節點介面[輸入, 輸出, 依賴],
    輸入: 邊包[輸入],
    *,
    上下文: 節點上下文,
    依賴: 依賴,
) -> 節點結果[輸出]:
    """執行一次節點，並讓可觀測的停止政策在這一層生效。"""
    停止 = 上下文.停止
    if 停止.最多呼叫 < 1:
        return 節點護欄(原因=護欄原因.步數, 已知證據=(), 用量=None)
    if 停止.最多秒 <= 0:
        return 節點護欄(原因=護欄原因.逾時, 已知證據=(), 用量=None)

    開始 = monotonic()
    結果 = 執行節點(節點, 輸入, 上下文=上下文, 依賴=依賴)
    if not _結果合約正確(結果, 上下文=上下文):
        return 節點護欄(原因=護欄原因.輸出不合約, 已知證據=(), 用量=None)

    # 單獨 runner 沒有第二次呼叫；結果未知也不能被改成可重跑的結果。
    if isinstance(結果, 節點結果未知) and 上下文.停止.結果未知不重跑:
        return 結果

    return _套用停止政策(結果, 輸入, 停止=停止, 開始=開始)


def _套用停止政策[輸入, 輸出](
    結果: 節點結果[輸出],
    輸入: 邊包[輸入],
    *,
    停止: 停止政策,
    開始: float,
) -> 節點結果[輸出]:
    """套用單次呼叫後能由 runner 判定的停止條件。"""
    已知證據 = _已知證據(結果)
    使用量 = _結果用量(結果)
    if 使用量 is not None and 使用量.總token > 停止.最多token:
        return 節點護欄(原因=護欄原因.預算, 已知證據=已知證據, 用量=使用量)
    if monotonic() - 開始 > 停止.最多秒:
        return 節點護欄(原因=護欄原因.逾時, 已知證據=已知證據, 用量=使用量)
    if isinstance(結果, 節點成功) and 結果.產出 is 輸入 and 停止.最多無進展 < 1:
        return 節點護欄(原因=護欄原因.無進展, 已知證據=結果.證據, 用量=使用量)
    return 結果


def _結果合約正確(結果: object, *, 上下文: 節點上下文) -> bool:
    if isinstance(結果, 節點成功):
        return (
            _邊包合約正確(結果.產出, 上下文=上下文)
            and _證據合約正確(結果.證據)
            and _用量合約正確(結果.用量)
        )
    if isinstance(結果, 節點確定失敗):
        return _證據合約正確(結果.證據)
    if isinstance(結果, (節點結果未知, 節點護欄)):
        return _證據合約正確(結果.已知證據) and _用量合約正確(結果.用量)
    return False


def _邊包合約正確(邊: object, *, 上下文: 節點上下文) -> bool:
    if not isinstance(邊, 邊包) or not isinstance(邊.結構, str) or not 邊.結構:
        return False
    if not isinstance(邊.版本, int) or 邊.版本 < 1:
        return False
    return _來源合約正確(邊.來源, 上下文=上下文)


def _來源合約正確(來源: object, *, 上下文: 節點上下文) -> bool:
    return (
        isinstance(來源, 證據來源)
        and isinstance(來源.執行, str)
        and bool(來源.執行)
        and 來源.執行 == 上下文.執行
        and 來源.工作流 == 上下文.工作流
        and isinstance(來源.分支, str)
        and bool(來源.分支)
        and 來源.分支 == 上下文.分支
        and isinstance(來源.節點, str)
        and bool(來源.節點)
        and 來源.節點 == 上下文.節點
        and isinstance(來源.嘗試, int)
        and 來源.嘗試 >= 1
        and 來源.嘗試 == 上下文.嘗試
        and isinstance(來源.父邊, tuple)
        and all(isinstance(父邊, str) and 父邊 for 父邊 in 來源.父邊)
    )


def _證據合約正確(證據: object) -> bool:
    return isinstance(證據, tuple) and all(
        isinstance(項, 證據項)
        and isinstance(項.識別碼, str)
        and bool(項.識別碼)
        and isinstance(項.類型, str)
        and bool(項.類型)
        and isinstance(項.摘要, str)
        for 項 in 證據
    )


def _用量合約正確(使用量: object) -> bool:
    return 使用量 is None or isinstance(使用量, 用量)


def _已知證據(結果: 節點結果[object]) -> tuple[證據項, ...]:
    if isinstance(結果, (節點成功, 節點確定失敗)):
        return 結果.證據
    return 結果.已知證據


def _結果用量(結果: object) -> 用量 | None:
    if isinstance(結果, (節點成功, 節點結果未知, 節點護欄)):
        return 結果.用量
    return None

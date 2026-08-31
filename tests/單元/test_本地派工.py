"""本地腦的派工邊界。"""

from nova.契約.派工 import 工作種類
from nova.載體.模型.本地 import 家族名 as 本地家族名
from nova.載體.派工表 import 怎麼派


def test_本地腦只作例行最後備援() -> None:
    """能力邊界尚未證明，所以 local 只在例行鏈最後，不能進推理列。"""
    assert 怎麼派(工作種類.例行).腦們[-1] == 本地家族名
    assert 本地家族名 not in 怎麼派(工作種類.推理).腦們

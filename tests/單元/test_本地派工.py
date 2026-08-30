"""本地腦的派工邊界。"""

from nova.契約.派工 import 工作種類
from nova.載體.模型.本地 import 家族名 as 本地家族名
from nova.載體.派工表 import 怎麼派


def test_能力未量到前本地腦只保留手動指定() -> None:
    """量測未證明適合自動派工前，本地腦不能出現在任何派工列。"""
    有本地腦的工作種類 = [種 for 種 in 工作種類 if 本地家族名 in 怎麼派(種).腦們]

    assert not 有本地腦的工作種類

"""閘：在一個執行點上，跑完該跑的規則並誠實判定。

閘是驗證迴圈（規格 §3.1），不是重試迴圈——一輪就停，修理是呼叫端的事。
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from nova.契約.檢查結果 import 檢查結果

檢查函式 = Callable[[], tuple[bool, str]]

# 閘點＝執行點。打錯名字要當場爆，不能靜默跑零條規則然後全綠。
閘點清單 = frozenset({"提交", "ci", "指令"})


@dataclass(frozen=True, slots=True)
class 規則:
    代碼: str
    名稱: str
    閘點: frozenset[str]
    負責層: str
    檢查: 檢查函式


def 跑閘(閘點: str, 規則表: Sequence[規則]) -> list[檢查結果]:
    """跑掛在這個閘點上的所有規則，回傳每一條的判定。

    規則自己爆掉一律算紅（fail-closed）——檢查壞了卻放行，等於保證靜默消失。
    """
    if 閘點 not in 閘點清單:
        raise ValueError(f"未知的閘點：{閘點}（可用：{'、'.join(sorted(閘點清單))}）")

    結果表: list[檢查結果] = []
    for 條 in 規則表:
        if 閘點 not in 條.閘點:
            continue
        try:
            通過, 證據 = 條.檢查()
        except Exception as 錯:  # noqa: BLE001 —— 任何例外都算紅，這是刻意的
            通過, 證據 = False, f"規則自己爆了：{錯}"
        結果表.append(
            檢查結果(
                代碼=條.代碼,
                名稱=條.名稱,
                通過=通過,
                負責層=條.負責層,
                證據=證據,
            )
        )
    return 結果表

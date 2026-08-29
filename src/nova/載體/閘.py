"""閘：在一個執行點上，依階段跑完該跑的規則並誠實判定。

閘是驗證迴圈（規格 §3.1），不是重試迴圈——一輪就停，修理是呼叫端的事。

**階段是資源排程**：規則依階段由小到大、一次一條序列執行。快的（lint、字元掃描）
先跑，重的（型別、測試）後跑，而且不同時跑——同時吃滿 CPU 會讓有時間敏感的檢查
無故變紅，那種紅燈是雜訊不是訊號。平行只發生在單一規則內部（pytest 自己開 worker）。
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from time import monotonic

from nova.契約.帳本 import 事件, 事件種類
from nova.契約.檢查結果 import 檢查結果
from nova.載體.帳本 import 不記帳本, 帳本

檢查函式 = Callable[[], tuple[bool, str]]

# 閘點＝執行點。打錯名字要當場爆，不能靜默跑零條規則然後全綠。
閘點清單 = frozenset({"提交", "ci"})

# 階段：1 靜態快檢（秒級）、2 型別、3 測試（最重）
靜態, 型別, 測試 = 1, 2, 3


@dataclass(frozen=True, slots=True)
class 規則:
    """一條可機械判定的規則。

    代碼   跨程序識別用，ASCII（CLAUDE.md 的 failure code 例外）
    名稱   給人看的中文
    閘點   掛在哪些執行點上
    負責層 這條紅了要去哪一層修
    檢查   回傳 (通過, 證據)
    階段   數字越小越先跑；同階段維持宣告順序
    涵蓋於 只掛在提交閘時，宣告 CI 裡哪條規則涵蓋了它。空字串＝沒有涵蓋者，
           那就必須自己也掛上 ci，否則「本地擋得住、CI 擋不住」會沒人發現
    """

    代碼: str
    名稱: str
    閘點: frozenset[str]
    負責層: str
    檢查: 檢查函式
    階段: int = field(default=靜態)
    涵蓋於: str = field(default="")


def 跑閘(
    閘點: str,
    規則表: Sequence[規則],
    *,
    提前停止: bool = False,
    帳: 帳本 | None = None,
) -> list[檢查結果]:
    """跑掛在這個閘點上的規則，依階段序列執行，回傳每一條的判定。

    提前停止=True：第一條紅就不跑後面（TDD 內圈要快回饋）。
    提前停止=False：全部跑完（CI 要一次看到全貌）。

    規則自己爆掉一律算紅（fail-closed）——檢查壞了卻放行，等於保證靜默消失。
    """
    if 閘點 not in 閘點清單:
        可用 = "、".join(sorted(閘點清單))
        訊息 = f"未知的閘點：{閘點}（可用：{可用}）"
        raise ValueError(訊息)

    適用 = [條 for 條 in 規則表 if 閘點 in 條.閘點]
    適用.sort(key=lambda 條: 條.階段)

    記帳 = 帳 or 不記帳本()
    結果表: list[檢查結果] = []
    for 條 in 適用:
        編號 = 記帳.新呼叫編號()
        記帳.記一筆(事件(種類=事件種類.規則開始, 呼叫編號=編號, 規則=條.代碼, 閘點=閘點))
        起 = monotonic()
        try:
            通過, 證據 = 條.檢查()
        except Exception as 錯:  # noqa: BLE001 —— 任何例外都算紅，這是刻意的
            通過, 證據 = False, f"規則自己爆了：{錯}"
        記帳.記一筆(
            事件(
                種類=事件種類.規則結束,
                呼叫編號=編號,
                規則=條.代碼,
                閘點=閘點,
                判準綠=通過,
                耗時毫秒=round((monotonic() - 起) * 1000),
            )
        )
        結果表.append(
            檢查結果(
                代碼=條.代碼,
                名稱=條.名稱,
                通過=通過,
                負責層=條.負責層,
                證據=證據,
            )
        )
        if 提前停止 and not 通過:
            break
    return 結果表

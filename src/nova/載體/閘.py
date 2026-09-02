"""閘：在一個執行點上，依階段跑完該跑的規則並誠實判定。

閘是驗證迴圈（規格 §3.1），不是重試迴圈——一輪就停，修理是呼叫端的事。

**階段是資源排程**：規則依階段由小到大、一次一條序列執行。快的（lint、字元掃描）
先跑，重的（型別、測試）後跑，而且不同時跑——同時吃滿 CPU 會讓有時間敏感的檢查
無故變紅，那種紅燈是雜訊不是訊號。平行只發生在單一規則內部（pytest 自己開 worker）。
"""

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

from nova.契約.帳本 import 事件, 事件種類
from nova.契約.檢查結果 import 檢查結果
from nova.載體.帳本 import 不記帳本, 帳本
from nova.載體.閘鎖 import 佔住, 佔用, 池大小

檢查函式 = Callable[[], tuple[bool, str]]

# 閘點＝執行點。打錯名字要當場爆，不能靜默跑零條規則然後全綠。
閘點清單 = frozenset({"提交", "ci"})

# 階段：1 靜態快檢（秒級）、2 型別、3 測試（最重）
靜態, 型別, 測試 = 1, 2, 3


class _抽乾整池型:
    """`抽乾整池` 這個哨兵的型別。**只有一個實例**，比較用 `is`。

    寫成型別而不是一個魔術數字，是因為「整池」的大小要跑的時候才知道
    （看的是那台機器有幾個核心），宣告的時候算不出來。
    """

    def __repr__(self) -> str:
        return "抽乾整池"


#: 這條規則要**整台機器**。只有負控刀該用它：那些刀的 `最多秒` 是牆鐘
#: （見 `載體/閘鎖.py` 的模組 docstring），機器上多一個鄰居就可能把好測試
#: 殺成假紅；別的規則超載只是慢。
抽乾整池 = _抽乾整池型()

要幾個token型 = int | _抽乾整池型


@dataclass(frozen=True, slots=True)
class 規則:
    """一條可機械判定的規則。

    代碼   跨程序識別用，ASCII（CLAUDE.md 的 failure code 例外）
    名稱   給人看的中文
    閘點   掛在哪些執行點上
    負責層 這條紅了要去哪一層修
    檢查   回傳 (通過, 證據)
    階段   數字越小越先跑；同階段維持宣告順序
    要幾個token 這條跑起來實際會開幾個 worker（序列指令＝1）；`抽乾整池` ＝ 要整台機器
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
    要幾個token: 要幾個token型 = field(default=1)


@contextmanager
def _拿這條的額度(條: 規則, *, 鎖目錄: Path | None, 核心數: int | None) -> Iterator[佔用]:
    """跟機器要這一條規則的 CPU 額度，跑完就還。yield 出額度收據。"""
    宣告 = 條.要幾個token
    要幾個 = 池大小(核心數) if isinstance(宣告, _抽乾整池型) else 宣告
    with 佔住("閘", 要幾個token=要幾個, 鎖目錄=鎖目錄, 核心數=核心數) as 收據:
        yield 收據


def _跑一條(
    條: 規則, *, 閘點: str, 記帳: 帳本, 鎖目錄: Path | None, 核心數: int | None
) -> 檢查結果:
    """拿這條的額度、跑它、記下開始與結束兩筆帳，回傳它的判定。

    規則自己爆掉一律算紅（fail-closed）——檢查壞了卻放行，等於保證靜默消失。
    """
    編號 = 記帳.新呼叫編號()
    with _拿這條的額度(條, 鎖目錄=鎖目錄, 核心數=核心數) as 收據:
        等待毫秒 = 收據.等待毫秒
        # **拿到額度才記「開始」**：這一筆要帶著「排了多久」，
        # 而那個數字要等到拿得到才知道。等待逐條發生，不是只有第一條會等。
        記帳.記一筆(
            事件(
                種類=事件種類.規則開始,
                呼叫編號=編號,
                規則=條.代碼,
                閘點=閘點,
                等待毫秒=等待毫秒 or None,  # 沒等就不落盤這一格
            )
        )
        起 = monotonic()
        try:
            通過, 證據 = 條.檢查()
        except Exception as 錯:  # noqa: BLE001 —— 任何例外都算紅，這是刻意的
            通過, 證據 = False, f"規則自己爆了：{錯}"
    # 計時從**拿到額度之後**起算：耗時是「這條跑多久」，排隊有自己的欄位。
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
    return 檢查結果(
        代碼=條.代碼,
        名稱=條.名稱,
        通過=通過,
        負責層=條.負責層,
        證據=證據,
        # 跟上面那筆帳本事件是**同一個變數**：CLI 印的秒數與 `lock_wait_ms`
        # 對得起來，是因為它們從這裡分出去，不是各量各的。
        等待毫秒=等待毫秒,
    )


def 跑閘(  # noqa: PLR0913 —— 鎖目錄與核心數是為了測得動額度，收成物件只是換個地方列
    閘點: str,
    規則表: Sequence[規則],
    *,
    提前停止: bool = False,
    帳: 帳本 | None = None,
    鎖目錄: Path | None = None,
    核心數: int | None = None,
) -> list[檢查結果]:
    """跑掛在這個閘點上的規則，依階段序列執行，回傳每一條的判定。

    提前停止=True：第一條紅就不跑後面（TDD 內圈要快回饋）。
    提前停止=False：全部跑完（CI 要一次看到全貌）。

    規則自己爆掉一律算紅（fail-closed）——檢查壞了卻放行，等於保證靜默消失。

    **CPU 額度是一條一條拿的**：每條規則按自己宣告的 `要幾個token` 跟機器要，
    跑完就還。整次包起來的話，一條只吃一個核心的 ruff 也會抽乾整池——
    池子有 12 個 token，實際還是一次一條閘。
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
        結果 = _跑一條(條, 閘點=閘點, 記帳=記帳, 鎖目錄=鎖目錄, 核心數=核心數)
        結果表.append(結果)
        if 提前停止 and not 結果.通過:
            break
    return 結果表

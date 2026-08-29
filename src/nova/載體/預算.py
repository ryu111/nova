"""跨執行預算鎖：一段時間內花超過就不再打出去。

工作流那一層本來就有 stop rule（步數上限＋token 上限，一次執行之內累計）。
**缺的是跨執行那一段**：`nova 問` 一次只發一個請求，單看那一次永遠沒有超支，
但一天叫兩百次就是另一回事——而那正是排程開始自己跑之後會發生的事。

累計的對象是**這個專案的帳本**（成本落盤做完才有的東西）。

## 預設關閉

「我主要是要看帳，但不要讓帳去把流程關閉。」熔斷是這樣，預算也是這樣。
機制存在、測得到、要用打開就有——但不准因為帳本裡的歷史而**預設**擋掉呼叫。

## 兩個相反方向的規則，都是刻意的

- **算不出成本 → `花費.美金` 是 None**（跟摘要同一條：有一顆給不出來就整個不給）。
  把算得出來的那幾次加起來是低報，而低報的預算會讓人以為還有額度。
- **算不出成本 → 成本上限一律放行**。擋的話，只要鏈上有一家不回成本
  （codex 與 agy 都不回），預算鎖就變成「永遠擋住」——那不是保護，那是壞掉。
  **擋不住的時候要說得出擋不住，不要假裝擋得住。**
"""

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from nova.契約.帳本 import 摘要


@dataclass(frozen=True, slots=True)
class 花費:
    """窗口內花掉的量。`美金` 是 None ＝ 這段裡有算不出成本的執行。"""

    token: int
    美金: float | None


@dataclass(frozen=True, slots=True)
class 上限:
    """兩個都不給就是不鎖——**預設關閉**。"""

    token: int | None = None
    美金: float | None = None


def 花了多少(執行們: list[摘要], *, 現在: datetime, 幾小時: float) -> 花費:
    """把窗口內的執行加起來。

    **窗口是必要的**：沒有窗口的預算不是預算，是一次性的封頂——
    用了三個月之後永遠超支，然後使用者只能把上限調高，那就等於沒有。

    讀不到時間的那一次跳過（不是整段算不出來）：一筆壞掉就整個算不出來
    等於沒有預算鎖。
    """
    if 幾小時 <= 0:
        訊息 = (
            f"幾小時 要大於 0（給的是 {幾小時}）——窗口是 0 的話什麼都不算，看起來在跑但永遠不會擋"
        )
        raise ValueError(訊息)
    起點 = 現在 - timedelta(hours=幾小時)
    總token = 0
    總美金: float | None = 0.0
    for 執行 in 執行們:
        當時 = _讀時間(執行.迄)
        if 當時 is None or 當時 < 起點:
            continue
        總token += 執行.總token
        if 執行.總成本美金 is None:
            總美金 = None
        elif 總美金 is not None:
            總美金 += 執行.總成本美金
    return 花費(token=總token, 美金=總美金)


def 超支了嗎(花: 花費, 限: 上限) -> str | None:
    """超了就回一句給人看的原因，沒超回 None。

    **等於上限不算超**——不然「上限 1000」實際只能用到 999，
    而那種差一格的規則會讓人不信任這個數字。
    """
    if 限.token is not None and 花.token > 限.token:
        return f"這段時間已經用掉 {花.token} token，超過上限 {限.token}"
    if 限.美金 is not None and 花.美金 is not None and 花.美金 > 限.美金:
        return f"這段時間已經花掉 US${花.美金:.4f}，超過上限 US${限.美金:.4f}"
    return None


def _讀時間(文字: str) -> datetime | None:
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(文字)
    return None

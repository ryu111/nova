"""成果：一次做完的工作在帳上長什麼樣。

跟 `契約.帳本` 的分工是**答的問題不同**，不是同一份資料的兩種格式：

| | 答什麼 | 顆粒 |
|---|---|---|
| 事件帳本 | 花了多少、叫了幾次、走了哪幾階 | 一次執行很多筆 |
| 成果帳本 | **這件工作做完了沒、結果是什麼** | 一次工作一筆 |

事件帳本答不出「做完了沒」——那要從軌跡自己推，而推的規則
（`3` 蓋過 `4` 之類）住在命令列那一層。所以收場與退出碼直接寫在成果上。

落盤的欄位名用 ASCII（CLAUDE.md 的跨程序 schema 欄位名例外），
給 python 呼叫端的是繁中屬性名，兩邊由 `成果轉字典` 對齊。
"""

from dataclasses import dataclass
from typing import Any

#: （繁中屬性名, 落盤的 ASCII 鍵, 讀不到時的預設值）。
#: 預設值的型別跟著欄位走，所以標成 `Any`——標死會逼出 `type: ignore`，
#: 而那是用規避換來的綠。
_欄位對照: tuple[tuple[str, str, Any], ...] = (
    ("執行識別碼", "run_id", ""),
    ("任務", "task", ""),
    ("收場", "outcome", ""),
    ("退出碼", "exit_code", 0),
    ("起", "started_at", ""),
    ("迄", "ended_at", ""),
    ("走了幾階", "steps", 0),
    ("總token", "tokens", 0),
    ("總成本美金", "cost_usd", None),
)


@dataclass(frozen=True, slots=True)
class 成果:
    """一次工作做完之後留下的那一筆。

    `任務` 記的是**使用者自己在命令列上打的那句話**，不是模型講了什麼。
    模型輸出不進帳（見 `契約.帳本.事件` 的 docstring：repo public、遮罩還沒有），
    而任務本身已經在 `ps` 的 args 上，記它沒有多開一條路。
    """

    執行識別碼: str
    任務: str
    收場: str
    退出碼: int
    起: str
    迄: str
    走了幾階: int
    總token: int
    總成本美金: float | None = None


def 成果轉字典(一筆: 成果) -> dict[str, Any]:
    """落盤用。鍵是 ASCII，讀的人可能不是 python。"""
    return {外: getattr(一筆, 內) for 內, 外, _ in _欄位對照 if getattr(一筆, 內) is not None}


def 字典轉成果(原始: dict[str, Any]) -> 成果:
    """讀回來。**缺欄位補預設值，不炸。**

    帳是 append-only 的歷史，以前寫的那些不會回頭改；欄位是之後加的話
    舊紀錄就少那一格。這裡炸掉的話整本帳都看不了，
    而看得到「哪一次、什麼收場」已經比看不到強得多。
    """
    return 成果(**{內: 原始.get(外, 預設) for 內, 外, 預設 in _欄位對照})

"""結構化審查問題契約。

定義審查意見中的結構化問題，包含穩定識別碼、種類、證據、狀態、
這一輪之內的編號及有界數量。

**兩個入口是分開的**：`ISSUE:` 是退回的入口（`審查問題`），
`FOLLOW-UP:` 是後續票的入口（`後續發現`）。審查員的視野是整份 diff，
票的視野是這一張票要做完的那件事——範圍外的發現寫成後續發現，不算一次退回。
"""

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import NamedTuple

#: 單次審查回覆中最多擷取的問題數量上限。
問題數量上限: int = 10

#: 不可信資料圍欄的標記。證據的正典形式一律不含它們，見 `_正典證據`。
不可信開始標記: str = "<<<UNTRUSTED"
不可信結束標記: str = "UNTRUSTED>>>"


class 問題種類(StrEnum):
    """審查問題歸屬的責任種類。"""

    測試設計 = "test-design"
    實作 = "impl"


class 問題狀態(StrEnum):
    """審查問題的追蹤狀態。"""

    未解 = "open"
    已解 = "resolved"


@dataclass(frozen=True, slots=True)
class 審查問題:
    """單一結構化審查問題。"""

    識別碼: str
    種類: 問題種類
    證據: str
    狀態: 問題狀態 = 問題狀態.未解
    #: 這一輪之內的指稱（1-based）。`0` ＝ 不是從審查文字讀出來的（手工建的）。
    #: **不進識別碼的雜湊**：重新編號不准換掉一條問題的身分。
    編號: int = 0


#: 不帶編號的舊行：`ISSUE: [impl] <證據>`。編號用它在文字裡的位置補。
_問題樣式 = re.compile(r"^ISSUE:\s*\[(test-design|impl)\]\s*(.+)$", re.MULTILINE | re.IGNORECASE)

#: 帶編號的行：`ISSUE-3: [impl] <證據>`。冒號可有可無——印給模型看的清單行長
#: `ISSUE-1 [impl] 證據`，模型照抄回來的就是那一行，讀不回來的話下一輪一條都撈不到。
_帶編號問題樣式 = re.compile(
    r"^ISSUE-(\d+):?\s*\[(test-design|impl)\]\s*(.+)$", re.MULTILINE | re.IGNORECASE
)


def 清掉不可信標記(文字: str) -> str:
    """把圍欄標記從文字裡清乾淨。

    清除後可能接合出新的標記，因此反覆清除到一個都不剩。
    包圍欄的人與算識別碼的人共用這一份，送出去的字才會跟算過雜湊的字逐字相同。
    """
    while 不可信開始標記 in 文字 or 不可信結束標記 in 文字:
        文字 = 文字.replace(不可信開始標記, "").replace(不可信結束標記, "")
    return 文字


def _正典證據(原字串: str) -> str:
    """把證據洗成不含圍欄標記的正典形式。

    證據會被包進不可信圍欄再送給下一個角色，包的時候標記一律清掉；
    正典形式先洗過，送出去的那一份就跟這裡算識別碼的這一份逐字相同，
    下一輪原封重印回來才讀得出同一個識別碼。
    """
    return 清掉不可信標記(原字串).strip()


def _穩定識別碼(前綴: str, 內文: str) -> str:
    """同樣的內文永遠算出同樣的識別碼——去重靠的就是這個穩定性，不是出現順序。"""
    return f"{前綴}-{hashlib.sha256(內文.encode()).hexdigest()[:8]}"


class _問題行(NamedTuple):
    """審查文字裡剖出來的一行 ISSUE，還沒洗成 `審查問題`。"""

    起始位置: int
    #: 行上寫的編號；舊行沒寫就是 `None`，由 `讀審查問題列` 用位置補。
    寫在行上的編號: int | None
    種類原字: str
    證據原字: str


def _每一條的行(文字: str) -> list[_問題行]:
    """兩種樣式各掃一遍，照它們在文字裡出現的先後排好。

    帶編號的行與舊行互斥（`ISSUE-3:` 不是 `ISSUE:`），不會有一行被讀兩次。
    """
    行們 = [
        _問題行(命中.start(), None, 命中.group(1), 命中.group(2))
        for 命中 in _問題樣式.finditer(文字)
    ]
    行們 += [
        _問題行(命中.start(), int(命中.group(1)), 命中.group(2), 命中.group(3))
        for 命中 in _帶編號問題樣式.finditer(文字)
    ]
    return sorted(行們, key=lambda 一行: 一行.起始位置)


def 讀審查問題列(文字: str) -> tuple[審查問題, ...]:
    """從審查文字中讀出結構化審查問題列，帶編號的行與不帶編號的舊行都認得。

    相同種類與證據內容將產生確定性的穩定識別碼——**編號不參與**，
    未解的條目原封帶到下一輪、重新編號之後仍然算同一條問題。
    證據取正典形式（不含圍欄標記，見 `_正典證據`）之後才算識別碼。
    行上沒寫編號時用它在這段文字裡的位置補（1-based）：
    「這條沒有編號」不是一種可以拿去講話的狀態。
    """
    問題列: list[審查問題] = []
    for 位置, 一行 in enumerate(_每一條的行(文字), start=1):
        種類 = 問題種類.測試設計 if 一行.種類原字.lower() == "test-design" else 問題種類.實作
        證據 = _正典證據(一行.證據原字)
        編號 = 一行.寫在行上的編號 if 一行.寫在行上的編號 is not None else 位置
        識別碼 = _穩定識別碼("issue", f"{種類.value}:{證據}")
        問題列.append(審查問題(識別碼=識別碼, 種類=種類, 證據=證據, 編號=編號))
        if len(問題列) >= 問題數量上限:
            break
    return tuple(問題列)


@dataclass(frozen=True, slots=True)
class 後續發現:
    """審查員留下的一條「範圍外但值得做」的發現。

    它**不是退回**：不進 `讀審查問題列`、不進連續審查護欄，
    收在 0 的時候各落成一張後續票。識別碼跟證據綁定，
    同一條在多輪重講時算同一個，所以只落一張票。
    """

    識別碼: str
    證據: str


_後續樣式 = re.compile(r"^FOLLOW-UP:\s*(.+)$", re.MULTILINE | re.IGNORECASE)


def 讀後續發現(文字: str) -> tuple[後續發現, ...]:
    """從審查文字中讀出範圍外的後續發現，照原文順序。

    證據原樣留著（不解析）——審查員寫的 `file:line` 是人回頭查的唯一線索。
    上限沿用 `問題數量上限`。
    """
    後續們: list[後續發現] = []
    for 命中 in _後續樣式.finditer(文字):
        證據 = 命中.group(1).strip()
        if not 證據:
            continue
        識別碼 = _穩定識別碼("followup", 證據)
        後續們.append(後續發現(識別碼=識別碼, 證據=證據))
        if len(後續們) >= 問題數量上限:
            break
    return tuple(後續們)

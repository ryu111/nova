"""結構化審查問題契約。

定義審查意見中的結構化問題，包含穩定識別碼、種類、證據、狀態及有界數量。

**兩個入口是分開的**：`ISSUE:` 是退回的入口（`審查問題`），
`FOLLOW-UP:` 是後續票的入口（`後續發現`）。審查員的視野是整份 diff，
票的視野是這一張票要做完的那件事——範圍外的發現寫成後續發現，不算一次退回。
"""

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

#: 單次審查回覆中最多擷取的問題數量上限。
問題數量上限: int = 10


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


_問題樣式 = re.compile(r"^ISSUE:\s*\[(test-design|impl)\]\s*(.+)$", re.MULTILINE | re.IGNORECASE)


def _穩定識別碼(前綴: str, 內文: str) -> str:
    """同樣的內文永遠算出同樣的識別碼——去重靠的就是這個穩定性，不是出現順序。"""
    return f"{前綴}-{hashlib.sha256(內文.encode()).hexdigest()[:8]}"


def 讀審查問題列(文字: str) -> tuple[審查問題, ...]:
    """從審查文字中讀出結構化審查問題列。

    相同種類與證據內容將產生確定性的穩定識別碼。
    """
    問題列: list[審查問題] = []
    for 命中 in _問題樣式.finditer(文字):
        種類字串 = 命中.group(1).lower()
        種類 = 問題種類.測試設計 if 種類字串 == "test-design" else 問題種類.實作
        證據 = 命中.group(2).strip()
        識別碼 = _穩定識別碼("issue", f"{種類.value}:{證據}")
        問題列.append(審查問題(識別碼=識別碼, 種類=種類, 證據=證據))
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

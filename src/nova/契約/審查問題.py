"""結構化審查問題契約。

定義審查意見中的結構化問題，包含穩定識別碼、種類、證據、狀態及有界數量。
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


def 讀審查問題列(文字: str) -> tuple[審查問題, ...]:
    """從審查文字中讀出結構化審查問題列。

    相同種類與證據內容將產生確定性的穩定識別碼。
    """
    問題列: list[審查問題] = []
    for 命中 in _問題樣式.finditer(文字):
        種類字串 = 命中.group(1).lower()
        種類 = 問題種類.測試設計 if 種類字串 == "test-design" else 問題種類.實作
        證據 = 命中.group(2).strip()
        內文字節 = f"{種類.value}:{證據}".encode()
        識別碼 = f"issue-{hashlib.sha256(內文字節).hexdigest()[:8]}"
        問題列.append(審查問題(識別碼=識別碼, 種類=種類, 證據=證據))
        if len(問題列) >= 問題數量上限:
            break
    return tuple(問題列)

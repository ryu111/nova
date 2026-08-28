"""「刪測試不是簡化，是拆掉驗收機制」的機械化版本。"""

import re

_測試定義 = re.compile(r"^\s*(?:async\s+)?def\s+test_", re.MULTILINE)


def 數測試(內容: str) -> int:
    """數一份原始碼裡有幾個測試函式。只認行首的 def，字串裡的不算。"""
    return len(_測試定義.findall(內容))


def 比較測試數(前: int, 後: int) -> tuple[bool, str]:
    """測試數只准持平或變多。回傳 (放行, 原因)。"""
    if 後 < 前:
        return False, f"測試數從 {前} 掉到 {後}，少了 {前 - 後} 支。刪測試＝拆掉驗收機制"
    return True, ""

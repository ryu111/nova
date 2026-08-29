"""跨執行熔斷：同一個專案裡，某一家腦連續失敗太多次就暫停呼叫。

規格：
1. 連續失敗門檻 3 次。第 3 次才開路，第 2 次還不算。
2. 只看同一家。agy 連續失敗不影響 codex。
3. 中間出現一次成功就把連續次數歸零。
4. 惰性時間重置：最後一次失敗超過冷卻期（30 分鐘）就當作閉路，回 None。
5. 沒有歷史就回 None。
"""

from datetime import datetime, timedelta

from nova.契約.帳本 import 一家的帳, 摘要

_連續失敗門檻 = 3
_冷卻時間 = timedelta(minutes=30)


def 該跳過嗎(執行們: list[摘要], 家: str, 現在: datetime) -> str | None:
    """判斷某一家供應商是否因連續失敗過多而應熔斷跳過。

    前置條件：
        執行們 必須由新到舊排序（時間上最新的在最前面）。
    """
    連續失敗 = 0
    最新失敗時間: datetime | None = None

    for 執行 in 執行們:
        帳 = _找出該家帳(執行, 家)
        if 帳 is None:
            continue
        if 帳.成功 > 0:
            break
        if 帳.失敗 > 0:
            if 最新失敗時間 is None:
                最新失敗時間 = datetime.fromisoformat(執行.迄)
            連續失敗 += 1

    if 連續失敗 < _連續失敗門檻 or 最新失敗時間 is None:
        return None

    if (現在 - 最新失敗時間) >= _冷卻時間:
        return None

    可再試 = 最新失敗時間 + _冷卻時間
    return f"供應商 {家} 連續失敗 {連續失敗} 次，請於 {可再試.isoformat()} 後再試。"


def _找出該家帳(執行: 摘要, 家: str) -> 一家的帳 | None:
    """從執行摘要中找出指定供應商且有呼叫次數的帳。"""
    for 帳 in 執行.各家:
        if 帳.供應商 == 家 and 帳.次數 > 0:
            return 帳
    return None

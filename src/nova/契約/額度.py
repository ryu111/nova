"""額度契約：限額視窗、家族額度與額度快照之資料結構。"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from nova.載體.額度 import 快取資料型

_代碼轉家名: dict[str, str] = {
    "cx": "codex",
    "ay": "agy",
    "cl": "claude",
}


@dataclass(frozen=True)
class 視窗:
    """單一時間視窗的限額狀態。"""

    標籤: str
    用掉百分比: int
    重置於: int


@dataclass(frozen=True)
class 家族額度:
    """單一模型家族之額度狀態。"""

    家: str
    視窗們: tuple[視窗, ...]
    失敗原因: str | None = None
    #: **這一家自己的**時戳（epoch 秒）；快取裡沒寫就退回全域 `ts`。
    #: 只有一個全域 `ts` 的話，只寫得到 `cl` 的那條路會把 cx／ay 也刷成新鮮的——
    #: 那是安靜地拿舊數字當新數字用。
    時間: int = 0


@dataclass(frozen=True)
class 額度快照:
    """額度快照。"""

    時間: int
    家族們: tuple[家族額度, ...]


def 快取轉快照(快取: "快取資料型 | Mapping[str, Any]") -> 額度快照:
    """將 ASCII 欄位之快取資料轉為額度快照契約物件。"""
    家族清單: list[家族額度] = []
    全域ts = int(快取["ts"])
    for 家族 in 快取.get("families", []):
        家名 = _代碼轉家名.get(家族["family"], 家族["family"])
        視窗元組 = tuple(
            視窗(
                標籤=str(窗["label"]),
                用掉百分比=int(窗["used_percent"]),
                重置於=int(窗["resets_at"]),
            )
            for 窗 in 家族.get("windows", [])
        )
        家族清單.append(
            家族額度(
                家=家名,
                視窗們=視窗元組,
                失敗原因=None,
                # 舊快取沒有每家的 `ts`，退回全域的——讀得回來比讀得漂亮重要。
                時間=int(家族.get("ts", 全域ts)),
            )
        )
    return 額度快照(時間=全域ts, 家族們=tuple(家族清單))


_星期表: dict[str, int] = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}

#: 一小時最多幾分；`4:99pm` 這種讀不出來就不猜。
_一小時的分鐘數 = 60

#: 12 小時制的鐘面只有 1～12。`0:00pm`／`13:00pm`／`99:00pm` 都是**認不得的字**，
#: 不是另一種寫法——拿 `% 12` 去湊會對一串沒看懂的文字回一個型別正確的時刻，
#: 而上層（接續票的 `不早於`、收件匣的時間門）分辨不出它是猜的。
_鐘面最小, _鐘面最大 = 1, 12

#: claude 的講法：`resets 4:40pm (Asia/Taipei)`、`resets 3:45pm`、`resets Mon 12:00am`。
#: 星期、時區都是選填；讀不出來的一律不猜（回 None），別家的寫法也不接。
_重置樣式 = re.compile(
    r"resets\s+(?:(mon|tue|wed|thu|fri|sat|sun)\b\s+)?"
    r"(\d{1,2}):(\d{2})\s*(am|pm)"
    r"(?:\s*\(([^)]+)\))?(?!\s*\()",
    re.IGNORECASE,
)


def _讀時區(時區名: str | None, 本機時區: tzinfo) -> tzinfo | None:
    """括號裡有時區名就照它，認不得就回 None（不猜）；沒括號才用本機時區。"""
    if 時區名 is None:
        return 本機時區
    try:
        return ZoneInfo(時區名.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _讀時分(時字: str, 分字: str, 上下午: str) -> tuple[int, int] | None:
    """12 小時制轉 24 小時制；時或分越界就回 None（**不拿餘數去湊**）。"""
    分 = int(分字)
    if 分 >= _一小時的分鐘數:
        return None
    時 = int(時字)
    if not (_鐘面最小 <= 時 <= _鐘面最大):
        return None
    if 時 == _鐘面最大:  # 12am → 0；12pm 會在下面加 12 成 12
        時 = 0
    if 上下午.lower() == "pm":
        時 += _鐘面最大
    return 時, 分


def _挪到未來(重置當地: datetime, 現在當地: datetime, 星期字: str | None) -> datetime:
    """把當天那個時刻挪到 `現在當地` 之後：帶星期就挪到下一個那個星期幾，沒帶就頂多挪一天。

    解出一個已經過去的時刻等於沒等——收件匣的時間門會當場放行、馬上再撞一次額度。
    """
    if 星期字 is None:
        return 重置當地 if 重置當地 > 現在當地 else 重置當地 + timedelta(days=1)
    差幾天 = (_星期表[星期字.lower()] - 重置當地.weekday()) % 7
    if 差幾天 == 0 and 重置當地 <= 現在當地:
        差幾天 = 7
    return 重置當地 + timedelta(days=差幾天)


def 解析重置時間(文字: str, *, 現在: datetime, 本機時區: tzinfo) -> datetime | None:
    """把 claude 的 `resets …` 講法解成一個釘死的 aware UTC 時刻；讀不出來就回 None。

    括號裡有時區就以它為準（本機時區完全不參與）；沒有括號才用 `本機時區`。
    解出來的時刻**一定在 `現在` 之後**：今天那個時刻已經過了就推到隔天，
    帶星期的就推到下一個那天。認不得的時區名、別家（agy／codex）的寫法一律回 None——
    猜錯的代價是再撞一次額度或整條線白躺著，不猜才是安全的一邊。
    """
    命中 = _重置樣式.search(文字)
    if 命中 is None:
        return None
    星期字, 時字, 分字, 上下午, 時區名 = 命中.groups()

    時區 = _讀時區(時區名, 本機時區)
    if 時區 is None:
        return None

    時分 = _讀時分(時字, 分字, 上下午)
    if 時分 is None:
        return None
    時, 分 = 時分

    現在當地 = 現在.astimezone(時區)
    當天那個時刻 = 現在當地.replace(hour=時, minute=分, second=0, microsecond=0)
    return _挪到未來(當天那個時刻, 現在當地, 星期字).astimezone(UTC)

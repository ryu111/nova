"""重置時間解析：`resets 4:40pm (Asia/Taipei)` 要變成一個**釘死的 UTC 時刻**。

## 為什麼要有這支

2026-09-02 15:29 台北，四條線在一分鐘內全部撞到 claude 的 session limit，
訊息一字不差：`You've hit your session limit · resets 4:40pm (Asia/Taipei)`。
四條線都收成退出碼 1（「東西壞了，人來修」），然後主 agent 等到 16:40
再手敲四次 `~/接續`——中間 72 分鐘沒有任何機制會動。

要讓「等到重置再從同一階接著做」變成機制而不是人腦裡的鬧鐘，
第一件事就是**把那個時刻讀出來**：接續票上的 `不早於`、收件匣的時間門、
`狀態.json` 的 `resume_not_before` 全都吃它。讀錯一個小時，
票不是早醒（再撞一次、再燒一次錢）就是晚醒（線白躺著）。

## 為什麼是純函式、為什麼 `現在` 與 `本機時區` 要用參數傳

- **住契約**：迴圈不准 import 載體（架構閘），而派工前的額度檢查在載體，
  兩邊要用同一支解析器，那它只能住契約。
- **不吃機器時鐘**：`resets 1:00pm` 到底是今天還是明天，取決於「現在幾點」。
  讀 `datetime.now()` 的話這支測試會在每天 13:00 那一刻自己翻面。
- **不吃機器時區**：`resets 3:45pm` 沒有括號，只能解成**本機**時間；
  跑 CI 的機器是 UTC、開發機是 Asia/Taipei，讀 `astimezone()` 會兩邊不同答案。

所以整支測試把 `現在` 釘在撞到的那一刻（2026-09-02T07:29:41Z＝台北 15:29:41）、
把 `本機時區` 釘在 `Asia/Taipei`，六種輸入的期望值全部是寫死的常數。

## 這支**不**守什麼

- 不猜。agy 的 `Resets in 143h57m55s`、codex 的 `try again at Sep 13th, 2026 7:11 PM`
  一律回 `None`（那兩家的寫法是另一張票）；讀不出來的時候
  上層的規則是「不排接續票、留給人看」，不是「加五小時試試看」。
  所以「回 None」在這裡是**被指名的正確行為**，不是還沒做完。
- 不管誰去呼叫它、也不管拿到時刻之後要做什麼（那是收件匣時間門那幾支）。

## 現在為什麼是紅的

`nova.契約.額度` 裡還沒有 `解析重置時間`，import 就會炸。
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from nova.契約.額度 import 解析重置時間

#: 四條線撞到上限的那一刻（帳本 20260902T071651Z-63dc3e 等四筆的 call_finished）。
#: 台北時間 15:29:41——「今天的 16:40 還沒到、今天的 13:00 已經過了」都吊在這一刻上。
現在 = datetime(2026, 9, 2, 7, 29, 41, tzinfo=UTC)
台北 = ZoneInfo("Asia/Taipei")

#: 帳本裡逐字抄下來的那一句，四條線一字不差。
實錄原文 = "You've hit your session limit · resets 4:40pm (Asia/Taipei)"


def _解析(文字: str) -> datetime | None:
    return 解析重置時間(文字, 現在=現在, 本機時區=台北)


def test_括號裡的時區說了算_不看本機時區() -> None:
    """實錄那一句：`4:40pm (Asia/Taipei)` ＝ 08:40Z。

    括號裡有時區的時候，本機時區一個字都不准參與——
    同一句話在 UTC 的 CI 機器上必須解出同一個時刻。
    """
    答 = _解析(實錄原文)

    assert 答 == datetime(2026, 9, 2, 8, 40, tzinfo=UTC)
    assert 答 is not None and 答.utcoffset() == timedelta(0), "回的必須是 aware 的 UTC 時刻"


def test_括號時區贏過本機時區_換一個本機時區答案不變() -> None:
    """同一句話、本機時區換成 UTC，答案還是 08:40Z。

    上一支自己過不了這一關：本機時區剛好也是台北的話，
    「有沒有真的讀括號」跟「拿本機時區湊巧對了」分不出來。
    """
    assert 解析重置時間(實錄原文, 現在=現在, 本機時區=UTC) == datetime(
        2026, 9, 2, 8, 40, tzinfo=UTC
    )


def test_沒有括號就用本機時區_今天還沒到就是今天() -> None:
    """`resets 3:45pm` 沒帶時區 → 台北 15:45（比現在 15:29 晚 16 分鐘）＝ 07:45Z。

    要是解成 UTC 15:45，接續票會晚八小時才醒，那條線整個下午躺著。
    """
    assert _解析("You've hit your session limit · resets 3:45pm") == datetime(
        2026, 9, 2, 7, 45, tzinfo=UTC
    )


def test_今天那個時刻已經過了就推到隔天() -> None:
    """`resets 1:00pm`：台北 13:00 在現在（15:29）之前，那它講的是**明天** 13:00 ＝ 隔天 05:00Z。

    這一格是「一定在未來」那條規則的骨頭：解出一個已經過去的時刻，
    收件匣的時間門會當場放行，等於沒等——馬上再撞一次額度、再燒一次錢。
    """
    assert _解析("You've hit your session limit · resets 1:00pm") == datetime(
        2026, 9, 3, 5, 0, tzinfo=UTC
    )


def test_帶星期就是下一個那天的零點() -> None:
    """`resets Mon 12:00am`：現在是星期三，下一個星期一是 09-07，台北 00:00 ＝ 09-06T16:00Z。

    `12:00am` 是**零點**不是中午——12 小時制這一格寫反的話會差 12 小時。
    """
    assert _解析("You've hit your usage limit · resets Mon 12:00am") == datetime(
        2026, 9, 6, 16, 0, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("識別", "文字"),
    [
        ("agy的相對寫法", "Quota exceeded. Resets in 143h57m55s"),
        ("codex的絕對寫法", "You've hit your usage limit. try again at Sep 13th, 2026 7:11 PM"),
    ],
)
def test_別家的寫法一律回None_不准為了變綠去猜(識別: str, 文字: str) -> None:
    """agy／codex 的重置寫法是另一張票的事，這支解析器**不准**順手猜。

    猜錯的代價不對稱：猜早了就是再撞一次額度（燒錢、工作樹被改一半），
    猜晚了就是那條線白躺著。回 `None` 的時候上層的規則是
    「不排接續票、把原文寫進理由留給人看」，那是安全的一邊。
    """
    assert _解析(文字) is None, f"{識別}不該被這支解析器認走"


@pytest.mark.parametrize(
    ("識別", "文字"),
    [
        ("零點不存在於12小時制", "You've hit your session limit · resets 0:00pm"),
        ("十三點不存在於12小時制", "You've hit your session limit · resets 13:00pm"),
        ("九十九點根本不是時刻", "You've hit your session limit · resets 99:00pm"),
    ],
)
def test_十二小時制越界就回None_不准拿餘數去湊(識別: str, 文字: str) -> None:
    """`% 12` 會把 `0:00pm` 讀成 12:00、`13:00pm` 讀成 13:00、`99:00pm` 讀成 15:00。

    三種都是**認不得的字**，不是「另一種寫法」：12 小時制的鐘面只有 1～12。
    拿餘數去湊的話，函式會對一串它其實沒看懂的文字回一個型別正確的時刻，
    而上層（接續票的 `不早於`、收件匣的時間門）完全沒有辦法分辨它是猜的——
    這正是這支解析器唯一不准做的事。`分` 那一格已經在越界時回 `None`，
    `時` 那一格用同一條規矩：**認不得就說認不得**。

    為什麼會有這種輸入：`resets 4:40pm` 這句話的來源是上游的錯誤訊息，
    格式沒有契約、隨時可能換寫法（例如改成 24 小時制的 `resets 16:40`）。
    那一天要的是「回 None、留給人看一眼」，不是安靜地早十二個小時醒來再撞一次。
    """
    assert _解析(文字) is None, f"{識別}被湊成了 {_解析(文字)}"


@pytest.mark.parametrize(
    ("識別", "文字"),
    [
        ("讀不出時刻", "You've hit your session limit · resets soon"),
        ("時區名認不得", "You've hit your session limit · resets 4:40pm (Middle-earth/Shire)"),
        ("整句沒有 resets", "You've hit your session limit. Upgrade to Max for more usage."),
        ("空字串", ""),
    ],
)
def test_讀不出來就回None(識別: str, 文字: str) -> None:
    """認不得就說認不得。

    「時區名認不得」那一格特別重要：`4:40pm` 讀得出來、時區讀不出來的時候
    **不准退回本機時區**——上游講的是它自己那個機房的 4:40，
    用台北時間套上去可能差好幾個小時，而且錯得很安靜。
    """
    assert _解析(文字) is None, f"{識別}應該回 None"


@pytest.mark.parametrize(
    ("識別", "文字"),
    [
        ("非法星期", "You've hit your session limit · resets monkey 12:00am"),
        (
            "未閉合時區",
            "You've hit your session limit · resets 4:40pm (Middle-earth/Shire",
        ),
    ],
)
def test_重置格式邊界不完整就回None_不准補猜(識別: str, 文字: str) -> None:
    """守住重置訊息的完整格式邊界：非法星期或未閉合時區都不准被補猜成時間。"""
    assert _解析(文字) is None, f"{識別}不應被解析成 {_解析(文字)}"

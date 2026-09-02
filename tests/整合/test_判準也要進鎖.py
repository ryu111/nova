"""跑判準的時候也要佔住這台機器。**判準跟閘搶的是同一份 CPU。**

`載體/閘鎖.py`（#174）讓 `nova 閘` 跑之前佔住整台機器，解掉「三個閘同時跑
pytest 互相拖出假紅」。但**工作流的判準指令沒進鎖**：`--判準` 預設是
`uv run pytest -q`，六條並行的工作流在「驗證紅」「驗證綠」「驗證重構」三個階段
都會跑它——同一種 CPU 互撞，發生次數比閘多三倍。

**誠實的比例**：2026-08-31 實測六條並行時 load average 4.22（16 核）、
零個 pytest 在跑，五條都卡在等模型。判準只佔工作流的一小段時間，
所以這一格的收益比閘鎖小；但「小機率的假紅」跟「沒有假紅」仍是兩件事，
而假紅的代價是有人去把一支好好的測試「修好」。

住整合層是因為它真的 fork 子程序、真的搶 flock，才測得出「有沒有進鎖」。
`XDG_STATE_HOME` 指到 tmp_path，所以佔的是這次測試專屬的鎖檔，
不會卡到這台機器上別的地方正在跑的閘。
"""

import inspect
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path

import pytest

from nova.契約.工作流 import 任務, 停止條件, 判準終局, 階段代碼
from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.載體.判準 import 可作指定pytest目標, 建判準
from nova.載體.閘鎖 import 佔不到, 佔住, 池大小, 等待上限環境變數
from nova.迴圈.工作流 import 建TDD執行器, 工作流結果, 跑工作流

#: 判準子程序一跑起來就留下腳印。**沒有腳印就是沒跑到。**
_留腳印腳本 = "import sys, pathlib; pathlib.Path(sys.argv[1]).write_text('跑過了')"

#: 判準子程序停在那裡等旗標，讓測試有一段「鎖確定被佔著」的窗口。
_等旗標腳本 = (
    "import sys, time, pathlib\n"
    "旗標 = pathlib.Path(sys.argv[1])\n"
    "起 = time.monotonic()\n"
    "while not 旗標.exists() and time.monotonic() - 起 < 20:\n"
    "    time.sleep(0.02)\n"
)


@pytest.fixture
def 專屬狀態目錄(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把鎖檔挪到這次測試的暫存目錄，別去碰真的機器鎖。"""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "狀態"))
    return tmp_path


def _建測試任務(工作目錄: Path) -> 任務:
    return 任務(描述="測判準有沒有進鎖", 工作目錄=工作目錄)


def _佔著幾個token() -> int:
    """「閘」那個池子裡現在有幾個 token 在別人手上。**不等，問完就走。**

    **不是是非題。** 閘鎖擋的是 CPU 額度不是「一次一條」：一條序列判準
    只拿走 1 個 token，機器上還有 11 個位子給別的閘與別的判準。
    所以這裡數的是「拿不到的有幾個」，不是「鎖被佔了沒」——
    問成是非題的話，「判準只該取 1 個」跟「判準獨佔整台機器」會長得一模一樣。
    """
    全部 = 池大小()
    with ExitStack() as 堆疊:
        拿到 = 0
        while 拿到 < 全部:
            try:
                堆疊.enter_context(佔住("閘", 要幾個token=1, 最多等幾秒=0.0))
            except 佔不到:
                break
            拿到 += 1
    return 全部 - 拿到


def test_閘佔著的時候判準的子程序根本沒跑(
    專屬狀態目錄: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**同一把鎖。** 判準跟閘各拿各的話，兩邊還是會同時跑滿 CPU，卻長得像有鎖。

    這裡佔的是閘用的那個名稱（`閘`）。判準若進了別把鎖，這支就會綠——
    所以腳印檔是這支測試的全部重點：**沒有腳印才代表判準真的被那把鎖擋住了。**
    """
    monkeypatch.setenv(等待上限環境變數, "0.5")
    腳印 = 專屬狀態目錄 / "腳印.txt"
    判準 = 建判準((sys.executable, "-c", _留腳印腳本, str(腳印)))

    with 佔住("閘"):
        收場, 證據 = 判準(_建測試任務(專屬狀態目錄))

    assert not 腳印.exists(), f"閘佔著鎖，判準的子程序卻還是跑了：{證據}"
    assert 收場 is not 判準終局.綠


def test_佔不到鎖回跑不起來而不是紅(專屬狀態目錄: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """**判準沒跑 ≠ 判準失敗。**

    回紅的話工作流會回去「再實作一次」，而實作要叫模型——最貴的那一步。
    機器很忙要的是等，不是叫一顆腦去改一份沒問題的程式碼。
    參考 `_子命令_閘` 佔不到時回 3（結果未知）的處理。
    """
    monkeypatch.setenv(等待上限環境變數, "0.5")
    判準 = 建判準((sys.executable, "-c", "raise SystemExit(0)"))

    with 佔住("閘"):
        收場, 證據 = 判準(_建測試任務(專屬狀態目錄))

    assert 收場 is 判準終局.跑不起來, f"收場是 {收場}，證據：{證據}"
    assert 證據.strip(), "佔不到鎖要留得下證據，不然看起來像判準空跑一輪"


def _量等多久(上限: str, 專屬狀態目錄: Path, monkeypatch: pytest.MonkeyPatch) -> float:
    """佔著鎖跑一次判準，量它放棄之前等了多久。"""
    monkeypatch.setenv(等待上限環境變數, 上限)
    判準 = 建判準((sys.executable, "-c", "raise SystemExit(0)"))
    with 佔住("閘"):
        起 = time.monotonic()
        收場, _ = 判準(_建測試任務(專屬狀態目錄))
        花了 = time.monotonic() - 起
    assert 收場 is 判準終局.跑不起來, f"上限 {上限} 秒這一輪的收場是 {收場}"
    return 花了


@pytest.mark.serial
def test_等待上限走既有的環境變數(專屬狀態目錄: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """**一個上限，不要第二個。** 4 核的機器排隊比 16 核久，那是設定不是邏輯。

    **量兩個不同的值再相比**，不是量一個值落在哪個區間：只量一個的話，
    寫死成任何一個常數（0.5 秒、20 秒、`_預設最多等幾秒`）都會通過，
    這支測試就背書不了「調得動」。差值才分得出「真的讀了環境變數」。
    """
    快 = _量等多久("0.4", 專屬狀態目錄, monkeypatch)
    慢 = _量等多久("1.6", 專屬狀態目錄, monkeypatch)

    assert 快 >= 0.4, f"設 0.4 秒上限卻只等了 {快:.2f} 秒——根本沒等"
    assert 慢 - 快 >= 0.6, f"上限從 0.4 調到 1.6，等待時間只從 {快:.2f} 變成 {慢:.2f} 秒"


class _假角色:
    """一顆不叫模型的假腦。**只有身分是假的，走的路是真的**——

    它掛在真的 `建TDD執行器` 上，由真的 `跑工作流` 呼叫，所以模型階段若誤佔了
    同一把鎖，卡住的會是這裡。自製一條「假模型執行緒」測不到那件事。
    """

    def __init__(self, 名稱: str) -> None:
        self.名稱 = 名稱
        self.收到: list[str] = []

    def 做(self, 提示: str, *, 工作目錄: Path | None = None) -> 回應:
        del 工作目錄
        self.收到.append(提示)
        return 回應(
            文字="乙的模型講完了",
            終局=終局.成功,
            失敗代碼=失敗代碼.無,
            原始結束碼=0,
            對話識別碼=None,
            用量=用量(輸入token=1, 輸出token=1),
        )


def _跑一條只走模型階段的工作流(工作目錄: Path) -> tuple[工作流結果, _假角色]:
    """真的 `跑工作流`，但停在第一個模型階段之後。

    `最多步數=1` 讓它只走得到「測試」那一階（模型階段）就收在護欄——
    正是「另一條工作流此刻在等模型」的形狀，而且沒有機會踏到判準。
    """
    測試員 = _假角色("測試")
    執行一步 = 建TDD執行器(
        角色表={
            階段代碼.測試: 測試員,
            階段代碼.實作: _假角色("實作"),
            階段代碼.重構: _假角色("重構"),
            階段代碼.審查: _假角色("審查"),
        },
        # 乙也備了真的判準：**建的時候不該佔鎖**，佔了這條路就走不到模型階段。
        跑判準=建判準((sys.executable, "-c", "raise SystemExit(0)")),
        篩選指定測試=可作指定pytest目標,
    )
    結果 = 跑工作流(
        _建測試任務(工作目錄),
        執行一步=執行一步,
        起點=階段代碼.測試,
        停止=停止條件(最多步數=1),
    )
    return 結果, 測試員


@pytest.mark.serial
def test_鎖只圈住跑子程序那一段_模型呼叫照樣跑得動(專屬狀態目錄: Path) -> None:
    """**鎖的範圍要小。** 圈住整個判準階段就等於一次只能跑一條工作流。

    模型呼叫要花好幾分鐘，判準的子程序只花幾秒；把鎖拉到階段層級，
    六條並行會退化成序列，而它們大部分時間本來就只是在等模型（實測五條同時等）。

    這支盯三件事：`建判準` 不准在建的時候就拿額度、子程序跑的那一段額度要在手上、
    跑完就要還。中間那段「另一條工作流的模型呼叫」走的是**真的 `跑工作流`**，
    只有那顆腦是假的——模型階段若也去拿額度，乙會卡在甲的窗口裡等到 join 逾時。

    **重疊怎麼驗**：數池子。token 池底下乙各取各的本來就不必等甲，
    所以「甲還握著」不能用「乙拿不到」來反推——要直接數出甲那 1 個還在。
    """
    旗標 = 專屬狀態目錄 / "放行.旗標"
    甲判準 = 建判準((sys.executable, "-c", _等旗標腳本, str(旗標)), 逾時秒=30.0)
    assert _佔著幾個token() == 0, "建判準的時候就把額度拿走了——那把整個階段都圈進去了"

    收場們: list[判準終局] = []
    甲 = threading.Thread(target=lambda: 收場們.append(甲判準(_建測試任務(專屬狀態目錄))[0]))
    甲.start()
    try:
        起 = time.monotonic()
        while _佔著幾個token() == 0:
            assert time.monotonic() - 起 < 20.0, "判準跑子程序的時候沒有跟機器要額度"
            time.sleep(0.02)

        # 乙工作流此刻要做的是模型呼叫——鎖在甲手上，它照樣得跑得完。
        乙跑完的: list[tuple[工作流結果, _假角色]] = []
        乙 = threading.Thread(
            target=lambda: 乙跑完的.append(_跑一條只走模型階段的工作流(專屬狀態目錄))
        )
        乙.start()
        乙.join(timeout=10.0)
        assert 乙跑完的, "甲拿著鎖的時候乙的工作流卡在模型階段跑不完"
        乙結果, 乙的測試員 = 乙跑完的[0]
        assert 乙的測試員.收到, "乙的模型階段根本沒被呼叫到"
        assert [步.終局 for 步 in 乙結果.軌跡] == [終局.成功], f"乙的軌跡是 {乙結果.軌跡}"
        assert _佔著幾個token() == 1, (
            "乙講完話的當下，甲該還握著**剛好 1 個** token："
            "0 代表甲已經還掉了（這一輪沒測到重疊），"
            "大於 1 代表一條序列判準拿走了不只一個核心的額度"
        )
    finally:
        旗標.write_text("走吧")
        甲.join(timeout=30.0)

    assert 收場們 == [判準終局.綠]
    assert _佔著幾個token() == 0, "判準跑完沒還額度——跑幾次就把池子漏光"


@pytest.mark.serial
def test_判準能宣告要幾個token而且跑的時候就握著那麼多(專屬狀態目錄: Path) -> None:
    """**額度是個數量，不是是非題。**

    `佔機器: bool` 只講得出「有拿」跟「沒拿」，於是「拿多少」被寫死在 `_佔住機器跑`
    裡的 `要幾個token=1`。序列 pytest 取 1 是對的，但那是**這條指令的性質**，
    不是判準這個機制的性質：`pytest -n 4` 那種判準實際會開四個 worker，
    照樣只登記 1 個的話，池子上的數字就跟機器上真正的負載對不起來——
    十二個各報 1 的四核判準能同時開跑，機器上其實是四十八個 worker。

    順帶讓 bool 退場：`佔機器=False`（子程序自己會去同一個池子拿）也是一種額度宣告，
    跟「取幾個」放同一個參數才講得清楚，兩個參數會出現「False 又取 4」這種說不通的組合。
    """
    要幾個 = 2
    if 池大小() < 要幾個:
        pytest.skip("池子不到 2 個 token，驗不出『宣告幾個就握幾個』")

    旗標 = 專屬狀態目錄 / "放行.旗標"
    判準 = 建判準(
        (sys.executable, "-c", _等旗標腳本, str(旗標)),
        逾時秒=30.0,
        要幾個token=要幾個,
    )
    assert _佔著幾個token() == 0, "建判準的時候就把額度拿走了"

    收場們: list[判準終局] = []
    跑著的 = threading.Thread(target=lambda: 收場們.append(判準(_建測試任務(專屬狀態目錄))[0]))
    跑著的.start()
    try:
        起 = time.monotonic()
        while _佔著幾個token() == 0:
            assert time.monotonic() - 起 < 20.0, "判準跑子程序的時候沒有跟機器要額度"
            time.sleep(0.02)

        assert _佔著幾個token() == 要幾個, (
            f"宣告 {要幾個} 個卻握著 {_佔著幾個token()} 個——1 代表宣告被無視、額度還是硬編碼的 1"
        )
    finally:
        旗標.write_text("走吧")
        跑著的.join(timeout=30.0)

    assert 收場們 == [判準終局.綠]
    assert _佔著幾個token() == 0, "判準跑完沒把宣告的那幾個還乾淨"
    assert "佔機器" not in inspect.signature(建判準).parameters, (
        "`佔機器: bool` 要退場：額度有幾個、還是子程序自己拿，是同一個參數的兩種值——"
        "留著 bool 就會出現「佔機器=False 又取 4 個」這種說不通的組合"
    )

"""閘鎖擋的是 **CPU 額度**，不是「一次一條閘」。

## 這一支守什麼

`載體/閘鎖.py` 的 docstring 自己寫了它防什麼：機器超載 → `tests/負控/登記.py`
的 `最多秒 = 2.0` 牆鐘逾時把好測試殺成「刀沒被殺」的假紅。**超載才是敵人**，
「同時有兩條閘」不是。可是實作把它做成一把互斥鎖，於是一條序列 pytest
（吃 1 個核心）也要獨佔整台 16 核的機器——`閘.排隊` 底下排了 12 個，
一次 `nova 閘 提交` 含排隊 318 秒。

正確的粒度是 make jobserver 那種**跨程序的計數信號量**：池子有
N ＝ `int(核心 × 平行成數)` 個 token，每條指令按**自己實際會開的 worker 數**
取用——序列 pytest／ruff／mypy 取 1，`pytest-parallel` 取 `平行度()`，
只有對超載敏感的負控刀（`registered-mutation`）抽乾整池。

## 為什麼這裡不真的開兩個閘

要驗的是「額度怎麼算」，不是「閘會不會跑」。所以鎖目錄與核心數都用注入的，
一支測試零個 pytest 子程序。真正 fork 的跨程序行為由 `test_閘鎖.py`
與 `test_閘鎖先到先得.py` 顧。

## 為什麼同一個程序裡拿得出「別人佔著」

`flock` 綁的是 open file description，不是程序。同一個程序裡各自 `open()`
出來的兩個 fd 一樣會互相擋——所以巢狀的 `佔住` 就足以模擬十三條線在搶。

住整合層是因為它動的是檔案系統上的鎖，不是純函式。
"""

import threading
from contextlib import ExitStack
from pathlib import Path

import pytest

from nova.載體.閘鎖 import 佔不到, 佔住, 抽乾池子時不准握著token, 池大小

#: 假裝的核心數。16 × `規則表.平行成數`(0.75) = 12 個 token，
#: 就是實測那台機器的額度。**寫死在測試裡**：這一支驗的是算法，不是這台機器。
_假核心數 = 16

#: 池滿的時候，排隊那一條等多久就判定「它真的排到隊了」。
#: 輪詢間隔是 0.2 秒，等兩輪足夠；**這不是被測行為的一部分**，
#: 只是不讓測試整支掛住。
_排隊上限秒 = 0.5

#: 扮鄰居的那條執行緒最多握多久／最多等多久。**不是被測行為**，
#: 只是不讓測試在哪裡卡死都沒人知道。
_鄰居最多握幾秒 = 20.0


def _佔(堆疊: ExitStack, 鎖目錄: Path, 要幾個token: int) -> None:
    """在堆疊上佔住 `要幾個token` 個 token，直到測試結束才放。"""
    堆疊.enter_context(佔住("閘", 要幾個token=要幾個token, 鎖目錄=鎖目錄, 核心數=_假核心數))


def test_池子有十二個token第十三條才要排隊(tmp_path: Path) -> None:
    """**這一支是這張票存在的理由。**

    十二條各取 1 的指令（序列 pytest／ruff／mypy）同時跑滿額度，
    誰也不必等誰；第十三條才碰到牆。互斥鎖版本在**第二條**就開始排隊。
    """
    assert 池大小(核心數=_假核心數) == 12

    with ExitStack() as 堆疊:
        for _ in range(12):
            _佔(堆疊, tmp_path, 1)

        with (
            pytest.raises(佔不到),
            佔住(
                "閘",
                要幾個token=1,
                最多等幾秒=_排隊上限秒,
                鎖目錄=tmp_path,
                核心數=_假核心數,
            ),
        ):
            pytest.fail("池子已經滿了，第十三條不該拿得到")


def test_池目錄建立完整額度的token檔(tmp_path: Path) -> None:
    """池子的容量要落成固定數量的獨立檔案鎖，讓每個額度都有可競爭的名額。"""
    with 佔住("閘", 要幾個token=1, 鎖目錄=tmp_path, 核心數=_假核心數):
        token目錄 = tmp_path / "閘.slots"
        實際檔名 = sorted(檔.name for 檔 in token目錄.iterdir())
        期望檔名 = [f"{編號:03d}" for 編號 in range(池大小(核心數=_假核心數))]

    assert 實際檔名 == 期望檔名


def test_取四的跟取一的算同一份額度(tmp_path: Path) -> None:
    """token 數 ＝ 這條指令實際會開的 worker 數，不是「一條指令一格」。

    三條平行 pytest（各 `平行度()` = 4）就吃掉 12 個額度，
    再來一條只要 1 個核心的 ruff 也得等——因為機器真的沒了。
    """
    with ExitStack() as 堆疊:
        for _ in range(3):
            _佔(堆疊, tmp_path, 4)

        with (
            pytest.raises(佔不到),
            佔住(
                "閘",
                要幾個token=1,
                最多等幾秒=_排隊上限秒,
                鎖目錄=tmp_path,
                核心數=_假核心數,
            ),
        ):
            pytest.fail("3×4 已經佔滿 12 個額度，取 1 的不該拿得到")


def test_刀要抽乾池子所以有人握著一個就得等(tmp_path: Path) -> None:
    """`registered-mutation` 取 N 個：它的 `最多秒` 是牆鐘，容不下任何鄰居。

    握著那 1 個的是**別條線**（這裡用另一條執行緒扮，`_排隊上限秒` 之後它還在握）。
    別人握著的 token 有人會還，所以刀要做的是**等**——這跟下一支的「自己握著自己要」
    不是同一件事，後者永遠等不到，得當場拋。
    """
    拿到了 = threading.Event()
    放手吧 = threading.Event()

    def 別條線握著一個() -> None:
        with 佔住("閘", 要幾個token=1, 鎖目錄=tmp_path, 核心數=_假核心數):
            拿到了.set()
            放手吧.wait(_鄰居最多握幾秒)

    鄰居 = threading.Thread(target=別條線握著一個)
    鄰居.start()
    try:
        assert 拿到了.wait(_鄰居最多握幾秒), "扮鄰居的那條線根本沒拿到 token"

        with (
            pytest.raises(佔不到),
            佔住(
                "閘",
                要幾個token=池大小(核心數=_假核心數),
                最多等幾秒=_排隊上限秒,
                鎖目錄=tmp_path,
                核心數=_假核心數,
            ),
        ):
            pytest.fail("還有人握著 1 個 token，抽乾池子的不該拿得到")
    finally:
        放手吧.set()
        鄰居.join(timeout=_鄰居最多握幾秒)


def test_握著token的人要抽乾池子是死鎖要當場拋(tmp_path: Path) -> None:
    """**死鎖規則**：抽乾池子的呼叫端必須在握零個 token 時才開始拿。

    握著 4 個再去要 12 個，剩下的 8 個永遠等不到——等的人就是還的人。
    這種情況**當場拋**，不准變成一次 30 分鐘的 `佔不到`：
    「機器很忙」跟「程式自己鎖死自己」的下一步相反，前者要等，後者要修。
    """
    with ExitStack() as 堆疊:
        _佔(堆疊, tmp_path, 4)

        with (
            pytest.raises(抽乾池子時不准握著token),
            佔住(
                "閘",
                要幾個token=池大小(核心數=_假核心數),
                鎖目錄=tmp_path,
                核心數=_假核心數,
            ),
        ):
            pytest.fail("握著 token 還要抽乾池子＝死鎖，不該進得去")


def test_同程序握著token帶上限抽乾也要當場拋(tmp_path: Path) -> None:
    """自鎖**不會因為等得短就變成不是自鎖**——給了 `最多等幾秒` 也照拋。

    現在的實作在呼叫端自己給了上限時就放行，於是同一個死鎖會偽裝成
    一次 0.5 秒的 `佔不到`。差別不在等多久，在**下一步**：
    `佔不到` 的下一步是重試（機器很忙，等一下就好），
    自鎖的下一步是修程式（多等一百倍也還是等不到，因為要還的人正在等）。
    把自鎖回報成 `佔不到` 就是叫呼叫端去重試一個永遠不會成立的條件。
    """
    with ExitStack() as 堆疊:
        _佔(堆疊, tmp_path, 4)

        with (
            pytest.raises(抽乾池子時不准握著token),
            佔住(
                "閘",
                要幾個token=池大小(核心數=_假核心數),
                最多等幾秒=_排隊上限秒,
                鎖目錄=tmp_path,
                核心數=_假核心數,
            ),
        ):
            pytest.fail("握著 4 個 token 還要抽乾整池＝死鎖，給了上限也一樣")

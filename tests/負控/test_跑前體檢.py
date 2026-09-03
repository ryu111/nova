"""登記的**跑前體檢**：不套用變異，只驗錨點與覆蓋。

現在這兩道檢查只在 `registered-mutation` 那條 CI 規則裡跑（一輪 158 秒），
於是登記寫錯要推 PR 等 CI 幾分鐘才看得到 `WRONG_TEST`。這個檔釘的是
**同樣的兩道判定、但跑之前就算得出來**那支檢查器的行為。

被釘的介面（實作還不存在，這個檔現在是紅的）：

    from . import 跑前體檢
    問題們: tuple[str, ...] = 跑前體檢.體檢登記(登記們, 根目錄=根)

回傳每一筆有問題的登記各一則訊息；**空 tuple ＝ 全部過**。
不 raise：一次要把 143 筆全部看完，第一筆就炸的話後面那些還是得等下一輪。

兩個假專案都是今天實際踩到的形狀，不是好造的假案例：
`except` 分支那支尤其——測試走 happy path、`except` 那兩行一次都沒跑到。
"""

import dataclasses
import shutil
from pathlib import Path

import pytest

from . import 跑前體檢
from .登記 import 替換一次, 變異

_量大小原始碼 = '''"""量檔案大小；量不到就回 -1。"""

from pathlib import Path


def 量大小(路徑: Path) -> int:
    try:
        return 路徑.stat().st_size
    except OSError:
        return -1
'''

#: 只走 happy path 的測試：`except OSError` 那兩行一次都不會被執行。
_量大小測試原始碼 = """from pathlib import Path

from 量大小 import 量大小


def test_量得到現有檔案的大小(tmp_path: Path) -> None:
    檔 = tmp_path / "甲.txt"
    檔.write_text("四個字", encoding="utf-8")

    assert 量大小(檔) == len("四個字".encode())
"""

_走happy_path的測試 = "tests/test_量大小.py::test_量得到現有檔案的大小"


@pytest.fixture
def 假專案(tmp_path: Path) -> Path:
    """一個跑得起來的最小專案：原始碼與測試都住在 `tests/`。

    住在 `tests/` 底下是為了讓 `from 量大小 import 量大小` 不必靠
    `PYTHONPATH` 的細節——體檢器怎麼接線都不影響這份測資成不成立。
    """
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/量大小.py").write_text(_量大小原始碼, encoding="utf-8")
    (tmp_path / "tests/test_量大小.py").write_text(_量大小測試原始碼, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n', encoding="utf-8"
    )
    return tmp_path


def test_錨點對不上的登記在跑變異之前就被指名(假專案: Path) -> None:
    """錨點被重構掉的那一筆要被點名，沒事的那一筆不准被連坐。

    今天踩到的成因：`自主票沒帶驗收照樣派出去` 的錨點那一行被重構成兩行，
    實際出現 0 次。這種錯**只要讀檔數字串**就知道，不必等 121 把刀跑完。
    """
    重構掉錨點的 = 變異(
        識別="量不到大小要回負一",
        目標檔=Path("tests/量大小.py"),
        # 這一行在目標檔裡長的是 `return 路徑.stat().st_size`，錨點實際出現 0 次。
        操作=替換一次("大小 = 路徑.stat().st_size", "大小 = 0"),
        該紅=(_走happy_path的測試,),
        最多秒=30.0,
    )
    錨點與覆蓋都對的 = 變異(
        識別="量大小不准回死值",
        目標檔=Path("tests/量大小.py"),
        操作=替換一次("return 路徑.stat().st_size", "return 0"),
        該紅=(_走happy_path的測試,),
        最多秒=30.0,
    )

    問題們 = 跑前體檢.體檢登記((重構掉錨點的, 錨點與覆蓋都對的), 根目錄=假專案)

    assert len(問題們) == 1, f"只有一筆該紅，實際：{問題們}"
    (訊息,) = 問題們
    assert "量不到大小要回負一" in 訊息, f"訊息沒指名是哪一筆：{訊息}"
    assert "量大小不准回死值" not in 訊息, f"好的那一筆被連坐了：{訊息}"
    assert "大小 = 路徑.stat().st_size" in 訊息, f"訊息沒說是哪個錨點：{訊息}"
    # 沿用既有那道檢查的說法（`錨點應恰好一次，實際 N`）：這一格是把它提早，不是換掉它。
    assert "實際 0" in 訊息, f"訊息沒說錨點實際出現幾次：{訊息}"


def test_該紅蓋不到except分支的登記在跑變異之前就被指名(假專案: Path) -> None:
    """刀砍 `except OSError` 那兩行，而點名的測試只走 happy path。

    這是今天五次裡的第一類形狀（砍到測試走不到的行）。錨點沒問題、
    測試也真的紅得起來，唯一的破綻是**那幾行根本沒被執行**——
    要靠覆蓋率才看得出來，所以體檢要真的跑一次 `該紅` 收覆蓋。

    訊息要能直接動手：印行號還要人自己去翻第幾行是什麼，所以**行的內容**
    也要在訊息裡。
    """
    砍except分支的 = 變異(
        識別="量不到大小照樣回得出數字",
        目標檔=Path("tests/量大小.py"),
        操作=替換一次(
            "    except OSError:\n        return -1",
            "    except OSError:\n        return 0",
        ),
        該紅=(_走happy_path的測試,),
        最多秒=30.0,
    )

    問題們 = 跑前體檢.體檢登記((砍except分支的,), 根目錄=假專案)

    assert len(問題們) == 1, f"這一筆該被抓出來，實際：{問題們}"
    (訊息,) = 問題們
    assert "WRONG_TEST" in 訊息, f"沒判成 WRONG_TEST：{訊息}"
    assert "量不到大小照樣回得出數字" in 訊息, f"訊息沒指名是哪一筆：{訊息}"
    assert _走happy_path的測試 in 訊息, f"訊息沒說是哪支測試蓋不到：{訊息}"
    assert "except OSError:" in 訊息, f"訊息沒印出蓋不到的那幾行的內容：{訊息}"
    assert "return -1" in 訊息, f"訊息沒印出蓋不到的那幾行的內容：{訊息}"


#: 合併之後的形狀：那一行的**前半段**被改寫過（`follow_symlinks=True` 是合併帶進來的），
#: 只有行尾的標記註解原封不動——標記錨要能在這種改寫底下照樣釘得住。
_帶標記錨的量大小原始碼 = '''"""量檔案大小；量不到就回 -1。"""

from pathlib import Path


def 量大小(路徑: Path) -> int:
    try:
        return 路徑.stat(follow_symlinks=True).st_size  # 負控錨:量得出大小
    except OSError:
        return -1
'''

_被改寫過的那一行 = "        return 路徑.stat(follow_symlinks=True).st_size  # 負控錨:量得出大小"
_變異之後的那一行 = "        return 0  # 負控錨:量得出大小"


def test_標記錨在那一行被改寫之後照樣命中(tmp_path: Path) -> None:
    """守：標記錨釘的是行尾的標記註解，被錨那一行的其餘部分改寫掉也照樣命中一次。

    命中之後換掉的是**含標記的那一整行**，不是只換標記那一段；同一個檔裡的其他行不准動。
    """
    from .登記 import 替換標記行

    目標 = tmp_path / "量大小.py"
    目標.write_text(_帶標記錨的量大小原始碼, encoding="utf-8")
    操作 = 替換標記行(標記="負控錨:量得出大小", 變成=_變異之後的那一行)

    assert 操作.錨點 == "# 負控錨:量得出大小", f"錨點要是標記本身，不是整行原文：{操作.錨點!r}"
    命中次數 = 目標.read_text(encoding="utf-8").count(操作.錨點)
    assert 命中次數 == 1, f"標記錨在合併改寫過的原始碼裡沒命中一次，實際 {命中次數}"

    前, 後 = 操作.套用(目標)

    assert 前 != 後, "套用前後的 SHA256 一樣，代表變異沒生效"
    套用後 = 目標.read_text(encoding="utf-8")
    assert _變異之後的那一行 in 套用後.splitlines(), f"沒把整行換成 `變成`：{套用後}"
    assert _被改寫過的那一行 not in 套用後, f"原本那一行還在，整行沒被換掉：{套用後}"
    assert "路徑.stat(" not in 套用後, f"整行沒被換掉，只換了標記那一段：{套用後}"
    assert "        return -1" in 套用後, f"被錨那一行以外的行不准動：{套用後}"


def test_錨點失效的訊息帶得出登記檔名與命中次數(假專案: Path) -> None:
    """守：錨點失效的訊息四件事給齊，而且跑前體檢與執行器拿到的是同一份。

    四件事＝哪把刀、登記在哪個檔、命中幾次、怎麼重釘。
    只說「錨點應恰好一次」的話，人要在 192 筆登記裡自己找那把刀住哪個檔；
    `登記們/` 這種只到目錄的說法等於沒說，要指到**那個登記檔的檔名**。
    「怎麼重釘」要能照著做完：指到登記那一行還不夠，得說改成什麼——
    改成目標檔現在的原文，或改用標記錨。
    """
    from . import 執行器
    from .登記 import 登記, 登記來源

    識別 = "登記來源照抄外層拿不到檔名"
    #: 對照要帶到**內層那次**收集的真檔名；照抄外層那份只會拿到目錄名。
    assert 登記來源[識別].endswith("登記們/負控錨點.py"), (
        f"模組層對照要指到內層那份的真檔名，實際：{登記來源[識別]!r}"
    )
    這一筆 = next(一筆 for 一筆 in 登記 if 一筆.識別 == 識別)
    錨點失效的 = dataclasses.replace(
        這一筆,
        目標檔=Path("tests/量大小.py"),
        # 這一行在目標檔裡長的是 `return 路徑.stat().st_size`，錨點實際出現 0 次。
        操作=替換一次("大小 = 路徑.stat().st_size", "大小 = 0"),
        該紅=(_走happy_path的測試,),
        最多秒=30.0,
    )

    (跑前體檢給的,) = 跑前體檢.體檢登記((錨點失效的,), 根目錄=假專案)
    with pytest.raises(執行器.負控錯誤) as 執行器炸的:
        執行器._確認錨點(錨點失效的, 假專案 / 錨點失效的.目標檔)
    執行器給的 = str(執行器炸的.value)

    for 來自, 訊息 in (("跑前體檢", 跑前體檢給的), ("執行器", 執行器給的)):
        assert 識別 in 訊息, f"{來自}的訊息沒指名是哪把刀：{訊息}"
        assert "登記們/負控錨點.py" in 訊息, f"{來自}的訊息沒說這把刀登記在哪個檔：{訊息}"
        assert "tests/量大小.py" in 訊息, f"{來自}的訊息沒說錨在哪個目標檔：{訊息}"
        assert "大小 = 路徑.stat().st_size" in 訊息, f"{來自}的訊息沒帶錨點原文：{訊息}"
        assert "實際 0" in 訊息, f"{來自}的訊息沒說實際命中幾次：{訊息}"
        assert f'識別="{識別}"' in 訊息, f"{來自}的訊息沒指到登記裡要改的那一筆：{訊息}"
        assert "把錨點改成目標檔現在的原文" in 訊息, (
            f"{來自}的重釘說法沒說可以改成目標檔現在的原文：{訊息}"
        )
        assert "替換標記行" in 訊息, f"{來自}的重釘說法沒說可以改用標記錨：{訊息}"


def test_標記錨推導出的破壞行是可執行行(tmp_path: Path) -> None:
    """守：標記錨算得出非空的必須覆蓋行，而且就是掛標記的那一行。

    推導不到可執行行的錨法（例如錨在 `def 名(` 上）會被收成 `WRONG_TEST`，
    那把刀就永遠證明不了「該紅真的走得到」。
    """
    from .執行器 import 要求覆蓋的行
    from .登記 import 替換標記行

    目標 = tmp_path / "量大小.py"
    目標.write_text(_帶標記錨的量大小原始碼, encoding="utf-8")
    掛標記的行號 = _帶標記錨的量大小原始碼.splitlines().index(_被改寫過的那一行) + 1
    一筆 = 變異(
        識別="量大小不准回死值",
        目標檔=Path("量大小.py"),
        操作=替換標記行(標記="負控錨:量得出大小", 變成=_變異之後的那一行),
        該紅=(_走happy_path的測試,),
        最多秒=30.0,
    )

    要求 = 要求覆蓋的行(目標, 一筆)

    assert 要求, "標記錨推導不出可執行行，這把刀會被收成 WRONG_TEST"
    assert 要求 == frozenset({掛標記的行號}), (
        f"要求覆蓋的行不是掛標記的那一行（第 {掛標記的行號} 行），實際：{sorted(要求)}"
    )


def test_正式跑刀的順序上最早炸的那道檢查就要給得出重釘指引(
    假專案: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """守：`執行變異` 正式順序上**第一個**碰到壞錨點的關卡，訊息就要四件事給齊。

    錨點失效時要能照著訊息重釘：哪把刀、登記在哪個檔、命中幾次、怎麼改。
    這一格守的是「正式 `registered-mutation` 路徑上看到的就是這一份」——
    不是某個直接呼叫得到的關卡碰巧說得比較清楚。
    """
    from . import 執行器
    from .登記 import 登記

    識別 = "登記來源照抄外層拿不到檔名"
    這一筆 = next(一筆 for 一筆 in 登記 if 一筆.識別 == 識別)
    錨點失效的 = dataclasses.replace(
        這一筆,
        目標檔=Path("tests/量大小.py"),
        # 這一行在目標檔裡長的是 `return 路徑.stat().st_size`，錨點實際出現 0 次。
        操作=替換一次("大小 = 路徑.stat().st_size", "大小 = 0"),
        該紅=(_走happy_path的測試,),
        最多秒=30.0,
    )

    def _不跑基線(根目錄: Path, 一筆: 變異) -> None:
        """基線那次 pytest 不是這一格的題目。"""

    # 只換掉跟錨點無關的兩步：假專案沒有 `src/`、`docs/`，複製整份就好。
    monkeypatch.setattr(執行器, "_複製專案", shutil.copytree)
    monkeypatch.setattr(執行器, "_跑基線", _不跑基線)
    走到確認錨點: list[str] = []
    真的確認錨點 = 執行器._確認錨點

    def _記一次(一筆: 變異, 目標: Path) -> None:
        走到確認錨點.append(一筆.識別)
        真的確認錨點(一筆, 目標)

    monkeypatch.setattr(執行器, "_確認錨點", _記一次)

    with pytest.raises(執行器.負控錯誤) as 炸的:
        執行器.執行變異(錨點失效的, 根目錄=假專案)
    訊息 = str(炸的.value)

    assert not 走到確認錨點, (
        f"這一筆在 `_確認錨點` 之前就該被前面那道檢查擋下，實際走到了：{走到確認錨點}"
    )
    assert 識別 in 訊息, f"最早炸的那道檢查沒指名是哪把刀：{訊息}"
    assert "登記們/負控錨點.py" in 訊息, f"最早炸的那道檢查沒說這把刀登記在哪個檔：{訊息}"
    assert "實際 0" in 訊息, f"最早炸的那道檢查沒說實際命中幾次：{訊息}"
    assert f'識別="{識別}"' in 訊息, f"最早炸的那道檢查沒指到登記裡要改的那一筆：{訊息}"
    assert "把錨點改成目標檔現在的原文" in 訊息, f"最早炸的那道檢查沒說重釘要改成什麼：{訊息}"
    assert "替換標記行" in 訊息, f"最早炸的那道檢查沒說可以改用標記錨：{訊息}"

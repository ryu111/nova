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

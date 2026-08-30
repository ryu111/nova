"""使用者說的那句話：**「下次有人問『8% 這個門檻哪來的』，要答得出來。」**

`docs/研究/` 放的是外部知識——業界怎麼做、論文說什麼、數字哪來的。
它跟 `docs/設計/`（我們的決定）分開，因為**混在一起之後沒人分得出
哪句是出處說的、哪句是我們推的**。

## 為什麼要測

README 裡寫著「每份開頭要寫誰產的、什麼時候、用什麼題目問的」。
**只寫在 README 裡的規矩等於不存在**——下一份研究存進來的人不會讀它。
研究會過期，而判斷有沒有過期需要日期；委派給哪一家會影響可信度
（不同家的失敗形態不一樣），所以產出者也要留。
"""

import re
from pathlib import Path

import pytest

研究目錄 = Path(__file__).resolve().parent.parent.parent / "docs" / "研究"
_日期 = re.compile(r"20\d\d-\d\d-\d\d")
#: 抬頭要在最前面。埋在中間等於沒有——讀的人第一眼看不到就會當成我們自己寫的。
_抬頭幾行 = 12


def _研究們() -> list[Path]:
    return sorted(路 for 路 in 研究目錄.glob("*.md") if 路.name != "README.md")


def test_研究目錄有東西() -> None:
    """空的話下面那些 parametrize 會一支都不跑，而**零支測試也是綠的**。"""
    assert _研究們(), f"{研究目錄} 是空的"


@pytest.mark.parametrize("研究", _研究們(), ids=lambda 路: 路.stem)
class Test每份研究都要交代來歷:
    def test_寫得出誰產的(self, 研究: Path) -> None:
        """**不同家的失敗形態不一樣**，可信度要連著來源一起讀。"""
        抬頭 = "\n".join(研究.read_text(encoding="utf-8").splitlines()[:_抬頭幾行])

        assert "產出者：" in 抬頭, f"{研究.name} 前 {_抬頭幾行} 行沒交代誰產的"

    def test_寫得出什麼時候(self, 研究: Path) -> None:
        """**研究會過期**，而判斷過期需要日期。"""
        抬頭 = "\n".join(研究.read_text(encoding="utf-8").splitlines()[:_抬頭幾行])

        assert _日期.search(抬頭), f"{研究.name} 前 {_抬頭幾行} 行沒有日期"

    def test_寫得出當初問了什麼(self, 研究: Path) -> None:
        """**答案的形狀由問題決定。** 沒有題目就看不出它為什麼沒講到某件事。"""
        抬頭 = "\n".join(研究.read_text(encoding="utf-8").splitlines()[:_抬頭幾行])

        assert "問法：" in 抬頭, f"{研究.name} 前 {_抬頭幾行} 行沒交代當初怎麼問的"

    def test_講明是外部資料不是我們的決定(self, 研究: Path) -> None:
        """**這是這個資料夾存在的理由。** 少了這句，下一個人會把它當規格。"""
        抬頭 = "\n".join(研究.read_text(encoding="utf-8").splitlines()[:_抬頭幾行])

        assert "不是 nova 的設計決定" in 抬頭, f"{研究.name} 沒講明它是外部資料"

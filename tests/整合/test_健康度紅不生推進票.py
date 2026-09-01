"""主線紅的時候不准再生推進票——背壓。

**紅的時候往佇列丟工作，只是把紅的東西堆更高。** `載體/健康度.py` 的閘
早就寫好、有測試、有四項各紅一次的窮舉，**但沒有任何人呼叫它**——
規範存在、可達性不存在，就是「以為有保證、其實沒有」（CLAUDE.md 判準第 1 條）。

閘接在 `空手時落一張票` **裡面**，不接在呼叫端：`命令列.py` 有兩個呼叫點
（`nova 跑` 空手那條、`nova 收件` 空手那條），閘放在呼叫端就是
「有一個忘了就等於沒有」。
"""

from pathlib import Path

import pytest

from nova.載體.健康度 import 健康度指標
from nova.載體.收件 import 待處理, 收件目錄
from nova.載體.缺口成票 import 空手時落一張票

_目標對照 = """# 某專案的目標對照

## 所以下一批該做什麼

**一、把記帳的匯出補完**

匯出只支援 CSV，缺 JSON。
"""


@pytest.fixture
def 假專案(tmp_path: Path) -> Path:
    專案 = tmp_path / "某專案"
    (專案 / "docs").mkdir(parents=True)
    (專案 / "docs" / "目標.md").write_text(_目標對照, encoding="utf-8")
    return 專案


def _全綠() -> 健康度指標:
    return 健康度指標(main綠嗎=True, 卡住的線數=0, 沒收尾的件數=0, 壞掉的PR數=0)


class Test健康度擋得住推進票:
    def test_全綠才落得了票(self, 假專案: Path) -> None:
        """基準線：這支綠的，下面兩支才證明得了是健康度擋的。"""
        結果 = 空手時落一張票(假專案, 查指標=lambda _: _全綠())

        assert 結果.票 is not None, 結果.擋下的理由
        assert 結果.擋下的理由 is None
        assert 待處理(收件目錄(假專案)) == [結果.票]

    def test_main紅就不生票而且講得出是哪一項(self, 假專案: Path) -> None:
        紅 = 健康度指標(main綠嗎=False, 卡住的線數=0, 沒收尾的件數=0, 壞掉的PR數=0)

        結果 = 空手時落一張票(假專案, 查指標=lambda _: 紅)

        assert 結果.票 is None, "主線紅還在生推進票——背壓沒接上"
        assert 結果.擋下的理由 is not None
        assert "main的CI" in 結果.擋下的理由, 結果.擋下的理由
        assert 待處理(收件目錄(假專案)) == [], "被擋下就不准有任何檔案落進收件匣"

    def test_查不到也不生票(self, 假專案: Path) -> None:
        """算不出來往安全那邊倒——不知道修理跟不跟得上時多生一張是拿看不見的東西下注。"""
        查不到 = 健康度指標(main綠嗎=None, 卡住的線數=0, 沒收尾的件數=0, 壞掉的PR數=0)

        結果 = 空手時落一張票(假專案, 查指標=lambda _: 查不到)

        assert 結果.票 is None
        assert 結果.擋下的理由 is not None
        assert "查不到" in 結果.擋下的理由, 結果.擋下的理由

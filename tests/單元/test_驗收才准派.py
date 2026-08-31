"""自主派工必須帶機械驗收。**沒有驗收的任務等於沒有停止條件。**

`契約/分派.py` 早就有 `缺驗收條件` 這個拒絕代碼、`迴圈/計畫.py` 也有驗證器，
但整套**零呼叫端**——沒有接上任何一條路的驗收機制，
按 CLAUDE.md 的判準等於不存在。這一格是把它接上的第一條路。

## 為什麼邊界劃在「自主 vs 人給」而不是「所有任務」

人敲 `nova 問 "看看這段為什麼慢"` 的時候，驗收是**他自己看**——
他在現場，做錯了他當場知道。逼他每次都寫驗收指令只會讓他改走別條路進來，
於是這道閘等於不存在。

自主生的票沒有人在現場。它做完之後下一輪直接接著做，
這時候「做完了」跟「做壞了」長得一模一樣。

所以判準是**誰在現場**，不是**任務難不難**。
"""

from pathlib import Path

import pytest

from nova.載體.收件 import (
    丟一件,
    你敲,
    協定,
    待處理,
    時鐘,
    檔案,
    要驗收嗎,
    讀出驗收,
)


class Test讀出驗收:
    """驗收指令怎麼從票的內容裡讀出來。"""

    def test_沒有標記就是沒有驗收(self) -> None:
        """**不是錯誤，是空的。** 手丟的票本來就不帶標記。"""
        assert 讀出驗收("把某某做完") == ()

    def test_一條指令(self) -> None:
        內容 = "把某某做完\n\n<!--nova:驗收 uv run pytest -k 某某-->\n"
        assert 讀出驗收(內容) == ("uv run pytest -k 某某",)

    def test_多條各自一個標記(self) -> None:
        """**多條是 and，全部要綠。**

        順序照原文，不排序——排序的話「先跑快的」這種安排會被靜默打亂。
        """
        內容 = (
            "把某某做完\n\n"
            "<!--nova:驗收 uv run pytest -k 某某-->\n"
            "<!--nova:驗收 uv run nova 閘 提交-->\n"
        )
        assert 讀出驗收(內容) == ("uv run pytest -k 某某", "uv run nova 閘 提交")

    def test_接續標記不會被當成驗收(self) -> None:
        """接續票也是 `<!--nova:...-->` 開頭，**兩種標記不准互相汙染**。

        混到的話接續票會憑空長出一條驗收，而那條指令是 `輪次=2`，跑不動。
        """
        內容 = "把某某做完\n\n<!--nova:接續 輪次=2 上一輪=abc-->\n上一輪走到這\n"
        assert 讀出驗收(內容) == ()

    def test_空白的驗收不算驗收(self) -> None:
        """`<!--nova:驗收 -->` 是一張**看起來有、其實沒有**的票。

        放行的話它會變成最貴的那種假綠：閘在、標記在、守不到任何東西。
        """
        assert 讀出驗收("做完\n\n<!--nova:驗收   -->\n") == ()


class Test誰要帶驗收:
    """哪些來源的票沒帶驗收就不准派。"""

    @pytest.mark.parametrize("來源", [時鐘, 協定])
    def test_自主來源要帶(self, 來源: str) -> None:
        """排程與協定派的票**沒有人在現場**。"""
        assert 要驗收嗎(來源) is True

    @pytest.mark.parametrize("來源", [你敲, 檔案])
    def test_人給的不用帶(self, 來源: str) -> None:
        """`你敲` 是他打字進來的，`檔案` 是他 cp 進去的——兩種都有人在現場。"""
        assert 要驗收嗎(來源) is False


class Test丟一件擋下沒驗收的自主票:
    """開跑前拒絕，不是跑完才發現。"""

    def test_自主票沒帶驗收不准派(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="驗收"):
            丟一件("把某某做完", 來源=時鐘, 目錄=tmp_path)

    def test_被擋下的票不准留在收件匣(self, tmp_path: Path) -> None:
        """**拋了例外但檔案已經寫進去**是最陰的那種假綠。

        呼叫端多半會 `except ValueError: 記一筆` 然後往下走，
        於是那張本來該被擋掉的票安安靜靜躺在佇列裡等下一輪撿走。
        """
        with pytest.raises(ValueError, match="驗收"):
            丟一件("把某某做完", 來源=時鐘, 目錄=tmp_path)
        assert 待處理(tmp_path) == []

    def test_自主票帶了驗收就派得出去(self, tmp_path: Path) -> None:
        落點 = 丟一件(
            "把某某做完\n\n<!--nova:驗收 uv run pytest -k 某某-->",
            來源=時鐘,
            目錄=tmp_path,
        )
        assert 待處理(tmp_path) == [落點]

    @pytest.mark.parametrize("來源", [你敲, 檔案])
    def test_人給的票不帶驗收照樣派(self, 來源: str, tmp_path: Path) -> None:
        """**這一格是刻意放行的**，不是漏掉的。人在現場，驗收是他自己看。"""
        落點 = 丟一件("看看這段為什麼慢", 來源=來源, 目錄=tmp_path)
        assert 待處理(tmp_path) == [落點]

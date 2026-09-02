"""哪些改動過的檔案可以當成指定 pytest 目標。

這條政策原本只有整合測試從 `迴圈` 那份副本間接走到，`載體.判準` 這份——
也就是兩個正式入口（`nova.__init__`、`載體.命令列`）真的注入的那一份——
一支測試都沒有。負控刀砍它時是 WRONG_TEST（該紅的測試根本沒覆蓋到那行），
等於這個保證只是宣稱。這支測試補上背書。
"""

import pytest

from nova.載體.判準 import 可作指定pytest目標


class Test不能當指定目標的非測試檔:
    @pytest.mark.parametrize(
        "路徑",
        [
            #: 2026-09-02 09:50 實測（run 92cfcd）：測試員新增的 CSS fixture 被當成
            #: pytest 目標 → `ERROR: not found`（exit 4）→ 驗證紅收成「結果未知」。
            "tests/資料/儀表板設計稿CSS.css",
            #: 2026-09-02 01:34 實測（run 128d6f）：同一個洞的第二次，換成 .json 與 .md。
            "tests/整合/實錄/agy_timeout.json",
            "tests/整合/實錄/README.md",
            #: 副檔名對了也不算：pytest 的 `python_files` 收不到這種名字的檔，
            #: 硬餵進去是 exit 5（沒收集到任何測試）——這個洞還沒被人踩到，先關上。
            "tests/負控/跑前體檢.py",
            "tests/單元/輔助.py",
        ],
    )
    def test_pytest收集不到的檔不能當目標(self, 路徑: str) -> None:
        """判準要問的是「pytest 收得到嗎」，不是「這個檔在不在黑名單上」。

        deny-list 每補一條就等下一種副檔名開第四次洞；allow-list 對齊
        pytest 自己的 `python_files`（`test_*.py`／`*_test.py`），一次關完。
        """
        assert not 可作指定pytest目標(路徑)

    def test_負控登記們底下的資料模組不行(self) -> None:
        """登記們裡面是變異資料，沒有測試函式，拿去跑 pytest 會 exit 5。"""
        assert not 可作指定pytest目標("tests/負控/登記們/動測試護欄.py")

    def test_登記們用絕對路徑也擋得住(self) -> None:
        assert not 可作指定pytest目標("/Users/x/nova/tests/負控/登記們/某某.py")

    def test_負控的登記與執行器本身不行(self) -> None:
        assert not 可作指定pytest目標("tests/負控/登記.py")
        assert not 可作指定pytest目標("tests/負控/執行器.py")

    def test_conftest與套件初始化不行(self) -> None:
        assert not 可作指定pytest目標("tests/conftest.py")
        assert not 可作指定pytest目標("tests/整合/__init__.py")


class Test真的測試檔可以當指定目標:
    def test_一般測試檔可以(self) -> None:
        assert 可作指定pytest目標("tests/單元/test_工作流.py")

    def test_尾綴式命名的測試檔也可以(self) -> None:
        """`python_files` 預設是 `test_*.py` **和** `*_test.py`，兩種都收得到。

        allow-list 只寫前綴的話，尾綴式命名的檔會被判成「不能當目標」而退回全套跑，
        誠實但白花時間；repo 現在剛好沒有這種命名，所以只有這支測試守得住那半條。
        """
        assert 可作指定pytest目標("tests/單元/工作流_test.py")
        assert 可作指定pytest目標("/Users/x/nova/tests/整合/命令列_test.py")

    def test_負控自己那支真測試可以(self) -> None:
        """`tests/負控/` 不是整個目錄都擋，擋的是登記們與非測試模組。"""
        assert 可作指定pytest目標("tests/負控/test_登記的變異會被殺.py")

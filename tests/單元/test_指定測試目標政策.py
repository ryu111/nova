"""哪些改動過的檔案可以當成指定 pytest 目標。

這條政策原本只有整合測試從 `迴圈` 那份副本間接走到，`載體.判準` 這份——
也就是兩個正式入口（`nova.__init__`、`載體.命令列`）真的注入的那一份——
一支測試都沒有。負控刀砍它時是 WRONG_TEST（該紅的測試根本沒覆蓋到那行），
等於這個保證只是宣稱。這支測試補上背書。
"""

from nova.載體.判準 import 可作指定pytest目標


class Test不能當指定目標的非測試檔:
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

    def test_負控自己那支真測試可以(self) -> None:
        """`tests/負控/` 不是整個目錄都擋，擋的是登記們與非測試模組。"""
        assert 可作指定pytest目標("tests/負控/test_登記的變異會被殺.py")

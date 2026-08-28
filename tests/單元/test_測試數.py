"""「刪測試不是簡化，是拆掉驗收機制」的機械化版本。"""

from nova.載體.測試數 import 數測試, 比較測試數


def test_數出測試函式數量() -> None:
    內容 = "def test_甲() -> None:\n    pass\n\n\ndef test_乙() -> None:\n    pass\n"
    assert 數測試(內容) == 2


def test_不把普通函式當測試() -> None:
    assert 數測試("def 幫手() -> None:\n    pass\n") == 0


def test_不把字串裡的_def_test_當測試() -> None:
    assert 數測試('訊息 = "def test_假的"\n') == 0


def test_數量減少要擋() -> None:
    通過, 證據 = 比較測試數(18, 17)
    assert 通過 is False
    assert "18" in 證據 and "17" in 證據


def test_數量持平放行() -> None:
    assert 比較測試數(18, 18)[0] is True


def test_數量增加放行() -> None:
    assert 比較測試數(18, 25)[0] is True

"""阿姆達爾定律門禁：serial 測試佔比不可超過門檻。

業界實測：serial 測試若沒有門禁，每季自然增長 15~25%。
而阿姆達爾定律鎖死平行加速比——10% 的測試是 serial，再多核心也快不過總時間的十分之一。
nova 現在 serial 6 支、全部約 930 支（0.6%），門檻抓 8% 留很大餘裕，
守的是「有沒有人在看」，不是現在的數字。
"""

from nova.載體.serial佔比 import 判定serial佔比, 預設門檻


def test_預設門檻為百分之八() -> None:
    assert 預設門檻 == 0.08


def test_佔比低於門檻放行() -> None:
    通過, _ = 判定serial佔比(6, 930)
    assert 通過 is True


def test_佔比剛好等於門檻放行() -> None:
    通過, _ = 判定serial佔比(8, 100, 門檻=0.08)
    assert 通過 is True


def test_佔比超過門檻要擋下並給出具體原因() -> None:
    通過, 證據 = 判定serial佔比(9, 100, 門檻=0.08)
    assert 通過 is False
    assert "9" in 證據  # 印出現在幾支 serial
    assert "9.0%" in 證據 or "9%" in 證據  # 印出佔比
    assert "8.0%" in 證據 or "8%" in 證據  # 印出門檻
    assert "超過門檻不是調高門檻，是把那些測試的共享狀態拆掉" in 證據


def test_支援自訂門檻供負控使用() -> None:
    通過, 證據 = 判定serial佔比(6, 930, 門檻=0.001)
    assert 通過 is False
    assert "6" in 證據
    assert "0.1%" in 證據
    assert "超過門檻不是調高門檻，是把那些測試的共享狀態拆掉" in 證據


def test_總數為零時放行() -> None:
    """沒有測試時不該除以零炸開。"""
    通過, _ = 判定serial佔比(0, 0)
    assert 通過 is True

"""帳本的 schema：欄位對應表要窮舉，落盤的鍵一律 ASCII。

這一層不碰檔案，所以住單元層。真的寫出去的行為在 `tests/整合/test_帳本落盤.py`。

**為什麼對應表要窮舉測試**：事件的欄位名是中文（CLAUDE.md 的預設），
落盤的鍵必須 ASCII（跨程序，例外條款）。中間那張表少對應一個欄位，
那個欄位就會靜默地不落盤——帳本照樣有檔案、照樣每行都是合法 JSON，
只是少了一格。這種漏法沒有測試抓不到。
"""

from dataclasses import fields

from nova.契約.帳本 import 事件, 事件種類, 欄位對應, 落盤時加的鍵


def test_每個欄位都有對應() -> None:
    assert {欄.name for 欄 in fields(事件)} == set(欄位對應)


def test_對應出去的鍵都是ASCII() -> None:
    for 中, 英 in 欄位對應.items():
        assert 英.isascii(), f"{中} 對到非 ASCII 的 {英}"


def test_對應出去的鍵不重複() -> None:
    """兩個欄位對到同一個鍵＝後寫的把先寫的蓋掉，而且不會有任何錯誤。"""
    assert len(set(欄位對應.values())) == len(欄位對應)


def test_落盤時加的鍵不跟欄位撞() -> None:
    """`run`／`seq`／`ts` 由 sink 自己加。撞名的話事件會蓋掉它們，序號就對不上了。"""
    assert not (set(落盤時加的鍵) & set(欄位對應.values()))


def test_事件種類的值都是ASCII() -> None:
    for 種 in 事件種類:
        assert 種.value.isascii(), 種


def test_成對的事件都在() -> None:
    """只有結束沒有開始的話，nova 被殺掉時連「哪一家正在跑」都看不出來。"""
    assert {事件種類.呼叫開始, 事件種類.呼叫結束} <= set(事件種類)
    assert {事件種類.階段開始, 事件種類.階段結束} <= set(事件種類)

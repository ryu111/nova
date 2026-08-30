"""重構員不准動測試——這條要是機械的，不是提示裡的懇求。

## 為什麼

`迴圈/角色提示.py` 的重構員第一條規矩就是「不准改任何測試檔。測試是驗收機制，
動它等於自己給自己發及格證」。那句話寫在**提示**裡——模型可以忽略它，
而且忽略了沒有人會發現：測試被改掉之後跑出來還是綠的。

CLAUDE.md 的判準：規則寫在 prompt 裡是虛線的懇求，寫在包住執行者的
程式碼裡才是實線的包圍環。所以驗收權不在執行者手上。

## 判準是「跑之前 vs 跑之後」

不是「模型說它沒改」。拍兩張快照比對，差在哪一個檔就是誰被動了。
**新增與刪除都算**：刪掉一支測試是最嚴重的那種，而它在「內容比對」裡
長得像什麼都沒發生。

純函式，不碰硬碟（快照由呼叫端拍），所以住單元層。
"""

from nova.載體.重構護欄 import 動到測試了嗎


class Test動到測試了嗎:
    def test_什麼都沒動就沒事(self) -> None:
        前 = {"tests/單元/test_甲.py": "aaa", "src/nova/乙.py": "bbb"}

        assert 動到測試了嗎(前, dict(前)) == ()

    def test_改了測試的內容要抓出來(self) -> None:
        前 = {"tests/單元/test_甲.py": "aaa"}
        後 = {"tests/單元/test_甲.py": "被改過了"}

        assert 動到測試了嗎(前, 後) == ("tests/單元/test_甲.py",)

    def test_刪掉一支測試是最嚴重的那種(self) -> None:
        """**刪掉在「內容比對」裡長得像什麼都沒發生。**

        少了這一條，重構員把礙事的測試刪掉就過關了——而
        `CLAUDE.md` 說刪測試不是簡化，是拆掉驗收機制。
        """
        前 = {"tests/單元/test_甲.py": "aaa", "tests/單元/test_乙.py": "bbb"}
        後 = {"tests/單元/test_甲.py": "aaa"}

        assert 動到測試了嗎(前, 後) == ("tests/單元/test_乙.py",)

    def test_新增測試也算動到(self) -> None:
        """重構員的工作是「不改行為地清乾淨」，**加測試是測試員的事**。

        放行新增的話，重構員可以加一支永遠綠的測試來墊高覆蓋率數字。
        """
        前: dict[str, str] = {}
        後 = {"tests/單元/test_新的.py": "aaa"}

        assert 動到測試了嗎(前, 後) == ("tests/單元/test_新的.py",)

    def test_改實作不算動到測試(self) -> None:
        """**不能擋到正常用法**——重構的定義就是改實作。"""
        前 = {"src/nova/甲.py": "aaa", "tests/單元/test_甲.py": "ccc"}
        後 = {"src/nova/甲.py": "整理過了", "tests/單元/test_甲.py": "ccc"}

        assert 動到測試了嗎(前, 後) == ()

    def test_conftest與fixture也是測試(self) -> None:
        """`conftest.py` 不叫 `test_` 開頭，但動它等於動了每一支測試。"""
        前 = {"tests/conftest.py": "aaa"}
        後 = {"tests/conftest.py": "被改過了"}

        assert 動到測試了嗎(前, 後) == ("tests/conftest.py",)

    def test_多個檔按路徑排序(self) -> None:
        """**順序要穩定**：不穩定的話同一次違規每次印出來不一樣，沒辦法比對。"""
        前 = {"tests/b.py": "1", "tests/a.py": "1"}
        後 = {"tests/b.py": "2", "tests/a.py": "2"}

        assert 動到測試了嗎(前, 後) == ("tests/a.py", "tests/b.py")

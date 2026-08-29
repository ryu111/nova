"""收件檔出現＝一次派工。**檔案就是事件。**

路線圖觸發層那四格裡，只有這一格的副標寫著「唯一的橋」——因為檔案是
唯一一種不綁任何一家 LLM、不綁任何一個宿主、`ls` 就看得到佇列的事件形式。
排程到期與 MCP 派票最後都應該收斂成「往收件匣丟一個檔」。

**收件匣不准住在工作目錄裡**，理由跟進度檔同一條，但更嚴重：
進度檔放錯只是讓模型替未來的自己種話，收件匣放錯是讓**執行者自己派工給自己**
——一個能寫工作目錄的模型可以無限次觸發自己。

會碰硬碟，所以住整合層。
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nova.載體.帳本 import 預設帳本目錄
from nova.載體.收件 import _檔名時戳, 丟一件, 你敲, 完成一件, 待處理, 收下一件, 收件目錄, 誰造的


def _丟一件(目錄: Path, 檔名: str, 內容: str = "把某件事做完") -> Path:
    目錄.mkdir(parents=True, exist_ok=True)
    路徑 = 目錄 / 檔名
    路徑.write_text(內容, encoding="utf-8")
    return 路徑


class Test落點:
    """跟帳本、已處理同一條規則：存在專案外面、用專案當鍵。"""

    def test_收件匣不在工作目錄裡(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """**這是這一格最重要的一條。**

        收件匣如果落在工作目錄裡，一個能寫檔的模型就能往自己的收件匣丟東西
        ——那不是「有記憶」，那是無限迴圈，而且是模型自己開的。
        """
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        專案 = tmp_path / "某個專案"
        專案.mkdir()

        assert 專案.resolve() not in 收件目錄(專案).parents

    def test_跟帳本住同一個專案資料夾(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        專案 = tmp_path / "某個專案"
        專案.mkdir()

        assert 收件目錄(專案).parent == 預設帳本目錄(專案).parent

    def test_不同專案分得開(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        甲 = tmp_path / "甲"
        乙 = tmp_path / "乙"
        for 專案 in (甲, 乙):
            專案.mkdir()

        assert 收件目錄(甲) != 收件目錄(乙)


class Test佇列:
    def test_目錄不存在時是空的不是炸掉(self, tmp_path: Path) -> None:
        """第一次跑的時候收件匣本來就還沒有。"""
        assert 待處理(tmp_path / "還沒有") == []

    def test_先丟的先處理(self, tmp_path: Path) -> None:
        """**先進先出**，不然先丟的那件可能永遠排不到。"""
        for 名 in ("20260830T010000Z-乙.md", "20260829T010000Z-甲.md"):
            _丟一件(tmp_path, 名)

        assert [路.name for 路 in 待處理(tmp_path)] == [
            "20260829T010000Z-甲.md",
            "20260830T010000Z-乙.md",
        ]

    def test_子目錄不算收件(self, tmp_path: Path) -> None:
        """`處理中/` 與 `失敗/` 就住在收件匣旁邊，掃到它們會變成無限迴圈。"""
        _丟一件(tmp_path, "真的一件.md")
        (tmp_path / "處理中").mkdir()

        assert [路.name for 路 in 待處理(tmp_path)] == ["真的一件.md"]


class Test收下:
    """收下＝把檔案從收件匣**移走**。移走是宣告所有權。"""

    def test_收下之後就不在佇列裡了(self, tmp_path: Path) -> None:
        """**沒有這一條就會重複執行。** 副作用做兩次，而且看起來完全正常。"""
        _丟一件(tmp_path, "一件.md")

        一件 = 收下一件(tmp_path)

        assert 一件 is not None
        assert 待處理(tmp_path) == []

    def test_收下的內容就是任務(self, tmp_path: Path) -> None:
        _丟一件(tmp_path, "一件.md", "把程序收割做完")

        一件 = 收下一件(tmp_path)

        assert 一件 is not None
        assert 一件.任務 == "把程序收割做完"
        assert 一件.名稱 == "一件"

    def test_空的收件匣回None(self, tmp_path: Path) -> None:
        assert 收下一件(tmp_path) is None

    def test_兩個程序不會拿到同一件(self, tmp_path: Path) -> None:
        """**搶同一件會讓工作做兩次。**

        靠 `rename` 的原子性：同一個檔只有一個 rename 會成功，
        另一個拿到 `FileNotFoundError`，然後去看下一件。
        """
        _丟一件(tmp_path, "只有一件.md")

        第一個 = 收下一件(tmp_path)
        第二個 = 收下一件(tmp_path)

        assert 第一個 is not None
        assert 第二個 is None

    def test_空白檔案不算一件(self, tmp_path: Path) -> None:
        """沒有任務內容的檔案派不出工，但它會一直卡在佇列最前面。

        **檔名要讓空的那個排前面。** 第一版寫成「空的.md」與「真的.md」，
        負控（讓空白也算一件）沒有紅——因為「真」的碼位比「空」小，
        真的那件本來就排前面，這支測試根本沒走到要守的那條分支。
        """
        _丟一件(tmp_path, "01-空的.md", "   \n")
        _丟一件(tmp_path, "02-真的.md", "真的有事")

        一件 = 收下一件(tmp_path)

        assert 一件 is not None
        assert 一件.任務 == "真的有事"


class Test完成:
    def test_完成之後原始請求留在已處理旁邊(self, tmp_path: Path) -> None:
        """**成果要對得回請求。**

        成果帳本說「這件收在護欄」，你要看得到當初丟進來的是什麼。
        兩邊靠執行識別碼配對，跟事件帳本同一條規則。
        """
        _丟一件(tmp_path / "收件", "一件.md", "原始的請求內容")
        一件 = 收下一件(tmp_path / "收件")
        assert 一件 is not None

        落點 = 完成一件(一件, 執行識別碼="20260830T120000Z-abc", 已處理=tmp_path / "已處理")

        assert 落點.read_text(encoding="utf-8") == "原始的請求內容"
        assert "20260830T120000Z-abc" in 落點.name

    def test_完成之後處理中是空的(self, tmp_path: Path) -> None:
        """留在 `處理中/` 的就是「開始了但沒收尾」——那一格要誠實。"""
        _丟一件(tmp_path / "收件", "一件.md")
        一件 = 收下一件(tmp_path / "收件")
        assert 一件 is not None

        完成一件(一件, 執行識別碼="20260830T120000Z-abc", 已處理=tmp_path / "已處理")

        assert list((tmp_path / "收件" / "處理中").iterdir()) == []


def test_沒收尾的看得出來(tmp_path: Path) -> None:
    """**收下了卻沒完成的那些，要留得住。**

    程序被殺掉的時候，那一件已經不在佇列裡了——如果它就這樣消失，
    使用者會以為工作做完了。留在 `處理中/` 才看得出「開始了，不知道結果」。
    """
    _丟一件(tmp_path, "一件.md")

    收下一件(tmp_path)

    assert [路.name for 路 in (tmp_path / "處理中").iterdir()]


class Test丟一件產出的檔名:
    """**檔名不是裝飾，是三個保證的載體。**

    時戳讓 `ls` 就是時序（先進先出靠的是它）、來源讓成果帳分得出是誰觸發的、
    亂碼讓同一秒敲兩次不會互相蓋掉。少一段就少一個保證，
    而三個都是**沒有症狀**地壞掉。
    """

    def test_開頭是讀得回來的時戳(self, tmp_path: Path) -> None:
        """**跟帳本的執行識別碼同一個格式。**

        兩邊走散的話「先進先出」會靜默壞掉：`待處理` 照檔名排序，
        排出來的就不再是時序，而佇列看起來完全正常。
        """
        落點 = 丟一件("做某件事", 來源=你敲, 目錄=tmp_path)

        datetime.strptime(落點.name.split("-")[0], _檔名時戳).replace(tzinfo=UTC)

    def test_同一秒丟兩件不會互相蓋掉(self, tmp_path: Path) -> None:
        """蓋掉的話，使用者連敲兩次會少做一件——而且沒有任何錯誤訊息。"""
        甲 = 丟一件("同一句話", 來源=你敲, 目錄=tmp_path)
        乙 = 丟一件("同一句話", 來源=你敲, 目錄=tmp_path)

        assert 甲 != 乙
        assert len(待處理(tmp_path)) == 2

    def test_排序出來就是丟進去的順序(self, tmp_path: Path) -> None:
        """**這一支釘的是「`ls` 就是時序」。**

        題目的字面順序跟時間順序相反時才測得出來：時戳掉了的話，
        `待處理` 會照題目的字排，先丟的反而排後面。
        """
        先 = 丟一件("乙乙乙先丟的", 來源=你敲, 目錄=tmp_path)
        後 = 丟一件("甲甲甲後丟的", 來源=你敲, 目錄=tmp_path)

        assert [路.name for 路 in 待處理(tmp_path)] == [先.name, 後.name]

    def test_來源讀得回來(self, tmp_path: Path) -> None:
        落點 = 丟一件("做某件事", 來源=你敲, 目錄=tmp_path)

        assert 誰造的(落點.name) == 你敲

    def test_不認得的來源要當場炸(self, tmp_path: Path) -> None:
        """悄悄接受的話，成果帳上會出現一個沒有人認得的 `source`。"""
        with pytest.raises(ValueError, match="不認得的來源"):
            丟一件("做某件事", 來源="隨便寫的", 目錄=tmp_path)

    def test_空題目派不出工(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="空的"):
            丟一件("   \n  ", 來源=你敲, 目錄=tmp_path)

    def test_題目有斜線也放得進檔名(self, tmp_path: Path) -> None:
        """題目是使用者打的字，什麼都可能有。炸掉的話 `nova 跑` 會挑題目。"""
        落點 = 丟一件("修 src/nova/載體/收件.py 的 bug", 來源=你敲, 目錄=tmp_path)

        assert 落點.is_file()
        assert "/" not in 落點.name

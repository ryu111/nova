"""工作流的控制流程：純函式轉移，零 LLM、零子程序。

寫成**表**不是 `if` 鏈的理由有三個：印得出來（可以直接進 journal）、
測得動（就是這支測試）、加階段只要加一列（開放封閉）。
"""

import dataclasses

import pytest

from nova.契約.工作流 import 審查判定, 步驟結果, 種類, 結束, 結束代碼, 階段代碼, 階段定義
from nova.契約.模型回應 import 終局
from nova.迴圈.狀態機 import TDD階段表, 下一步, 查階段


def _結果(
    終: 終局 = 終局.成功,
    *,
    判準綠: bool | None = None,
    審查結論: 審查判定 | None = None,
) -> 步驟結果:
    return 步驟結果(階段=階段代碼.測試, 終局=終, 判準綠=判準綠, 證據="", 審查結論=審查結論)


class TestTDD順序:
    def test_五個階段的順序(self) -> None:
        """規則明文：先寫會紅的測試 → 跑它親眼看到它紅 → 最少的碼讓它綠 → 全綠下重構。"""
        assert [階段.代碼 for 階段 in TDD階段表] == [
            階段代碼.測試,
            階段代碼.驗證紅,
            階段代碼.實作,
            階段代碼.驗證綠,
            階段代碼.審查,
        ]

    def test_階段表涵蓋所有階段代碼(self) -> None:
        """加了 enum 成員卻沒進表——這支會紅。"""
        assert {階段.代碼 for 階段 in TDD階段表} == set(階段代碼)

    def test_驗證是機械的不是模型(self) -> None:
        """驗收權不在執行者手上——硬規則 4 禁止自寫自評。"""
        判準的 = {階段.代碼 for 階段 in TDD階段表 if 階段.種類 is 種類.判準}
        assert 判準的 == {階段代碼.驗證紅, 階段代碼.驗證綠}

    def test_驗證紅期望的是紅不是綠(self) -> None:
        """「跑它，親眼看到它紅」——沒看到紅就不知道它到底在測什麼。"""
        assert 查階段(階段代碼.驗證紅).期望綠 is False
        assert 查階段(階段代碼.驗證綠).期望綠 is True

    def test_模型階段沒有期望綠(self) -> None:
        for 階段 in TDD階段表:
            if 階段.種類 is 種類.模型:
                assert 階段.期望綠 is None


class Test轉移:
    def test_一路順利就往下走(self) -> None:
        assert 下一步(查階段(階段代碼.測試), _結果()) is 階段代碼.驗證紅
        assert 下一步(查階段(階段代碼.實作), _結果()) is 階段代碼.驗證綠

    def test_驗證紅真的紅了才准往下(self) -> None:
        assert 下一步(查階段(階段代碼.驗證紅), _結果(判準綠=False)) is 階段代碼.實作

    def test_驗證紅居然是綠的要退回測試(self) -> None:
        """一支永遠綠的測試等於沒有測試——不能讓它混過去。"""
        assert 下一步(查階段(階段代碼.驗證紅), _結果(判準綠=True)) is 階段代碼.測試

    def test_驗證綠沒過要退回實作(self) -> None:
        """這就是 fallback 那條回頭邊——鏈式寫法表達不了它。"""
        assert 下一步(查階段(階段代碼.驗證綠), _結果(判準綠=False)) is 階段代碼.實作

    def test_審查通過才結束(self) -> None:
        終 = 下一步(查階段(階段代碼.審查), _結果(審查結論=審查判定.通過))
        assert isinstance(終, 結束)
        assert 終.代碼 is 結束代碼.完成

    def test_審查要求修改要退回實作(self) -> None:
        """第三條回頭邊。審出問題就回去改，不是結束。"""
        assert 下一步(查階段(階段代碼.審查), _結果(審查結論=審查判定.要求修改)) is 階段代碼.實作

    def test_審查沒給判定一律中止(self) -> None:
        """**這支守的是一個真的發生過的假成功。**

        審查階段原本歸在 `種類.模型`，而模型階段「跑完就算達到期望」——
        所以審查員回「設計有重大問題，不通過」，只要 CLI 結束碼是 0，
        工作流照樣宣布「全綠且通過審查」。

        fail-closed：讀不出判定就停下來讓人看。讀不出來跟「它說可以」是兩件事。
        """
        for 結論 in (審查判定.沒給結論, None):
            終 = 下一步(查階段(階段代碼.審查), _結果(審查結論=結論))
            assert isinstance(終, 結束), f"{結論} 竟然往下走了"
            assert 終.代碼 is 結束代碼.中止
            assert "沒給判定" in 終.原因


class Test結果未知:
    @pytest.mark.parametrize("代碼", list(階段代碼))
    def test_任何階段結果未知都要停(self, 代碼: 階段代碼) -> None:
        """結果未知＝不知道做了沒。往下走或退回重做，都可能把做過的事再做一次。

        at-most-once：寧漏不重。這一條蓋過所有階段的個別轉移。
        """
        終 = 下一步(查階段(代碼), _結果(終局.結果未知))
        assert isinstance(終, 結束), f"{代碼} 遇到結果未知竟然還往下走"
        assert 終.代碼 is 結束代碼.中止
        assert "未知" in 終.原因

    def test_確定失敗不是結果未知(self) -> None:
        """確定失敗可以退回重做；結果未知不行。兩者不能共用一條路。"""
        終 = 下一步(查階段(階段代碼.測試), _結果(終局.確定失敗))
        assert isinstance(終, 結束)
        assert 終.代碼 is 結束代碼.中止
        assert "未知" not in 終.原因


def test_每個階段的下一步都指得到() -> None:
    """轉移表指向不存在的階段——這支會紅。"""
    代碼們 = {階段.代碼 for 階段 in TDD階段表}
    for 階段 in TDD階段表:
        for 去處 in (階段.綠, 階段.紅):
            if not isinstance(去處, 結束):
                assert 去處 in 代碼們, f"{階段.代碼} 指向不存在的階段 {去處}"


def test_查不到的階段要當場炸() -> None:
    with pytest.raises(KeyError, match="不存在"):
        查階段("不存在")  # type: ignore[arg-type]


def test_階段定義不可變() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        TDD階段表[0].代碼 = 階段代碼.審查  # type: ignore[misc]
    assert isinstance(TDD階段表[0], 階段定義)


def test_enum的值都是ASCII() -> None:
    """識別字中文、值 ASCII——值要跨程序流動（journal、CLI 輸出）。"""
    for 群 in (階段代碼, 種類, 結束代碼):
        for 成員 in 群:
            assert 成員.value.isascii(), f"{成員!r} 的值不是 ASCII"

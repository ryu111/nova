"""工作流的控制流程：純函式轉移，零 LLM、零子程序。

寫成**表**不是 `if` 鏈的理由有三個：印得出來（可以直接進 journal）、
測得動（就是這支測試）、加階段只要加一列（開放封閉）。
"""

import dataclasses

import pytest

from nova.契約.工作流 import 審查判定, 步驟結果, 種類, 結束, 結束代碼, 階段代碼, 階段定義
from nova.契約.模型回應 import 終局
from nova.迴圈.狀態機 import TDD階段表, 下一步, 卡住了, 卡住門檻, 查階段


def _結果(
    終: 終局 = 終局.成功,
    *,
    判準綠: bool | None = None,
    審查結論: 審查判定 | None = None,
) -> 步驟結果:
    return 步驟結果(階段=階段代碼.測試, 終局=終, 判準綠=判準綠, 證據="", 審查結論=審查結論)


class TestTDD順序:
    def test_七個階段的順序(self) -> None:
        """規則明文：先寫會紅的測試 → 跑它親眼看到它紅 → 最少的碼讓它綠 → 全綠下重構。"""
        assert [階段.代碼 for 階段 in TDD階段表] == [
            階段代碼.測試,
            階段代碼.驗證紅,
            階段代碼.實作,
            階段代碼.驗證綠,
            階段代碼.重構,
            階段代碼.驗證重構,
            階段代碼.審查,
        ]

    def test_階段表涵蓋所有階段代碼(self) -> None:
        """加了 enum 成員卻沒進表——這支會紅。"""
        assert {階段.代碼 for 階段 in TDD階段表} == set(階段代碼)

    def test_驗證是機械的不是模型(self) -> None:
        """驗收權不在執行者手上——硬規則 4 禁止自寫自評。"""
        判準的 = {階段.代碼 for 階段 in TDD階段表 if 階段.種類 is 種類.判準}
        assert 判準的 == {階段代碼.驗證紅, 階段代碼.驗證綠, 階段代碼.驗證重構}

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
        assert 終.代碼 is 結束代碼.護欄
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


class Test沒進展就要停:
    """「重複相同失敗方法而無策略改變」是 loop 的第一號反模式。

    nova 的兩條回頭邊（驗證紅沒紅退回測試、驗證綠沒綠退回實作）本來就可能
    來回不停，現在唯一擋它的是**步數上限**——那是「燒完 20 步才停」，
    不是「發現沒進展就停」。中間那 18 步全是白花的錢。

    **只看判準階段。** 模型階段的證據是自由文字，每次都不一樣，比對永遠不相等；
    判準階段的證據是 pytest 的輸出，是確定性的——**同一個判準吐出一模一樣的東西，
    就是真的什麼都沒變**。這是 OpenHands 那套 stuck detector 的同一個想法
    （deterministic equality，忽略會變動的 metadata），但只留對 nova 成立的那一半。

    為什麼不是「連續」而是「出現過」：中間夾著模型階段，本來就不連續。
    """

    def _判準步(self, 綠: bool, 證據: str) -> 步驟結果:
        return 步驟結果(階段=階段代碼.驗證紅, 終局=終局.成功, 判準綠=綠, 證據=證據)

    def test_同一個判準吐出同樣的紅N次就算卡住(self) -> None:
        軌跡 = tuple(self._判準步(綠=False, 證據="1 failed") for _ in range(卡住門檻))
        assert 卡住了(軌跡) is not None

    def test_差一次還不算(self) -> None:
        """門檻要真的是門檻，不是「出現兩次就慌」。"""
        軌跡 = tuple(self._判準步(綠=False, 證據="1 failed") for _ in range(卡住門檻 - 1))
        assert 卡住了(軌跡) is None

    def test_證據不一樣就不算卡住(self) -> None:
        """錯誤訊息在變 ＝ 有在動。**這才是「進展」的機械定義。**"""
        軌跡 = tuple(self._判準步(綠=False, 證據=f"{n} failed") for n in range(卡住門檻))
        assert 卡住了(軌跡) is None

    def test_綠的不算卡住(self) -> None:
        """同一個判準連綠三次是正常的（重跑確認），不是卡住。"""
        軌跡 = tuple(self._判準步(綠=True, 證據="all passed") for _ in range(卡住門檻 + 2))
        assert 卡住了(軌跡) is None

    def test_模型階段不看證據(self) -> None:
        """模型的自由文字本來就每次不同，拿它比對只會永遠不相等——

        更糟的是**萬一相等**（模型剛好回一樣的話），那也不代表沒進展。
        所以模型階段一律不算進來。
        """
        軌跡 = tuple(
            步驟結果(階段=階段代碼.測試, 終局=終局.成功, 判準綠=None, 證據="我寫好了")
            for _ in range(卡住門檻 + 3)
        )
        assert 卡住了(軌跡) is None

    def test_理由要說得出是哪一階和幾次(self) -> None:
        """「卡住了」不可行動。要能直接看出下一步該查哪裡。"""
        軌跡 = tuple(self._判準步(綠=False, 證據="1 failed") for _ in range(卡住門檻))
        理由 = 卡住了(軌跡)
        assert 理由 is not None
        assert 階段代碼.驗證紅.value in 理由
        assert str(卡住門檻) in 理由


class Test中止要分得出護欄還是壞掉:
    """`aborted` 把兩種完全相反的處境壓成同一個碼。

    外圈（`/goal` 驅動的修復迴圈、CI、任何腳本）看到 `中止` 之後要做的事相反：

    | 這一類 | 該做什麼 | 不准做什麼 |
    |---|---|---|
    | **護欄正常運作** | 改題目、改起點、由**人**決定要不要放寬 |
      **不准調高上限**——那是自己拆執法點 |
    | （預算用完、步數用完、卡住了、結果未知、重構改壞行為） | | |
    | **壞掉了**（角色確定失敗：認證、額度、接線） | 照硬規則 6 診斷：環境 → 回饋 → 流程 | — |

    不分開的話，一個半夜自動跑的修復迴圈會很合理地把 `--最多token` 調到五百萬，
    然後回報「修好了」。**那跟 `--no-verify` 是同一件事。**

    審查要求修改不在這張表裡：它走的是回頭邊（退回實作），不是中止。
    """

    def test_結果未知是護欄不是壞掉(self) -> None:
        步 = 步驟結果(階段=階段代碼.測試, 終局=終局.結果未知, 判準綠=None, 證據="")
        去處 = 下一步(查階段(階段代碼.測試), 步)
        assert isinstance(去處, 結束)
        assert 去處.代碼 is 結束代碼.護欄, "at-most-once 是護欄，不是壞掉"

    def test_角色確定失敗是壞掉(self) -> None:
        """**這支防的是分過頭。** 全部標成護欄的話，就沒有任何東西是「要修的」了。"""
        步 = 步驟結果(階段=階段代碼.測試, 終局=終局.確定失敗, 判準綠=None, 證據="")
        去處 = 下一步(查階段(階段代碼.測試), 步)
        assert isinstance(去處, 結束)
        assert 去處.代碼 is 結束代碼.中止

    def test_重構改壞行為是護欄(self) -> None:
        """SOP 明定不准往前除錯、要退回上一個綠燈——那是規矩生效，不是東西壞了。"""
        步 = 步驟結果(階段=階段代碼.驗證重構, 終局=終局.成功, 判準綠=False, 證據="1 failed")
        去處 = 下一步(查階段(階段代碼.驗證重構), 步)
        assert isinstance(去處, 結束)
        assert 去處.代碼 is 結束代碼.護欄

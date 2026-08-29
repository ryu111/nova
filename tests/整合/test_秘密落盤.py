"""祕密檔的落點與權限。**這兩件都是「出生前就擋」。**

碰硬碟、要真的 chmod，所以住整合層。解析那一半在 `tests/單元/test_秘密.py`。
"""

import os
import stat
from pathlib import Path

import pytest

from nova.載體.秘密 import 已載入的鍵環境變數, 權限太鬆, 看不懂的祕密檔, 祕密檔, 載入到


@pytest.fixture
def 專案(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    這個 = tmp_path / "某個專案"
    這個.mkdir()
    return 這個


def _種一份(專案: Path, 內容: str, *, 權限: int = 0o600) -> Path:
    路徑 = 祕密檔(專案)
    路徑.parent.mkdir(parents=True, exist_ok=True)
    路徑.write_text(內容, encoding="utf-8")
    路徑.chmod(權限)
    return 路徑


class Test住在專案外面:
    """**「屬於某個專案」跟「存在那個專案裡面」是兩件事。**

    存在裡面就等於交到執行者手上，而這個 repo 是 public——
    洩漏一次就是永久的，GitHub 的快取與別人的 clone 收不回來。
    """

    def test_落點不在專案底下(self, 專案: Path) -> None:
        路徑 = 祕密檔(專案)

        assert 專案 not in 路徑.parents, f"祕密檔落在專案裡面了：{路徑}"

    def test_兩個同名的專案不會混在一起(self, tmp_path: Path) -> None:
        """`~/a/nova` 與 `~/b/nova` 用同一份憑證的話，一個手滑就跨專案外洩。"""
        甲 = tmp_path / "甲" / "nova"
        乙 = tmp_path / "乙" / "nova"
        for 路 in (甲, 乙):
            路.mkdir(parents=True)

        assert 祕密檔(甲) != 祕密檔(乙)


class Test權限太鬆就不要出生:
    """`0644` 的祕密檔在多人機器上等於沒有祕密，**而它看起來完全正常**。

    沒有任何症狀，直到有一天有症狀。
    """

    @pytest.mark.parametrize("權限", [0o644, 0o604, 0o660, 0o666])
    def test_比0600鬆就拒絕(self, 專案: Path, 權限: int) -> None:
        路徑 = _種一份(專案, "A=x\n", 權限=權限)

        assert 權限太鬆(路徑) is not None, f"{權限:04o} 應該要被拒絕"

    @pytest.mark.parametrize("權限", [0o600, 0o400])
    def test_夠緊的放行(self, 專案: Path, 權限: int) -> None:
        """**這一組防的是擋過頭**——全部擋掉的話祕密檔一次都用不到。"""
        路徑 = _種一份(專案, "A=x\n", 權限=權限)

        assert 權限太鬆(路徑) is None, f"{權限:04o} 應該要放行"

    def test_太鬆的時候載入要炸不是靜默跳過(self, 專案: Path) -> None:
        """靜默跳過的話，使用者會拿到 401 而不是「你的祕密檔權限太鬆」。"""
        _種一份(專案, "A=x\n", 權限=0o644)
        環境: dict[str, str] = {}

        with pytest.raises(看不懂的祕密檔, match="0600"):
            載入到(環境, 專案=專案)

        assert 環境 == {}, "炸了卻還是塞了一半進去"

    def test_錯誤訊息要說得出怎麼修(self, 專案: Path) -> None:
        路徑 = _種一份(專案, "A=x\n", 權限=0o644)

        訊息 = 權限太鬆(路徑) or ""

        assert "chmod 600" in 訊息


class Test載入:
    def test_塞得進環境(self, 專案: Path) -> None:
        _種一份(專案, "MY_THING=abc123\n")
        環境: dict[str, str] = {}

        進去了 = 載入到(環境, 專案=專案)

        assert 環境["MY_THING"] == "abc123"
        assert 進去了 == ["MY_THING"]

    def test_沒有祕密檔是正常狀態(self, 專案: Path) -> None:
        """**預設關閉**：沒有祕密要載入不是使用者做錯什麼。"""
        環境: dict[str, str] = {}

        assert 載入到(環境, 專案=專案) == []
        assert 環境 == {}

    def test_不蓋掉已經存在的(self, 專案: Path) -> None:
        """使用者手動 export 的優先。

        反過來的話，「我明明 export 了為什麼沒用」會變成一個查不出來的問題。
        """
        _種一份(專案, "A=檔案裡的\n")
        環境 = {"A": "手動設的"}

        進去了 = 載入到(環境, 專案=專案)

        assert 環境["A"] == "手動設的"
        assert 進去了 == []

    def test_載入的鍵名要記進環境讓遮罩看得見(self, 專案: Path) -> None:
        """**這一條是不外洩那條線的第一段。**

        `遮罩` 靠鍵名的特徵猜哪些環境變數是祕密（KEY／TOKEN／SECRET…），
        猜不中 `MY_THING`。但 nova 自己載進去的東西**是不是祕密不必猜**。
        """
        _種一份(專案, "MY_THING=abc123\n")
        環境: dict[str, str] = {}

        載入到(環境, 專案=專案)

        assert 環境[已載入的鍵環境變數] == "MY_THING"

    def test_名單不會蓋掉上一次的(self, 專案: Path) -> None:
        _種一份(專案, "MY_THING=abc123\n")
        環境 = {已載入的鍵環境變數: "早就有的"}

        載入到(環境, 專案=專案)

        名單 = 環境[已載入的鍵環境變數].split(",")
        assert "早就有的" in 名單
        assert "MY_THING" in 名單

    def test_檔案的權限本身不會被改掉(self, 專案: Path) -> None:
        """載入是唯讀動作。**nova 不准去動使用者檔案的權限**——

        「幫你 chmod 好了」看起來貼心，但那是使用者系統上的狀態。
        """
        路徑 = _種一份(專案, "A=x\n", 權限=0o400)

        載入到({}, 專案=專案)

        assert stat.S_IMODE(路徑.stat().st_mode) == 0o400


def test_檔案不准被寫進版控(專案: Path) -> None:
    """落點在 `XDG_STATE_HOME` 底下，本來就不在任何 repo 裡——

    這一支是那個保證的斷言，不是那個保證本身。
    """
    路徑 = _種一份(專案, "A=x\n")

    assert str(路徑).startswith(os.environ["XDG_STATE_HOME"])

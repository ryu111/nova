"""已處理／：成果帳本的落點與讀取端。

**沒有讀取端就不准宣稱補了成果帳本**——只有寫端的話那是寫檔案給沒人看。
這條是 `docs/設計/04-載體要長什麼樣.md` 對 State 那一格的判準，成果帳本同理。

落點跟帳本同一條規則（見 `帳本.預設帳本目錄` 的表）：
**歸屬是索引問題，不是存放位置問題**——存在專案外面、用專案當鍵。
存在專案裡面就等於交到執行者手上。

會碰硬碟，所以住整合層不住單元層。
"""

from pathlib import Path

import pytest

from nova.契約.成果 import 成果
from nova.載體.已處理 import 列出成果, 已處理目錄, 歸檔
from nova.載體.帳本 import 預設帳本目錄


def _成果(識別碼: str, *, 收場: str = "完成", 退出碼: int = 0) -> 成果:
    return 成果(
        執行識別碼=識別碼,
        任務="隨便一件事",
        收場=收場,
        退出碼=退出碼,
        起="2026-08-30T09:15:00Z",
        迄="2026-08-30T09:31:00Z",
        走了幾階=5,
        總token=100,
    )


def test_歸檔之後讀得回來(tmp_path: Path) -> None:
    寫進去 = _成果("20260830T091500Z-aaa")

    歸檔(寫進去, 目錄=tmp_path)

    assert 列出成果(tmp_path) == [寫進去]


def test_檔名就是執行識別碼(tmp_path: Path) -> None:
    """這樣 `ls` 就是時序，而且對得回帳本的 `<執行識別碼>.jsonl`。"""
    歸檔(_成果("20260830T091500Z-aaa"), 目錄=tmp_path)

    assert [檔.name for 檔 in tmp_path.iterdir()] == ["20260830T091500Z-aaa.json"]


def test_最近的排前面(tmp_path: Path) -> None:
    """看帳的人要的是「剛剛那次怎麼了」，不是三個月前第一筆。"""
    for 識別 in ("20260828T000000Z-a", "20260830T000000Z-c", "20260829T000000Z-b"):
        歸檔(_成果(識別), 目錄=tmp_path)

    assert [筆.執行識別碼 for 筆 in 列出成果(tmp_path)] == [
        "20260830T000000Z-c",
        "20260829T000000Z-b",
        "20260828T000000Z-a",
    ]


def test_目錄還不存在時讀出來是空的不是炸掉(tmp_path: Path) -> None:
    """第一次跑 `nova 已處理` 的時候那個目錄本來就不存在。"""
    assert 列出成果(tmp_path / "還沒有") == []


def test_讀不動的那筆不准把整本帳帶走(tmp_path: Path) -> None:
    """一筆壞掉就整本看不了，那等於沒有帳本。

    **這是誠實欄位的反面**：跳過壞掉的那筆是對的，
    但不准連「有幾筆壞掉」都不知道——所以壞的那筆不算進結果，好的照樣讀得到。
    """
    歸檔(_成果("20260830T000000Z-good"), 目錄=tmp_path)
    (tmp_path / "20260829T000000Z-bad.json").write_text("{這不是 JSON", encoding="utf-8")

    回來 = 列出成果(tmp_path)

    assert [筆.執行識別碼 for 筆 in 回來] == ["20260830T000000Z-good"]


def test_上限擋得住(tmp_path: Path) -> None:
    for i in range(5):
        歸檔(_成果(f"2026083{i}T000000Z-x"), 目錄=tmp_path)

    assert len(列出成果(tmp_path, 上限=2)) == 2


class Test落點:
    """兩條軸：完整性（模型摸不摸得到）與歸屬（是誰的帳）。

    容易被改壞成單軸——只顧完整性就全域混在一起，只顧歸屬就寫進專案裡。
    """

    def test_落在專案外面(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """**會被人拿來當證據的東西，不准放在執行者摸得到的地方。**"""
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        專案 = tmp_path / "某個專案"
        專案.mkdir()

        assert 專案.resolve() not in 已處理目錄(專案).parents

    def test_不同專案分得開(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        甲 = tmp_path / "甲"
        乙 = tmp_path / "乙"
        for 專案 in (甲, 乙):
            專案.mkdir()

        assert 已處理目錄(甲) != 已處理目錄(乙)

    def test_落點看得出是哪個專案(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """純雜湊看不出是誰的帳，而**人查得動**正是帳本存在的理由。"""
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        專案 = tmp_path / "某個專案"
        專案.mkdir()

        assert "某個專案" in str(已處理目錄(專案))

    def test_跟帳本是同一個專案目錄下的兩個資料夾(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """成果帳本跟事件帳本是同一次執行的兩個面，走散了就對不回去。"""
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        專案 = tmp_path / "某個專案"
        專案.mkdir()

        assert 已處理目錄(專案).parent == 預設帳本目錄(專案).parent

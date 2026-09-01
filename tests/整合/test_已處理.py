"""已處理／：成果帳本的落點與讀取端。

**沒有讀取端就不准宣稱補了成果帳本**——只有寫端的話那是寫檔案給沒人看。
這條是 `docs/設計/04-載體要長什麼樣.md` 對 State 那一格的判準，成果帳本同理。

落點跟帳本同一條規則（見 `帳本.預設帳本目錄` 的表）：
**歸屬是索引問題，不是存放位置問題**——存在專案外面、用專案當鍵。
存在專案裡面就等於交到執行者手上。

會碰硬碟，所以住整合層不住單元層。
"""

import argparse
import json
from pathlib import Path

import pytest

from nova.契約.工作流 import 結束, 結束代碼
from nova.契約.成果 import 成果
from nova.契約.遮罩 import 已經遮過了
from nova.載體.命令列 import _歸檔成果, _這次執行, _題目
from nova.載體.已處理 import 列出成果, 已處理目錄, 歸檔
from nova.載體.帳本 import 預設帳本目錄
from nova.迴圈.工作流 import 工作流結果


def _成果(識別碼: str, *, 收場: str = "完成", 退出碼: int = 0) -> 成果:
    return 成果(
        執行識別碼=識別碼,
        任務=已經遮過了("隨便一件事", 因為="測試資料，裡面沒有祕密"),
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


class Test從摘要接到成果:
    """**這條接線最容易漏，而且漏了完全看不出來。**

    加總對了、顯示對了，但 `_歸檔成果` 忘了把成本傳下去的話，
    成果帳本上就是一片空白——而空白跟「這次沒人給成本」長得一模一樣。

    上一輪這一格是用「跑完就丟的臨時斷言」驗負控的，repo 裡沒有留下任何東西
    ——那等於沒有保證。見 docs/負控紀錄/0001-既有紀錄.md 的第六次。
    """

    def _跑一次歸檔(self, tmp_path: Path, 事件們: list[dict[str, object]]) -> 成果 | None:
        帳本目錄 = tmp_path / "帳本"
        帳本目錄.mkdir(parents=True)
        識別 = "20260830T120000Z-abc123"
        (帳本目錄 / f"{識別}.jsonl").write_text(
            "\n".join(json.dumps(事, ensure_ascii=False) for 事 in 事件們) + "\n",
            encoding="utf-8",
        )
        參數 = argparse.Namespace(帳本目錄=str(帳本目錄))
        _歸檔成果(
            參數,
            這次=_這次執行(識別=識別, 起點commit=None),
            題=_題目(描述="做一件事", 收件=None),
            果=工作流結果(結束=結束(結束代碼.完成, "做完了"), 軌跡=()),
            退出碼=0,
        )
        筆們 = 列出成果(tmp_path / "已處理")
        return 筆們[0] if 筆們 else None

    def _呼叫(self, 編號: int, 家: str, 成本: float | None) -> list[dict[str, object]]:
        收尾: dict[str, object] = {
            "run": "20260830T120000Z-abc123",
            "seq": 編號 * 2,
            "ts": f"t{編號 * 2}",
            "event": "call_finished",
            "call": 編號,
            "family": 家,
            "outcome": "success",
            "input_tokens": 100,
            "output_tokens": 10,
        }
        if 成本 is not None:
            收尾["cost_usd"] = 成本
        return [
            {
                "run": "20260830T120000Z-abc123",
                "seq": 編號 * 2 - 1,
                "ts": f"t{編號 * 2 - 1}",
                "event": "call_started",
                "call": 編號,
                "family": 家,
            },
            收尾,
        ]

    def test_事件帳本裡的成本會出現在成果上(self, tmp_path: Path) -> None:
        一筆 = self._跑一次歸檔(tmp_path, self._呼叫(1, "claude", 0.75))

        assert 一筆 is not None, "根本沒歸檔"
        assert 一筆.總成本美金 == 0.75

    def test_缺一家成本時成果上也是留白(self, tmp_path: Path) -> None:
        """**留白不准變成 0。** 0 看起來像免費，留白看起來像不知道——後者才是真的。"""
        一筆 = self._跑一次歸檔(
            tmp_path, [*self._呼叫(1, "claude", 0.75), *self._呼叫(2, "codex", None)]
        )

        assert 一筆 is not None
        assert 一筆.總成本美金 is None

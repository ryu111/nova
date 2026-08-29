"""跨執行的規則觸發率：從來不紅的規則是刪除候選。

這是**第一個「因為帳本裡的東西而做的決定」**的資料來源。
在此之前 nova 的 9 條規則一條都沒有觸發率資料——
「這條規則有沒有在守東西」只能憑印象。

Fowler 那份感測器歷史回答得了三個問題，這一層對應前兩個：
**哪些從來不紅**（不必要的訊號）、**哪些常紅**（該補指引的地方）。
第三個（趨勢）要時間軸，還沒做。
"""

import json
from pathlib import Path

import pytest

from nova.載體.命令列 import 主程式, 規則樣本下限
from nova.載體.帳本讀取 import 統計規則


def 寫執行(目錄: Path, 識別: str, 規則們: list[tuple[str, bool]]) -> None:
    目錄.mkdir(parents=True, exist_ok=True)
    行們 = []
    for 序, (代碼, 綠) in enumerate(規則們, start=1):
        共通 = {"run": 識別, "ts": "t", "call": 序, "rule": 代碼, "gate_point": "提交"}
        行們.append({**共通, "seq": 序 * 2 - 1, "event": "rule_started"})
        行們.append({**共通, "seq": 序 * 2, "event": "rule_finished", "gate_green": 綠})
    (目錄 / f"{識別}.jsonl").write_text(
        "".join(json.dumps(行, ensure_ascii=False) + "\n" for 行 in 行們), encoding="utf-8"
    )


def test_跨執行加總(tmp_path: Path) -> None:
    """一次執行看不出觸發率——每條規則一趟只跑一次。**要跨執行才有意義。**"""
    寫執行(tmp_path, "r1", [("lint", True), ("mypy", False)])
    寫執行(tmp_path, "r2", [("lint", True), ("mypy", True)])
    表 = {(條.規則, 條.閘點): 條 for 條 in 統計規則(tmp_path)}
    assert (表["lint", "提交"].跑過, 表["lint", "提交"].紅過) == (2, 0)
    assert (表["mypy", "提交"].跑過, 表["mypy", "提交"].紅過) == (2, 1)


def test_同一條規則不同閘點分開算(tmp_path: Path) -> None:
    """同一條規則在提交閘與 CI 的觸發率可以差很多——混在一起就看不出來。"""
    目錄 = tmp_path
    目錄.mkdir(parents=True, exist_ok=True)
    (目錄 / "r1.jsonl").write_text(
        "\n".join(
            json.dumps(行, ensure_ascii=False)
            for 行 in [
                {
                    "run": "r1",
                    "seq": 1,
                    "ts": "t",
                    "event": "rule_finished",
                    "call": 1,
                    "rule": "pytest",
                    "gate_point": "提交",
                    "gate_green": True,
                },
                {
                    "run": "r1",
                    "seq": 2,
                    "ts": "t",
                    "event": "rule_finished",
                    "call": 2,
                    "rule": "pytest",
                    "gate_point": "ci",
                    "gate_green": False,
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert len(統計規則(目錄)) == 2


def test_沒有帳本就是空的(tmp_path: Path) -> None:
    assert 統計規則(tmp_path / "沒這個目錄") == ()


def test_只算結束事件(tmp_path: Path) -> None:
    """開始事件不代表跑完了。兩邊都算會讓每條規則的次數變兩倍。"""
    寫執行(tmp_path, "r1", [("lint", True)])
    (條,) = 統計規則(tmp_path)
    assert 條.跑過 == 1


class TestCLI:
    def test_樣本夠了才敢說刪除候選(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """**從來不紅的規則是刪除候選**——報表要主動把它標出來。"""
        for 次 in range(規則樣本下限):
            寫執行(tmp_path, f"r{次}", [("lint", True), ("mypy", False)])
        assert 主程式(["帳本", "--規則", "--帳本目錄", str(tmp_path)]) == 0
        出 = capsys.readouterr().out
        assert "lint" in 出 and "mypy" in 出
        assert "從來沒紅（刪除候選）" in 出

    def test_樣本不夠不准說刪除候選(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """跑過兩次沒紅根本不是證據，而「刪除候選」是個很有份量的標籤。

        **沒有這個下限，報表第一天就會叫人去刪掉每一條規則**——
        實測第一次跑 `nova 帳本 --規則`，9 條規則全部被標成刪除候選。
        """
        寫執行(tmp_path, "r1", [("lint", True)])
        寫執行(tmp_path, "r2", [("lint", True)])
        主程式(["帳本", "--規則", "--帳本目錄", str(tmp_path)])
        出 = capsys.readouterr().out
        assert "不夠下結論" in 出
        assert "刪除候選" not in 出

    def test_沒有資料要講清楚(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert 主程式(["帳本", "--規則", "--帳本目錄", str(tmp_path)]) == 0
        assert "還沒有" in capsys.readouterr().out

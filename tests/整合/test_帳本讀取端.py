"""`nova 帳本`：把寫下去的東西真的讀回來給人看。

碰檔案，所以住整合層。收斂的邏輯在 `tests/單元/test_帳本讀取.py`。

**這一層才證明「有讀取端」**——純函式收斂得再對，沒有 CLI 就等於
寫檔案給沒人看。
"""

import json
from pathlib import Path

import pytest

from nova.載體.命令列 import 主程式
from nova.載體.帳本讀取 import 列出執行, 讀一次執行


def 寫一份(目錄: Path, 識別: str, 事件們: list[dict[str, object]]) -> Path:
    目錄.mkdir(parents=True, exist_ok=True)
    檔 = 目錄 / f"{識別}.jsonl"
    檔.write_text(
        "".join(json.dumps(事, ensure_ascii=False) + "\n" for 事 in 事件們), encoding="utf-8"
    )
    return 檔


一次成功 = [
    {"run": "r1", "seq": 1, "ts": "t1", "event": "call_started", "call": 1, "family": "agy"},
    {
        "run": "r1",
        "seq": 2,
        "ts": "t2",
        "event": "call_finished",
        "call": 1,
        "family": "agy",
        "outcome": "success",
        "input_tokens": 14523,
        "output_tokens": 935,
    },
]


def test_讀得回自己寫的檔(tmp_path: Path) -> None:
    果 = 讀一次執行(寫一份(tmp_path, "r1", 一次成功))
    assert 果.總token == 15458
    assert 果.各家[0].供應商 == "agy"


def test_列出執行是新的在前(tmp_path: Path) -> None:
    """檔名開頭是時戳，所以字典序倒過來就是時序。"""
    for 識別 in ("20260101T000000Z-aaa", "20260828T000000Z-bbb"):
        寫一份(tmp_path, 識別, 一次成功)
    assert [檔.stem for 檔 in 列出執行(tmp_path)] == [
        "20260828T000000Z-bbb",
        "20260101T000000Z-aaa",
    ]


def test_目錄不存在就是空的(tmp_path: Path) -> None:
    assert 列出執行(tmp_path / "沒有這個") == []


class TestCLI:
    def test_不給識別碼就列出最近的(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        寫一份(tmp_path, "r1", 一次成功)
        assert 主程式(["帳本", "--帳本目錄", str(tmp_path)]) == 0
        assert "r1" in capsys.readouterr().out

    def test_給識別碼就看那一次(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        寫一份(tmp_path, "r1", 一次成功)
        assert 主程式(["帳本", "r1", "--帳本目錄", str(tmp_path)]) == 0
        出 = capsys.readouterr().out
        assert "agy" in 出
        assert "15458" in 出

    def test_沒收尾的呼叫要吵(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """有開始沒結束＝可能已經做了一半。這件事不准安靜地過去。"""
        寫一份(tmp_path, "r1", [一次成功[0]])
        主程式(["帳本", "r1", "--帳本目錄", str(tmp_path)])
        assert "沒收尾" in capsys.readouterr().out

    def test_壞掉的行要吵(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """證據不完整不准長得跟「事情沒發生」一樣。"""
        檔 = 寫一份(tmp_path, "r1", 一次成功)
        檔.write_text(檔.read_text(encoding="utf-8") + "{半行\n", encoding="utf-8")
        主程式(["帳本", "r1", "--帳本目錄", str(tmp_path)])
        assert "讀不動" in capsys.readouterr().out

    def test_找不到那一次要當場說(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert 主程式(["帳本", "沒有這次", "--帳本目錄", str(tmp_path)]) != 0
        assert "找不到" in capsys.readouterr().err

    def test_一本都沒有也要講清楚(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """空輸出會讓人以為指令壞了。"""
        assert 主程式(["帳本", "--帳本目錄", str(tmp_path)]) == 0
        assert "沒有" in capsys.readouterr().out

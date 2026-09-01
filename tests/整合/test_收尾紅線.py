"""`nova 收` 的遠端副作用紅線。

這裡只讓暫存目錄裡的假 `git` 與假 `gh` 收到指令；任何測試都不碰真的遠端。
"""

import json
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from nova.契約.檢查結果 import 檢查結果
from nova.契約.退出碼 import 放行, 未知, 閘紅
from nova.載體.命令 import 收 as 命令列
from nova.載體.命令列 import 主程式


def _造假git與gh(專案: Path, 測具: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """在專案外造會記錄 argv 的假 `git` 與假 `gh`。"""
    專案.mkdir()
    執行檔目錄 = 測具 / "假執行檔"
    執行檔目錄.mkdir(parents=True)
    紀錄 = 測具 / "收尾指令.jsonl"
    # 30 秒遠超測試的 0.05 秒，是逾時保護失效時的保險絲。
    原文 = f"""#!{sys.executable}
import json
import os
import pathlib
import sys
import time
路徑 = pathlib.Path(os.environ['NOVA_收尾紀錄'])
with 路徑.open('a', encoding='utf-8') as 檔:
    資料 = {{'程式': pathlib.Path(sys.argv[0]).name, 'argv': sys.argv[1:]}}
    json.dump(資料, 檔, ensure_ascii=False)
    檔.write("\\n")
if pathlib.Path(sys.argv[0]).name == 'gh' and sys.argv[1:3] == ['pr', 'checks']:
    模式 = os.environ.get('NOVA_收尾CI', '')
    if 模式 == '紅':
        sys.exit(1)
    if 模式 == '逾時':
        time.sleep(30)
"""
    for 名稱 in ("git", "gh"):
        路徑 = 執行檔目錄 / 名稱
        路徑.write_text(原文, encoding="utf-8")
        路徑.chmod(路徑.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("NOVA_收尾紀錄", str(紀錄))
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join((str(執行檔目錄), os.environ.get("PATH", ""))),
    )
    return 紀錄


def _準備收尾(暫存根: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """建立專案與專案外的假 CLI 測具。"""
    專案 = 暫存根 / "專案"
    紀錄 = _造假git與gh(專案, 暫存根 / "測具", monkeypatch)
    return 專案, 紀錄


def _收尾參數(專案: Path) -> list[str]:
    """回傳所有收尾指令共用的 CLI 參數。"""
    return [
        "收",
        "--工作目錄",
        str(專案),
        "--不記帳",
        "--訊息",
        "測試收尾",
    ]


def _讀呼叫(紀錄: Path) -> list[tuple[str, list[str]]]:
    """把假 CLI 的 JSONL 紀錄還原成（程式名、argv）。"""
    if not 紀錄.exists():
        return []
    呼叫紀錄: list[tuple[str, list[str]]] = []
    for 行 in 紀錄.read_text(encoding="utf-8").splitlines():
        資料 = cast(dict[str, object], json.loads(行))
        參數 = [str(值) for 值 in cast(list[object], 資料["argv"])]
        呼叫紀錄.append((str(資料["程式"]), 參數))
    return 呼叫紀錄


def _斷言有指令(呼叫紀錄: list[tuple[str, list[str]]], 程式: str, *開頭: str) -> list[str]:
    """斷言有一個以指定參數開頭的假 CLI 呼叫，並回傳其 argv。"""
    for 名稱, 參數 in 呼叫紀錄:
        if 名稱 == 程式 and 參數[: len(開頭)] == list(開頭):
            return 參數
    訊息 = f"找不到 {程式} {' '.join(開頭)}：{呼叫紀錄}"
    raise AssertionError(訊息)


def _斷言沒有指令(呼叫紀錄: list[tuple[str, list[str]]], 程式: str, *開頭: str) -> None:
    """斷言沒有以指定參數開頭的假 CLI 呼叫。"""
    assert not any(名稱 == 程式 and 參數[: len(開頭)] == list(開頭) for 名稱, 參數 in 呼叫紀錄), (
        f"不應有 {程式} {' '.join(開頭)}：{呼叫紀錄}"
    )


def _檔案快照(專案: Path) -> dict[Path, bytes]:
    """取得專案目錄內所有檔案的內容快照。"""
    return {路徑.relative_to(專案): 路徑.read_bytes() for 路徑 in 專案.rglob("*") if 路徑.is_file()}


@pytest.fixture
def 閘放行(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """回傳把閘設成放行的設定函式。"""

    def 設定() -> None:
        monkeypatch.setattr(命令列, "_收尾閘", lambda *_: 放行)

    return 設定


class Test收尾紅線:
    def test_提交指令不准帶繞過驗證旗標(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        閘放行: Callable[[], None],
    ) -> None:
        """收尾組出的 commit 不得關掉 hooks。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        閘放行()

        assert 主程式(_收尾參數(專案)) == 放行

        提交 = _斷言有指令(_讀呼叫(紀錄), "git", "commit")
        assert "--no-verify" not in 提交

    def test_合併指令不准帶管理員旗標(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        閘放行: Callable[[], None],
    ) -> None:
        """收尾不得用管理員權限繞過 required checks。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        閘放行()

        assert 主程式(_收尾參數(專案)) == 放行

        合併 = _斷言有指令(_讀呼叫(紀錄), "gh", "pr", "merge")
        assert "--admin" not in 合併

    def test_合併指令一定帶刪除分支旗標(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        閘放行: Callable[[], None],
    ) -> None:
        """合併成功後必須把遠端分支一起收掉。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        閘放行()

        assert 主程式(_收尾參數(專案)) == 放行

        合併 = _斷言有指令(_讀呼叫(紀錄), "gh", "pr", "merge")
        assert "--delete-branch" in 合併

    def test_CI紅時不會組出合併指令(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        閘放行: Callable[[], None],
    ) -> None:
        """required CI 非零時只能回報紅，不能再組出 merge。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        monkeypatch.setenv("NOVA_收尾CI", "紅")
        閘放行()

        assert 主程式(_收尾參數(專案)) == 閘紅

        呼叫紀錄 = _讀呼叫(紀錄)
        _斷言有指令(呼叫紀錄, "gh", "pr", "checks")
        _斷言沒有指令(呼叫紀錄, "gh", "pr", "merge")

    def test_閘紅時後續提交推送開PR都不發生(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """閘是紅的時候，commit、push、開 PR 都不得啟動。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        monkeypatch.setattr(命令列, "_收尾閘", lambda *_: 閘紅)

        assert 主程式(_收尾參數(專案)) == 閘紅

        assert _讀呼叫(紀錄) == []

    def test_等不到CI回結果未知三(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        閘放行: Callable[[], None],
    ) -> None:
        """CI 等不到結果不是確定失敗，退出碼必須是 3 且不得合併。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        monkeypatch.setenv("NOVA_收尾CI", "逾時")
        閘放行()

        assert 主程式([*_收尾參數(專案), "--等CI秒", "0.05"]) == 未知

        呼叫紀錄 = _讀呼叫(紀錄)
        _斷言有指令(呼叫紀錄, "gh", "pr", "checks")
        _斷言沒有指令(呼叫紀錄, "gh", "pr", "merge")

    def test_閘紅時只跑閘不修改任何檔案(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """閘紅只回報，不得自行改檔把閘修綠。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        (專案 / "待修檔案.txt").write_text("閘紅時保留原樣\n", encoding="utf-8")
        原快照 = _檔案快照(專案)
        閘有跑 = False

        def 假閘(*_: object, **__: object) -> list[檢查結果]:
            nonlocal 閘有跑
            閘有跑 = True
            return [檢查結果("測試閘紅", "測試用紅閘", False, "測試", "故意讓閘紅")]

        monkeypatch.setattr(命令列, "跑閘", 假閘)

        assert 主程式(_收尾參數(專案)) == 閘紅
        assert 閘有跑
        assert _檔案快照(專案) == 原快照
        assert _讀呼叫(紀錄) == []

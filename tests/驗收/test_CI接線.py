"""CI 的接線本身也要有測試。

`test-count` 只要基準沒指到 base branch 就會整條空轉——而且是**全綠地**空轉。
這種「看起來有防護」的失敗沒有測試抓不到，所以直接把 CI 設定當成被驗收的對象。
"""

from pathlib import Path
from typing import Any

import yaml

from nova.載體.規則表 import 基準環境變數, 決定基準

CI設定 = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "gates.yml"


def _載入() -> dict[str, Any]:
    內容: dict[str, Any] = yaml.safe_load(CI設定.read_text(encoding="utf-8"))
    return 內容


def _閘步驟() -> dict[str, Any]:
    步驟們 = _載入()["jobs"]["gates"]["steps"]
    跑閘的 = [步驟 for 步驟 in 步驟們 if "nova 閘 ci" in 步驟.get("run", "")]
    assert len(跑閘的) == 1, "CI 應該只有一個地方呼叫 nova 閘（薄轉接、厚 nova）"
    步驟: dict[str, Any] = 跑閘的[0]
    return 步驟


def test_job名稱是gates() -> None:
    """`gates` 是 main 保護規則的 required check context，改名等於拆掉保護。"""
    assert "gates" in _載入()["jobs"]


def test_CI把測試數基準指到base_branch() -> None:
    基準 = _閘步驟().get("env", {}).get(基準環境變數, "")
    assert 基準.startswith("origin/"), (
        f"CI 必須把 {基準環境變數} 指到遠端 base branch。"
        f"留在預設的 HEAD 會讓 test-count 空轉——CI checkout 之後工作區就是 HEAD。實際值：{基準!r}"
    )


def test_CI有先把基準抓下來() -> None:
    """actions/checkout 預設只抓一層深度，不 fetch 的話基準 ref 根本不存在。"""
    全部指令 = "\n".join(步驟.get("run", "") for 步驟 in _載入()["jobs"]["gates"]["steps"])
    assert "git fetch" in 全部指令, "沒 fetch 就沒有 origin/main，規則會 fail-closed 紅在抓不到基準"


def test_沒設環境變數時退回HEAD() -> None:
    """本機 commit 前就是要跟 HEAD 比，不該逼開發者自己設環境變數。"""
    assert 決定基準({}) == "HEAD"


def test_環境變數會被採用() -> None:
    assert 決定基準({基準環境變數: "origin/主線"}) == "origin/主線"

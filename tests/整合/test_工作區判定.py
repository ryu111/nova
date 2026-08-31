"""工作區唯讀判定的整合測試。

會 fork 子程序或真跑 git/閘 的測試一律放在整合層。
"""

from pathlib import Path

import pytest

from nova.契約.工作流 import 任務, 工作區狀態, 步驟結果, 結束代碼, 階段代碼, 階段定義
from nova.契約.模型回應 import 終局
from nova.載體.工作區 import 判定工作區, 拍快照
from nova.載體.閘 import 規則, 靜態
from nova.迴圈.工作流 import 跑工作流


def test_工作區沒被動過時回傳沒被動過(tmp_path: Path) -> None:
    """工作區無變動時判定為沒被動過。"""
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    (工作區 / "檔案.txt").write_text("原內容", encoding="utf-8")
    快照 = 拍快照(工作區)
    任 = 任務(描述="沒動任何東西", 工作目錄=工作區)

    判定 = 判定工作區(任, 階段代碼.實作, 前快照=快照)

    assert 判定.狀態 is 工作區狀態.沒被動過
    assert 階段代碼.驗證綠 in 判定.未跑的階段


def test_工作區全綠時回傳綠並列出通過規則(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """工作區有變動且規則全過時回傳綠與通過名單。"""
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    (工作區 / "檔案.txt").write_text("新內容", encoding="utf-8")
    任 = 任務(描述="實作完成", 工作目錄=工作區)

    假規則表 = [
        規則(
            代碼="ruff-check",
            名稱="靜態檢查",
            閘點=frozenset({"ci"}),
            負責層="載體",
            檢查=lambda: (True, "ok"),
            階段=靜態,
        ),
        規則(
            代碼="pytest-unit",
            名稱="單元測試",
            閘點=frozenset({"ci"}),
            負責層="載體",
            檢查=lambda: (True, "ok"),
            階段=靜態,
        ),
    ]
    monkeypatch.setattr("nova.載體.工作區.建規則表", lambda _: 假規則表)

    判定 = 判定工作區(任, 階段代碼.實作, 前快照={"檔案.txt": "舊雜湊"})

    assert 判定.狀態 is 工作區狀態.綠
    assert 判定.綠的 == ("ruff-check", "pytest-unit")
    assert not 判定.紅的
    assert 判定.未跑的階段 == (階段代碼.驗證綠, 階段代碼.重構, 階段代碼.驗證重構, 階段代碼.審查)


def test_工作區有紅時指名哪幾支紅(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """工作區有檢查失敗時回傳紅並指名紅的規則代碼。"""
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    (工作區 / "檔案.txt").write_text("做了一半", encoding="utf-8")
    任 = 任務(描述="實作做到一半", 工作目錄=工作區)

    假規則表 = [
        規則(
            代碼="ruff-check",
            名稱="靜態檢查",
            閘點=frozenset({"ci"}),
            負責層="載體",
            檢查=lambda: (True, "ok"),
            階段=靜態,
        ),
        規則(
            代碼="pytest-unit",
            名稱="單元測試",
            閘點=frozenset({"ci"}),
            負責層="載體",
            檢查=lambda: (False, "1 failed"),
            階段=靜態,
        ),
    ]
    monkeypatch.setattr("nova.載體.工作區.建規則表", lambda _: 假規則表)

    判定 = 判定工作區(任, 階段代碼.實作, 前快照={"檔案.txt": "舊雜湊"})

    assert 判定.狀態 is 工作區狀態.紅
    assert 判定.綠的 == ("ruff-check",)
    assert 判定.紅的 == ("pytest-unit",)
    assert 階段代碼.驗證綠 in 判定.未跑的階段


def test_判定為綠也不准自動往下執行(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """即使判定查出工作區是綠的，工作流也不得擅自進入下一階段，退出碼仍為護欄。"""
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    任 = 任務(描述="逾時但工作區全綠", 工作目錄=工作區)
    執行階段: list[階段代碼] = []

    def 執行一步(定義: 階段定義, 任務參數: 任務, __: tuple[步驟結果, ...]) -> 步驟結果:
        (任務參數.工作目錄 / "檔.txt").write_text("寫入成果", encoding="utf-8")
        執行階段.append(定義.代碼)
        return 步驟結果(階段=定義.代碼, 終局=終局.結果未知, 判準綠=None, 證據="模型逾時")

    假規則表 = [
        規則(
            代碼="ci-all",
            名稱="全部檢查",
            閘點=frozenset({"ci"}),
            負責層="載體",
            檢查=lambda: (True, "all passed"),
            階段=靜態,
        ),
    ]
    monkeypatch.setattr("nova.載體.工作區.建規則表", lambda _: 假規則表)

    結果 = 跑工作流(
        任,
        執行一步=執行一步,
        起點=階段代碼.實作,
        拍快照=拍快照,
        判定工作區=判定工作區,
    )

    assert 結果.結束.代碼 is 結束代碼.護欄
    assert 執行階段 == [階段代碼.實作]
    assert len(結果.軌跡) == 1
    assert "工作區綠：ci-all" in 結果.結束.原因
    assert "尚未執行：驗證綠、重構、驗證重構、審查" in 結果.結束.原因

"""第一次動測試退回測試員前，測試檔要回到實作階段開始前。"""

import ast
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from nova.契約.工作流 import (
    任務,
    停止條件,
    審查判定,
    步驟結果,
    種類,
    結束代碼,
    階段代碼,
    階段定義,
)
from nova.契約.模型回應 import 終局
from nova.契約.護欄 import 護欄原因
from nova.載體.工作區 import 判定工作區, 拍工作區快照
from nova.載體.重構護欄 import 動到測試了嗎, 建立測試檔快照能力, 拍測試快照
from nova.迴圈.工作流 import 工作流結果, 跑工作流

測試檔 = "tests/test_既有.py"
基線內容 = "def test_既有() -> None:\n    assert 1 + 1 == 3\n"
實作員改後內容 = "def test_既有() -> None:\n    assert True  # 作弊改成恆綠\n"


def _建立基線repo(工作區: Path) -> None:
    (工作區 / "tests").mkdir(parents=True)
    (工作區 / 測試檔).write_text(基線內容, encoding="utf-8")
    for 指令 in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "測試@example.com"],
        ["git", "config", "user.name", "測試"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "實作前基線"],
    ):
        subprocess.run(指令, cwd=工作區, check=True, capture_output=True)


def test_實作員第一次動測試檔退回測試員前要還原到實作前快照(
    tmp_path: Path,
) -> None:
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    _建立基線repo(工作區)
    已伸手 = False

    def 執行一步(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
        nonlocal 已伸手
        del 軌跡
        if 定義.代碼 is 階段代碼.實作 and not 已伸手:
            已伸手 = True
            (任.工作目錄 / 測試檔).write_text(實作員改後內容, encoding="utf-8")
        if 定義.種類 is 種類.判準:
            return 步驟結果(
                階段=定義.代碼,
                終局=終局.成功,
                判準綠=定義.期望綠,
                證據="假判準",
            )
        return 步驟結果(
            階段=定義.代碼,
            終局=終局.成功,
            判準綠=None,
            證據="做好了",
            審查結論=審查判定.通過 if 定義.代碼 is 階段代碼.審查 else None,
        )

    果: 工作流結果 = 跑工作流(
        任務(描述="讓 X 變成 Y", 工作目錄=工作區),
        執行一步=執行一步,
        停止=停止條件(最多步數=4),
        拍快照=拍測試快照,
        動到測試了嗎=動到測試了嗎,
    )

    assert [步.階段 for 步 in 果.軌跡] == [
        階段代碼.測試,
        階段代碼.驗證紅,
        階段代碼.實作,
        階段代碼.測試,
    ], "第一次動測試要回到測試階，不能在實作階段直接收線"
    assert (工作區 / 測試檔).read_text(encoding="utf-8") == 基線內容, (
        "退回測試員前要把實作員對測試檔的改動還原到實作階段開始前"
    )


def test_正式接線下第一次動測試仍要還原並退回測試員(tmp_path: Path) -> None:
    """守住正式工作流接線下，第一次違規仍會還原測試檔並回到測試階。"""
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    _建立基線repo(工作區)
    能力 = 建立測試檔快照能力()
    已伸手 = False

    def 執行一步(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
        nonlocal 已伸手
        del 軌跡
        if 定義.代碼 is 階段代碼.實作 and not 已伸手:
            已伸手 = True
            (任.工作目錄 / 測試檔).write_text(實作員改後內容, encoding="utf-8")
        if 定義.種類 is 種類.判準:
            return 步驟結果(
                階段=定義.代碼,
                終局=終局.成功,
                判準綠=定義.期望綠,
                證據="假判準",
            )
        return 步驟結果(
            階段=定義.代碼,
            終局=終局.成功,
            判準綠=None,
            證據="做好了",
            審查結論=審查判定.通過 if 定義.代碼 is 階段代碼.審查 else None,
        )

    果: 工作流結果 = 跑工作流(
        任務(描述="讓 X 變成 Y", 工作目錄=工作區),
        執行一步=執行一步,
        停止=停止條件(最多步數=4),
        拍快照=拍工作區快照,
        動到測試了嗎=動到測試了嗎,
        測試檔快照能力=能力,
        判定工作區=判定工作區,
    )

    assert [步.階段 for 步 in 果.軌跡] == [
        階段代碼.測試,
        階段代碼.驗證紅,
        階段代碼.實作,
        階段代碼.測試,
    ], "正式接線下第一次動測試要回到測試階，不能直接收護欄"
    assert (工作區 / 測試檔).read_text(encoding="utf-8") == 基線內容, (
        "正式接線下退回測試員前要還原到實作階段開始前的測試內容"
    )


def test_實作員第一次動同一支測試要保留測試階段的改動(tmp_path: Path) -> None:
    """還原要回到實作階段開始前，不能退回派工樹的起點 commit。"""
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    _建立基線repo(工作區)
    實作階段開始前內容 = 基線內容 + "\ndef test_測試員這輪新增() -> None:\n    assert 2 + 2 == 5\n"
    (工作區 / 測試檔).write_text(實作階段開始前內容, encoding="utf-8")
    已伸手 = False

    def 執行一步(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
        nonlocal 已伸手
        del 軌跡
        if 定義.代碼 is 階段代碼.實作 and not 已伸手:
            已伸手 = True
            (任.工作目錄 / 測試檔).write_text(實作員改後內容, encoding="utf-8")
        if 定義.種類 is 種類.判準:
            return 步驟結果(
                階段=定義.代碼,
                終局=終局.成功,
                判準綠=定義.期望綠,
                證據="假判準",
            )
        return 步驟結果(
            階段=定義.代碼,
            終局=終局.成功,
            判準綠=None,
            證據="做好了",
            審查結論=審查判定.通過 if 定義.代碼 is 階段代碼.審查 else None,
        )

    果: 工作流結果 = 跑工作流(
        任務(描述="讓 X 變成 Y", 工作目錄=工作區),
        執行一步=執行一步,
        停止=停止條件(最多步數=4),
        拍快照=拍測試快照,
        動到測試了嗎=動到測試了嗎,
    )

    assert [步.階段 for 步 in 果.軌跡] == [
        階段代碼.測試,
        階段代碼.驗證紅,
        階段代碼.實作,
        階段代碼.測試,
    ], "第一次動同一支測試也要回測試階，不能因還原到起點失敗而收護欄"
    assert (工作區 / 測試檔).read_text(encoding="utf-8") == 實作階段開始前內容, (
        "還原實作員改動時要保留測試員在實作階段開始前留下的內容"
    )


def test_第一次動測試不能因工作目錄沒有git就略過快照還原(tmp_path: Path) -> None:
    """工作流只依賴注入的快照能力時，也不能把未還原的作弊內容帶回測試員。"""
    工作區 = tmp_path / "工作區"
    (工作區 / "tests").mkdir(parents=True)
    (工作區 / 測試檔).write_text(基線內容, encoding="utf-8")
    已伸手 = False

    def 執行一步(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
        nonlocal 已伸手
        del 軌跡
        if 定義.代碼 is 階段代碼.實作 and not 已伸手:
            已伸手 = True
            (任.工作目錄 / 測試檔).write_text(實作員改後內容, encoding="utf-8")
        if 定義.種類 is 種類.判準:
            return 步驟結果(
                階段=定義.代碼,
                終局=終局.成功,
                判準綠=定義.期望綠,
                證據="假判準",
            )
        return 步驟結果(
            階段=定義.代碼,
            終局=終局.成功,
            判準綠=None,
            證據="做好了",
            審查結論=審查判定.通過 if 定義.代碼 is 階段代碼.審查 else None,
        )

    果: 工作流結果 = 跑工作流(
        任務(描述="讓 X 變成 Y", 工作目錄=工作區),
        執行一步=執行一步,
        停止=停止條件(最多步數=4),
        拍快照=拍測試快照,
        動到測試了嗎=動到測試了嗎,
    )

    assert [步.階段 for 步 in 果.軌跡] == [
        階段代碼.測試,
        階段代碼.驗證紅,
        階段代碼.實作,
        階段代碼.測試,
    ]
    assert (工作區 / 測試檔).read_text(encoding="utf-8") == 基線內容, (
        "快照能力已接上時，不能因工作目錄沒有 .git 就把實作員的作弊內容留下"
    )


def test_第一次動測試的還原不該讀取非測試檔(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """測試護欄只需備份 `tests/`；工作區其他檔不應被還原器讀進記憶體。"""
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    _建立基線repo(工作區)
    非測試檔 = "src/不該被還原器讀取.py"
    (工作區 / "src").mkdir()
    (工作區 / 非測試檔).write_text("實作內容", encoding="utf-8")

    快照次數 = 0
    已拍實作前快照 = False
    讀到非測試檔 = False
    原本讀檔 = Path.read_bytes

    def 拍快照(根目錄: Path) -> Mapping[str, str]:
        nonlocal 快照次數, 已拍實作前快照
        快照次數 += 1
        if 快照次數 == 3:  # 測試階段前後各一次，第三次是實作階段開始前
            已拍實作前快照 = True
        return {
            測試檔: (根目錄 / 測試檔).read_text(encoding="utf-8"),
            非測試檔: "非測試檔雜湊",
        }

    def 記錄讀檔(路徑: Path) -> bytes:
        nonlocal 讀到非測試檔
        if 已拍實作前快照 and 路徑 == 工作區 / 非測試檔:
            讀到非測試檔 = True
        return 原本讀檔(路徑)

    monkeypatch.setattr(Path, "read_bytes", 記錄讀檔)
    已執行實作 = False

    def 執行一步(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
        nonlocal 已執行實作
        del 軌跡
        if 定義.代碼 is 階段代碼.實作:
            已執行實作 = True
            (任.工作目錄 / 測試檔).write_text(實作員改後內容, encoding="utf-8")
        if 定義.種類 is 種類.判準:
            return 步驟結果(
                階段=定義.代碼,
                終局=終局.成功,
                判準綠=定義.期望綠,
                證據="假判準",
            )
        return 步驟結果(
            階段=定義.代碼,
            終局=終局.成功,
            判準綠=None,
            證據="做好了",
            審查結論=審查判定.通過 if 定義.代碼 is 階段代碼.審查 else None,
        )

    果: 工作流結果 = 跑工作流(
        任務(描述="讓 X 變成 Y", 工作目錄=工作區),
        執行一步=執行一步,
        停止=停止條件(最多步數=4),
        拍快照=拍快照,
        動到測試了嗎=lambda 前, 後: tuple(
            sorted(
                檔
                for 檔 in set(前) | set(後)
                if 檔.startswith("tests/") and 前.get(檔) != 後.get(檔)
            )
        ),
    )

    assert 已執行實作
    assert [步.階段 for 步 in 果.軌跡] == [
        階段代碼.測試,
        階段代碼.驗證紅,
        階段代碼.實作,
        階段代碼.測試,
    ]
    assert not 讀到非測試檔, "備份測試檔時不該把工作區其他檔案讀進來"
    assert (工作區 / 測試檔).read_text(encoding="utf-8") == 基線內容, (
        "第一次違規退回測試員前仍要還原測試檔"
    )


def test_第一次動測試要刪掉實作員新增的測試檔(tmp_path: Path) -> None:
    """守住第一次違規退回測試員前，實作員新增的測試檔必須被刪掉。"""
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    _建立基線repo(工作區)
    新增測試檔 = "tests/test_實作員新增.py"
    已執行實作 = False

    def 執行一步(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
        nonlocal 已執行實作
        del 軌跡
        if 定義.代碼 is 階段代碼.實作 and not 已執行實作:
            已執行實作 = True
            (任.工作目錄 / 新增測試檔).write_text("assert True\n", encoding="utf-8")
        if 定義.種類 is 種類.判準:
            return 步驟結果(
                階段=定義.代碼,
                終局=終局.成功,
                判準綠=定義.期望綠,
                證據="假判準",
            )
        return 步驟結果(
            階段=定義.代碼,
            終局=終局.成功,
            判準綠=None,
            證據="做好了",
            審查結論=審查判定.通過 if 定義.代碼 is 階段代碼.審查 else None,
        )

    果: 工作流結果 = 跑工作流(
        任務(描述="讓 X 變成 Y", 工作目錄=工作區),
        執行一步=執行一步,
        停止=停止條件(最多步數=4),
        拍快照=拍測試快照,
        動到測試了嗎=動到測試了嗎,
    )

    assert [步.階段 for 步 in 果.軌跡] == [
        階段代碼.測試,
        階段代碼.驗證紅,
        階段代碼.實作,
        階段代碼.測試,
    ]
    assert not (工作區 / 新增測試檔).exists(), "實作員新增的測試檔要在退回測試員前刪掉"


def test_第一次動測試還原失敗要收護欄(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """守住測試檔還原失敗時，工作流必須收護欄而不帶著未還原改動前進。"""
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    _建立基線repo(工作區)
    已執行實作 = False
    原本寫入 = Path.write_bytes
    錯誤訊息 = "刻意讓測試檔還原失敗"

    def 讓還原失敗(路徑: Path, 內容: bytes) -> int:
        if 路徑 == 工作區 / 測試檔:
            raise OSError(錯誤訊息)
        return 原本寫入(路徑, 內容)

    monkeypatch.setattr(Path, "write_bytes", 讓還原失敗)

    def 執行一步(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
        nonlocal 已執行實作
        del 軌跡
        if 定義.代碼 is 階段代碼.實作 and not 已執行實作:
            已執行實作 = True
            (任.工作目錄 / 測試檔).write_text(實作員改後內容, encoding="utf-8")
        if 定義.種類 is 種類.判準:
            return 步驟結果(
                階段=定義.代碼,
                終局=終局.成功,
                判準綠=定義.期望綠,
                證據="假判準",
            )
        return 步驟結果(
            階段=定義.代碼,
            終局=終局.成功,
            判準綠=None,
            證據="做好了",
            審查結論=審查判定.通過 if 定義.代碼 is 階段代碼.審查 else None,
        )

    果: 工作流結果 = 跑工作流(
        任務(描述="讓 X 變成 Y", 工作目錄=工作區),
        執行一步=執行一步,
        停止=停止條件(最多步數=4),
        拍快照=拍測試快照,
        動到測試了嗎=動到測試了嗎,
    )

    assert 果.結束.代碼 is 結束代碼.護欄
    assert 果.結束.護欄原因 is 護欄原因.動了測試
    assert "還原失敗" in 果.結束.原因
    assert (工作區 / 測試檔).read_text(encoding="utf-8") == 實作員改後內容

    工作流原始碼 = ast.parse(
        (Path(__file__).parents[2] / "src/nova/迴圈/工作流.py").read_text(encoding="utf-8")
    )
    迴圈直接碰檔案的呼叫 = {
        節點.func.attr
        for 節點 in ast.walk(工作流原始碼)
        if isinstance(節點, ast.Call) and isinstance(節點.func, ast.Attribute)
    }
    assert not {"read_bytes", "write_bytes", "unlink"} & 迴圈直接碰檔案的呼叫, (
        "測試檔快照、還原與刪除新增檔要由載體能力承接，迴圈不該直接碰檔案"
    )


def test_結果未知時第一次動測試仍要還原到實作前快照(tmp_path: Path) -> None:
    """守住結果未知收場也不能把實作員改過的測試檔留在工作區。"""
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    _建立基線repo(工作區)
    能力 = 建立測試檔快照能力()
    已執行實作 = False

    def 執行一步(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
        nonlocal 已執行實作
        del 軌跡
        if 定義.代碼 is 階段代碼.測試:
            return 步驟結果(
                階段=定義.代碼,
                終局=終局.成功,
                判準綠=None,
                證據="測試完成",
            )
        if 定義.代碼 is 階段代碼.驗證紅:
            return 步驟結果(
                階段=定義.代碼,
                終局=終局.成功,
                判準綠=False,
                證據="假判準紅",
            )
        if 定義.代碼 is 階段代碼.實作:
            if not 已執行實作:
                已執行實作 = True
                (任.工作目錄 / 測試檔).write_text(實作員改後內容, encoding="utf-8")
            return 步驟結果(
                階段=定義.代碼,
                終局=終局.結果未知,
                判準綠=None,
                證據="實作結果未知",
            )
        return 步驟結果(
            階段=定義.代碼,
            終局=終局.成功,
            判準綠=None,
            證據="做好了",
            審查結論=審查判定.通過 if 定義.代碼 is 階段代碼.審查 else None,
        )

    果: 工作流結果 = 跑工作流(
        任務(描述="讓 X 變成 Y", 工作目錄=工作區),
        執行一步=執行一步,
        停止=停止條件(最多步數=4),
        動到測試了嗎=動到測試了嗎,
        測試檔快照能力=能力,
    )

    assert 果.結束.代碼 is 結束代碼.護欄
    assert (工作區 / 測試檔).read_text(encoding="utf-8") == 基線內容

"""轉接器的全鏈路：真的 fork 子程序，但子程序是假 CLI，不燒 token。

假 CLI 讀環境變數決定要吐哪一份實錄、用哪個結束碼，所以連
「工作目錄有沒有傳下去」「逾時會不會殺掉」都測得到——這是純函式測不到的那一段。
"""

import os
import stat
from pathlib import Path

import pytest

from nova.載體.模型.執行 import 跑cli
from nova.載體.模型.轉接 import 建立, 找執行檔

實錄 = Path(__file__).resolve().parents[1] / "整合" / "實錄"

假CLI內容 = """#!/usr/bin/env python3
import os, sys, time, pathlib
if os.environ.get("假CLI_睡"):
    time.sleep(float(os.environ["假CLI_睡"]))
if os.environ.get("假CLI_印工作目錄"):
    print(pathlib.Path.cwd()); sys.exit(0)
sys.stdout.write(pathlib.Path(os.environ["假CLI_實錄"]).read_text(encoding="utf-8"))
sys.exit(int(os.environ.get("假CLI_結束碼", "0")))
"""


@pytest.fixture
def 假CLI(tmp_path: Path) -> Path:
    路徑 = tmp_path / "假cli"
    路徑.write_text(假CLI內容, encoding="utf-8")
    路徑.chmod(路徑.stat().st_mode | stat.S_IEXEC)
    return 路徑


def _環境(實錄檔: str, 結束碼: int = 0, **其他: str) -> dict[str, str]:
    return {"假CLI_實錄": str(實錄 / 實錄檔), "假CLI_結束碼": str(結束碼), **其他}


class Test全鏈路:
    def test_成功(self, 假CLI: Path) -> None:
        答 = 建立("claude", 執行檔=假CLI).詢問("在嗎", 環境=_環境("claude_ok.json"))
        assert 答.終局 == "success"
        assert 答.文字 == "ok"

    def test_失敗被分類(self, 假CLI: Path) -> None:
        答 = 建立("codex", 執行檔=假CLI).詢問("在嗎", 環境=_環境("codex_bad.txt", 1))
        assert 答.終局 != "success"
        assert 答.失敗代碼 == "model-not-found"
        assert 答.原始結束碼 == 1

    def test_工作目錄真的傳下去(self, 假CLI: Path, tmp_path: Path) -> None:
        別處 = tmp_path / "別處"
        別處.mkdir()
        答 = 建立("agy", 執行檔=假CLI).詢問("在嗎", 工作目錄=別處, 環境={"假CLI_印工作目錄": "1"})
        assert 答.失敗代碼 == "unknown", "假 CLI 印的是路徑不是 envelope，本來就該解不動"

    def test_逾時會被殺掉並標成timeout(self, 假CLI: Path) -> None:
        答 = 建立("claude", 執行檔=假CLI).詢問(
            "在嗎", 逾時秒=0.3, 環境=_環境("claude_ok.json", 0, 假CLI_睡="5")
        )
        assert 答.終局 != "success"
        assert 答.失敗代碼 == "timeout"

    def test_執行檔不存在要當場炸(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            建立("claude", 執行檔=tmp_path / "根本沒有").詢問("在嗎")


class Test把各家載體關到最小:
    """「換腦但行為一樣」的測試背書。

    這幾條旗標若被拿掉，nova 的行為就會變成「這次剛好用了哪一家的行為」。
    設計理由見 docs/設計/02-統一LLM介面.md「基準形狀是本地模型」。
    """

    def test_claude關掉工具與家目錄設定(self) -> None:
        參數 = 建立("claude", 執行檔=Path("/x")).組參數("提示", None)
        assert 參數[參數.index("--tools") : 參數.index("--tools") + 2] == ["--tools", ""], (
            "--tools '' 才會關掉全部內建工具（claude --help 原文：Use \"\" to disable all tools）"
        )
        assert "--bare" in 參數, "--bare 才會跳過 hooks、auto-memory 與 CLAUDE.md 自動探索"
        assert 參數[參數.index("--system-prompt") : 參數.index("--system-prompt") + 2] == [
            "--system-prompt",
            "",
        ]

    def test_codex唯讀且不讀使用者設定(self) -> None:
        參數 = 建立("codex", 執行檔=Path("/x")).組參數("提示", None)
        assert 參數[0] == "exec", "codex 的非互動是子指令不是旗標"
        for 要有 in ("--sandbox", "read-only", "--ignore-user-config", "--ephemeral", "--json"):
            assert 要有 in 參數, f"少了 {要有}"

    def test_agy用plan模式(self) -> None:
        參數 = 建立("agy", 執行檔=Path("/x")).組參數("提示", None)
        assert 參數[參數.index("--mode") : 參數.index("--mode") + 2] == ["--mode", "plan"]

    def test_提示一律併進參數不靠stdin(self) -> None:
        """agy 1.1.22 實測不讀 stdin，所以三家一律走參數——最小公倍數。"""
        for 家 in ("claude", "codex", "agy"):
            assert "我的提示" in 建立(家, 執行檔=Path("/x")).組參數("我的提示", None)

    def test_模型是漏出的不翻譯(self) -> None:
        參數 = 建立("codex", 執行檔=Path("/x")).組參數("提示", "gpt-5-codex")
        assert "gpt-5-codex" in 參數, "模型字串原樣傳下去，各家命名空間不交集，翻譯只會翻錯"


class Test不信PATH:
    def test_優先用候選目錄(self, tmp_path: Path) -> None:
        (tmp_path / "codex").write_text("", encoding="utf-8")
        assert 找執行檔("codex", 候選目錄=(tmp_path,)) == tmp_path / "codex"

    def test_候選目錄都沒有就報錯不要靜默走PATH(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="codex"):
            找執行檔("codex", 候選目錄=(tmp_path,), 查PATH=lambda _: None)


def test_假CLI真的印出工作目錄(假CLI: Path, tmp_path: Path) -> None:
    """把上面那支測試沒斷言到的部分補起來：cwd 真的是我們指定的那個。"""
    別處 = tmp_path / "另一個"
    別處.mkdir()
    結果 = 跑cli(假CLI, [], 工作目錄=別處, 環境={"假CLI_印工作目錄": "1", **os.environ})
    assert 結果.標準輸出.strip() == str(別處.resolve())

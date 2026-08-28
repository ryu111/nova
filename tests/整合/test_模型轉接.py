"""轉接器的全鏈路：真的 fork 子程序，但子程序是假 CLI，不燒 token。

假 CLI 讀環境變數決定要吐哪一份實錄、用哪個結束碼，所以連
「工作目錄有沒有傳下去」「逾時會不會殺掉」都測得到——這是純函式測不到的那一段。
"""

import os
import stat
import tomllib
from pathlib import Path

import pytest

from nova.契約.角色 import 呼叫選項, 權限
from nova.載體.模型.執行 import 跑cli
from nova.載體.模型.轉接 import (
    agy預設模型,
    codex常用模型,
    codex推理強度,
    codex高階模型,
    家族,
    建立,
    找執行檔,
)

實錄 = Path(__file__).resolve().parents[1] / "整合" / "實錄"

假CLI內容 = """#!/usr/bin/env python3
import os, sys, time, pathlib
if os.environ.get("假CLI_睡"):
    time.sleep(float(os.environ["假CLI_睡"]))
if os.environ.get("假CLI_只吐stderr"):
    sys.stderr.write(os.environ["假CLI_只吐stderr"])
    sys.exit(int(os.environ.get("假CLI_結束碼", "2")))
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
        答 = 建立("agy", 執行檔=假CLI).詢問(
            "在嗎", 選項=呼叫選項(工作目錄=別處), 環境={"假CLI_印工作目錄": "1"}
        )
        assert 答.失敗代碼 == "unknown", "假 CLI 印的是路徑不是 envelope，本來就該解不動"

    def test_逾時會被殺掉並標成timeout(self, 假CLI: Path) -> None:
        答 = 建立("claude", 執行檔=假CLI).詢問(
            "在嗎", 選項=呼叫選項(逾時秒=0.3), 環境=_環境("claude_ok.json", 0, 假CLI_睡="5")
        )
        assert 答.終局 != "success"
        assert 答.失敗代碼 == "timeout"

    def test_失敗又沒話說時要把stderr當證據(self, 假CLI: Path) -> None:
        """診斷丟掉比結論丟掉更難查——它看起來完全正常。

        真實案例：codex 的 `--sandbox` 與 `--approve-for-me` 互斥，exit 2，
        stdout 全空、錯誤訊息全在 stderr。不補的話使用者只看得到
        「確定失敗 usage」，看不到是哪個旗標錯了。
        """
        答 = 建立("codex", 執行檔=假CLI).詢問(
            "在嗎", 環境={"假CLI_只吐stderr": "error: 旗標互斥\n", "假CLI_結束碼": "2"}
        )
        assert 答.失敗代碼 == "usage"
        assert "旗標互斥" in 答.文字, "stderr 沒被當成證據，使用者查不到真因"

    def test_成功時不會把stderr混進文字(self, 假CLI: Path) -> None:
        """stderr 只在「失敗又沒話說」時才補——不然會汙染模型真正說的話。"""
        答 = 建立("claude", 執行檔=假CLI).詢問("在嗎", 環境=_環境("claude_ok.json"))
        assert 答.文字 == "ok"

    def test_執行檔不存在要當場炸(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            建立("claude", 執行檔=tmp_path / "根本沒有").詢問("在嗎")


class Test把各家載體關到最小:
    """「換腦但行為一樣」的測試背書。

    這幾條旗標若被拿掉，nova 的行為就會變成「這次剛好用了哪一家的行為」。
    設計理由見 docs/設計/02-統一LLM介面.md「基準形狀是本地模型」。
    """

    def test_claude關掉工具與家目錄設定(self) -> None:
        參數 = 建立("claude", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        assert 參數[參數.index("--tools") : 參數.index("--tools") + 2] == ["--tools", ""], (
            "--tools '' 才會關掉全部內建工具（claude --help 原文：Use \"\" to disable all tools）"
        )
        assert "--bare" in 參數, "--bare 才會跳過 hooks、auto-memory 與 CLAUDE.md 自動探索"
        assert 參數[參數.index("--system-prompt") : 參數.index("--system-prompt") + 2] == [
            "--system-prompt",
            "",
        ]

    def test_codex唯讀且不讀使用者設定(self) -> None:
        參數 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        assert 參數[0] == "exec", "codex 的非互動是子指令不是旗標"
        for 要有 in ("--sandbox", "read-only", "--ignore-user-config", "--ephemeral", "--json"):
            assert 要有 in 參數, f"少了 {要有}"

    def test_agy用plan模式(self) -> None:
        參數 = 建立("agy", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        assert 參數[參數.index("--mode") : 參數.index("--mode") + 2] == ["--mode", "plan"]

    def test_提示一律併進參數不靠stdin(self) -> None:
        """agy 1.1.22 實測不讀 stdin，所以三家一律走參數——最小公倍數。"""
        for 家 in ("claude", "codex", "agy"):
            assert "我的提示" in 建立(家, 執行檔=Path("/x")).組參數("我的提示", 呼叫選項())

    def test_模型是漏出的不翻譯(self) -> None:
        參數 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項(模型="gpt-5-codex"))
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


class Test權限是漏出的:
    """權限不由介面決定——藏起來就是幫使用者做風險決策。預設一律最嚴那邊。"""

    def test_預設是唯讀(self) -> None:
        """忘了設不會變成放行。"""
        assert 呼叫選項().權限 is 權限.唯讀

    def test_claude可編輯時才給工具(self) -> None:
        唯讀 = 建立("claude", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        可寫 = 建立("claude", 執行檔=Path("/x")).組參數("提示", 呼叫選項(權限=權限.可編輯))
        assert 唯讀[唯讀.index("--tools") : 唯讀.index("--tools") + 2] == ["--tools", ""]
        assert "Write" in 可寫[可寫.index("--tools") + 1]
        assert 可寫[可寫.index("--permission-mode") : 可寫.index("--permission-mode") + 2] == [
            "--permission-mode",
            "acceptEdits",
        ]
        assert "--permission-mode" not in 唯讀, "唯讀模式不該帶權限模式旗標"

    def test_codex可編輯時不給sandbox(self) -> None:
        """實測：`--sandbox` 與 `--approve-for-me` 互斥，一起給會 exit 2。"""
        唯讀 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        可寫 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項(權限=權限.可編輯))
        assert "read-only" in 唯讀
        assert "--approve-for-me" in 可寫
        assert "--sandbox" not in 可寫

    def test_agy可編輯時換成accept_edits(self) -> None:
        可寫 = 建立("agy", 執行檔=Path("/x")).組參數("提示", 呼叫選項(權限=權限.可編輯))
        assert 可寫[可寫.index("--mode") : 可寫.index("--mode") + 2] == ["--mode", "accept-edits"]

    def test_三家都不准用最危險的旗標(self) -> None:
        危險 = (
            "--dangerously-skip-permissions",
            "--dangerously-bypass-approvals-and-sandbox",
            "--dangerously-bypass-hook-trust",
        )
        for 家 in ("claude", "codex", "agy"):
            for 可以做什麼 in 權限:
                參數 = 建立(家, 執行檔=Path("/x")).組參數("提示", 呼叫選項(權限=可以做什麼))
                assert not (set(危險) & set(參數)), f"{家} 在 {可以做什麼} 用了危險旗標"


class Test隔離設定是漏出的:
    """讀了家目錄設定，nova[claude] 就跟 nova[codex] 行為不同。"""

    def test_預設隔離(self) -> None:
        assert 呼叫選項().隔離設定 is True

    def test_claude隔離用bare不隔離用restricted(self) -> None:
        """`--bare` 連 keychain 都不讀（訂閱登入會死），所以要有退路。"""
        隔離 = 建立("claude", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        不隔離 = 建立("claude", 執行檔=Path("/x")).組參數("提示", 呼叫選項(隔離設定=False))
        assert "--bare" in 隔離 and "--restricted" not in 隔離
        assert "--restricted" in 不隔離 and "--bare" not in 不隔離

    def test_codex隔離才擋使用者設定(self) -> None:
        隔離 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        不隔離 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項(隔離設定=False))
        assert "--ignore-user-config" in 隔離 and "--ignore-rules" in 隔離
        assert "--ignore-user-config" not in 不隔離


class Test預設模型:
    def test_agy有預設模型與推理強度(self) -> None:
        """agy 的推理強度包在型號裡（`agy models` 實測），不是另一個旗標。"""
        參數 = 建立("agy", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        assert ["--model", agy預設模型] == 參數[參數.index("--model") : 參數.index("--model") + 2]
        assert agy預設模型.endswith("-high"), "沒指定就要用最高的推理強度"

    def test_codex有預設模型與推理強度(self) -> None:
        """codex 沒有 `--effort` 旗標（實測），推理強度走 `-c` 設定覆寫。"""
        參數 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        assert ["--model", codex常用模型] == 參數[參數.index("--model") : 參數.index("--model") + 2]
        assert 參數[參數.index("-c") + 1] == f'model_reasoning_effort="{codex推理強度}"'

    def test_codex的推理強度值是合法TOML(self) -> None:
        """`-c` 的值會被當 TOML 解析，字串沒包引號會變成別的東西。"""
        參數 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        鍵值 = 參數[參數.index("-c") + 1]
        assert tomllib.loads(鍵值)["model_reasoning_effort"] == codex推理強度

    def test_codex只用兩個型號(self) -> None:
        """使用者裁定：luna 常用、sol 高階推理，基本上就這兩個。"""
        assert codex常用模型 == "gpt-5.6-luna"
        assert codex高階模型 == "gpt-5.6-sol"

    def test_指定模型會蓋掉預設(self) -> None:
        家與預設: tuple[tuple[家族, str], ...] = (("agy", agy預設模型), ("codex", codex常用模型))
        for 家, 預設 in 家與預設:
            參數 = 建立(家, 執行檔=Path("/x")).組參數("提示", 呼叫選項(模型="我指定的"))
            assert "我指定的" in 參數
            assert 預設 not in 參數


class Testclaude的變長參數:
    def test_tools不准緊鄰提示(self) -> None:
        """`--tools <tools...>` 會把後面的提示一起吞掉，claude 會說「沒有 prompt」。

        實測踩過一次：真 CLI 才抓得到，假 CLI 不會抱怨。
        """
        for 可以做什麼 in 權限:
            參數 = 建立("claude", 執行檔=Path("/x")).組參數("我的提示", 呼叫選項(權限=可以做什麼))
            工具值後面 = 參數[參數.index("--tools") + 2]
            assert 工具值後面.startswith("-"), (
                f"--tools 的值後面必須接一個選項終結變長參數，實際是 {工具值後面!r}"
            )
            assert 參數[-1] == "我的提示"

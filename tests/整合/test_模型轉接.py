"""轉接器的全鏈路：真的 fork 子程序，但子程序是假 CLI，不燒 token。

假 CLI 讀環境變數決定要吐哪一份實錄、用哪個結束碼，所以連
「工作目錄有沒有傳下去」「逾時會不會殺掉」都測得到——這是純函式測不到的那一段。
"""

import os
import stat
import sys
import tomllib
from pathlib import Path

import pytest

from nova.契約.模型回應 import 終局
from nova.契約.角色 import 呼叫選項, 權限
from nova.載體.模型.執行 import 跑cli
from nova.載體.模型.解析 import 解析agy
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

#: 假 CLI 的 shebang **走 `sys.executable`，不走 `/usr/bin/env python3`**。
#: 兩個理由：一，`env python3` 在這台機器上指到系統的 3.9.6，不是專案釘的 3.13——
#: 假 CLI 跑在錯的直譯器上，哪天用到新語法會紅在跟測試完全無關的地方。
#: 二，實測快約 10 毫秒（3.9.6 起得比 3.13 慢）。
假CLI內容 = f"""#!{sys.executable}
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


@pytest.fixture(scope="session")
def 假CLI(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """整個 session 共用同一支假 CLI。

    **行為本來就靠環境變數切**（見 `假CLI內容`），所以沒有理由每支測試重寫一份檔。

    實測（macOS、n=15 取中位數）：

        新寫一份檔再第一次執行 ...... 122 毫秒
        同一支重複執行 .............. 14 毫秒

    貴的不是 fork，是 **macOS 對「剛寫出來的新執行檔」的第一次執行檢查**，約 100 毫秒。
    那 100 毫秒每支都白付一次。
    """
    路徑 = tmp_path_factory.mktemp("假cli") / "假cli"
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
        assert "Write" not in 參數[參數.index("--tools") + 1], (
            "唯讀不准有 Write——工具白名單就是「載體被關到多小」的那一格"
        )
        assert 參數[參數.index("--setting-sources") : 參數.index("--setting-sources") + 2] == [
            "--setting-sources",
            "",
        ], "設定隔離走 --setting-sources，不要換回 --bare（那條連 keychain 都不讀）"
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

    def test_claude唯讀是讀得到但寫不了(self) -> None:
        """**`--tools ""` 不是唯讀，是把它關進小黑屋。**

        help 原文「Use "" to disable all tools」的 all 是真的 all——連 Read 都沒了。
        實測叫它讀工作目錄裡的一個檔案，回的是
        「I can't do this one — I don't have any file access tools available」。

        唯讀的意思是**看得到但不准改**，所以走白名單 `Read,Grep,Glob`：
        實測讀得到檔案內容，而叫它寫檔會回「我只有唯讀類的工具，沒有 Write、Edit、
        Bash」——**擋在工具層，不是靠模型自律**。

        （這一輪順帶看到 `--tools` 管不到 MCP 工具：那次回應說它還有 Context7 可用。
        要一起關掉得再加 `--strict-mcp-config`，還沒做，見設計文件 02 的已知缺口。）
        """
        唯讀 = 建立("claude", 執行檔=Path("/x")).組參數("提示", 呼叫選項(工作目錄=Path("/w")))
        工具 = 唯讀[唯讀.index("--tools") + 1].split(",")
        assert set(工具) == {"Read", "Grep", "Glob"}, f"唯讀的工具白名單不對：{工具}"
        assert "--restricted" in 唯讀, "唯讀也要把 Read 關在工作目錄裡"
        assert 唯讀[唯讀.index("--add-dir") : 唯讀.index("--add-dir") + 2] == ["--add-dir", "/w"]

    def test_claude可編輯時才給寫的工具(self) -> None:
        唯讀 = 建立("claude", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        可寫 = 建立("claude", 執行檔=Path("/x")).組參數("提示", 呼叫選項(權限=權限.可編輯))
        assert "Write" not in 唯讀[唯讀.index("--tools") + 1]
        assert "Write" in 可寫[可寫.index("--tools") + 1]
        assert 可寫[可寫.index("--permission-mode") : 可寫.index("--permission-mode") + 2] == [
            "--permission-mode",
            "acceptEdits",
        ]
        assert "--permission-mode" not in 唯讀, "唯讀模式不該帶權限模式旗標"

    def test_codex可編輯用真沙箱而不是自動核准(self) -> None:
        """`--approve-for-me` 的邊界是假的。**需求變了，不是測試配合實作。**

        help 原文：「Route approval requests through automatic review using the
        workspace-write sandbox」——**自動審核**，不是不准。實測叫它
        `printf '芒果乾' > ~/x.txt`：模型先說「這個路徑在工作區外，需要額外權限」，
        然後自己核准了，`exit_code: 0`，檔案真的出現在家目錄。

        `--sandbox workspace-write` 才是真邊界：同一條指令回
        「系統拒絕寫入（operation not permitted）」，而寫 cwd 照樣成功。
        **三家裡只有 codex 有 OS 層邊界**——claude 的 `--restricted` 只擋檔案工具
        （Bash 繞得過，實測繞過去了），agy 連 plan 模式都擋不住寫。

        代價：workspace-write 沙箱同時關掉網路與工作區外的寫入，所以
        「可編輯」這一級裝不了套件。要那個就用全開。
        """
        唯讀 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        可寫 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項(權限=權限.可編輯))
        assert 唯讀[唯讀.index("--sandbox") : 唯讀.index("--sandbox") + 2] == [
            "--sandbox",
            "read-only",
        ]
        assert 可寫[可寫.index("--sandbox") : 可寫.index("--sandbox") + 2] == [
            "--sandbox",
            "workspace-write",
        ]
        assert "--approve-for-me" not in 可寫, "自動核准會把「升級到工作區外」一起核准掉"

    def test_agy可編輯時換成accept_edits(self) -> None:
        可寫 = 建立("agy", 執行檔=Path("/x")).組參數("提示", 呼叫選項(權限=權限.可編輯))
        assert 可寫[可寫.index("--mode") : 可寫.index("--mode") + 2] == ["--mode", "accept-edits"]

    def test_claude可編輯要同時給白名單(self) -> None:
        """`--permission-mode acceptEdits` **一個人不夠**。

        實測：隔離設定（`--setting-sources ""`）之下只給 acceptEdits，claude 會回
        「I need permission to create the file — pending approval on your end」，
        檔案一個都沒寫。把 `--allowedTools` 補上同一份清單就寫得出來了。

        推測是 acceptEdits 要靠「這個目錄已被信任」那份使用者設定，而隔離之後
        那份讀不到。**這是實測結論，不是推測出來的用法**——
        `test_可編輯真的寫得出檔案[claude]` 就是被它咬紅過的那支。
        """
        可寫 = 建立("claude", 執行檔=Path("/x")).組參數("提示", 呼叫選項(權限=權限.可編輯))
        assert "--allowedTools" in 可寫, "只給 acceptEdits 會卡在 pending approval"
        assert 可寫[可寫.index("--allowedTools") + 1] == 可寫[可寫.index("--tools") + 1], (
            "白名單與工具清單要是同一份，不然會出現「有工具但不准用」的空隙"
        )

    def test_claude可編輯要把檔案工具關在工作目錄裡(self) -> None:
        """`--restricted --add-dir <工作目錄>`：檔案工具只准動工作目錄。

        實測踩過：沒有這兩條時 claude 自己猜路徑，把檔案寫進了 **nova 的 repo 根目錄**
        （而且它還在 `/tmp/claude-workdir/` 另外建了一份）。加上之後兩次實跑都乖乖
        寫在 cwd，而且叫它寫工作目錄外面會被檔案工具擋下來。

        **這是加速器不是保證**：同一次實測裡，改叫它用 Bash 重導向就照樣寫出去了。
        claude 沒有 OS 層沙箱（codex 的 `--sandbox` 才有）。要硬保證得靠外面。
        """
        可寫 = 建立("claude", 執行檔=Path("/x")).組參數(
            "提示", 呼叫選項(權限=權限.可編輯, 工作目錄=Path("/w"))
        )
        assert "--restricted" in 可寫
        assert 可寫[可寫.index("--add-dir") : 可寫.index("--add-dir") + 2] == ["--add-dir", "/w"]

    def test_claude全開不准帶restricted(self) -> None:
        """`--restricted` 的 help 原文寫明它 **refuses bypassPermissions**——兩條互斥。"""
        全開 = 建立("claude", 執行檔=Path("/x")).組參數(
            "提示", 呼叫選項(權限=權限.全開, 工作目錄=Path("/w"))
        )
        assert "--restricted" not in 全開

    def test_agy有工作目錄就要加進workspace(self) -> None:
        """沒有 `--add-dir`，agy 的檔案工具會寫到 `~/.gemini/antigravity-cli/scratch/`。

        實測：`--mode accept-edits` 跑完回「好了」、cwd 卻空的。追 stream-json 才看到
        `write_to_file` 的 `TargetFile` 指到那個 scratch 目錄——**模型沒說謊，
        它真的寫了，只是寫到別的地方**。`--add-dir <工作目錄>` 之後就寫進 cwd 了。

        這種假成功比報錯難抓：`status: SUCCESS`、`response` 也有話說，
        `_成功但沒話說算未知` 攔不到它。只有真的去看檔案系統才會紅。
        """
        可寫 = 建立("agy", 執行檔=Path("/x")).組參數(
            "提示", 呼叫選項(權限=權限.可編輯, 工作目錄=Path("/w"))
        )
        assert 可寫[可寫.index("--add-dir") : 可寫.index("--add-dir") + 2] == ["--add-dir", "/w"]
        # 唯讀那一級刻意不給——理由見 test_agy唯讀不給add_dir是刻意的

    def test_agy三種權限都要給add_dir(self) -> None:
        """**唯讀的意思是「看得到但不准改」，不是「什麼都看不到」。**

        這一條改過一次，過程值得留著：原本唯讀刻意不給 `--add-dir`，理由是
        agy 的 `--mode plan` 擋不住寫（`--sandbox`、兩條一起，三種都實測過），
        不給 `--add-dir` 至少能保證它動不到工作目錄。

        那個保證是真的，但**它把唯讀的用途一起換掉了**：唯讀的 agy 連讀都讀不到
        （工具被 headless 權限系統 auto-deny，回一個空的 response）。而 nova 唯一
        的唯讀呼叫端是**工作流的審查員**——一個「請指出具體的檔案與行號」卻看不到
        檔案的審查員，只會回空回應、把工作流卡在結果未知。

        所以換回來：三種權限都給 `--add-dir`，而
        **agy 的唯讀明確標成加速器不是保證**（`test_agy的唯讀擋不住寫檔這是已知事實`
        斷言的就是「擋不住」）。誠實標示比假保證好，也比一個看不見東西的審查員好。

        升級路徑（尚未做）：唯讀模式下由 nova 自己在跑完之後比對工作目錄有沒有被
        改動，有的話把終局降成結果未知——偵測型保證，不是預防型，但那是 nova
        自己拿得出來的東西，不必等 agy。
        """
        for 可以做什麼 in (權限.唯讀, 權限.可編輯, 權限.全開):
            參數 = 建立("agy", 執行檔=Path("/x")).組參數(
                "提示", 呼叫選項(權限=可以做什麼, 工作目錄=Path("/w"))
            )
            assert 參數[參數.index("--add-dir") : 參數.index("--add-dir") + 2] == [
                "--add-dir",
                "/w",
            ], f"{可以做什麼} 少了 --add-dir：寫檔會落到 agy 的 scratch 目錄，讀檔會被 auto-deny"

    def test_沒給工作目錄就不要亂加add_dir(self) -> None:
        """`--add-dir` 的值是路徑，沒有工作目錄時沒有正確的值可填——寧可不加。"""
        for 家 in ("claude", "agy"):
            參數 = 建立(家, 執行檔=Path("/x")).組參數("提示", 呼叫選項(權限=權限.可編輯))
            assert "--add-dir" not in 參數, f"{家} 在沒有工作目錄時加了 --add-dir"

    def test_危險旗標只准出現在全開(self) -> None:
        """需求變了：不再是「一律不准」，而是「只准在明講全開時出現」。

        全開有正當用途（跑在已經被隔離的環境裡），一律禁掉只會逼人繞過介面
        自己拼指令——那更糟。但它每多開一級，「模型能對這台機器做什麼」
        就少一層攔截，所以必須是明講的、而且不可能誤觸的。
        """
        危險 = (
            "--dangerously-skip-permissions",
            "--dangerously-bypass-approvals-and-sandbox",
            "--dangerously-bypass-hook-trust",
        )
        for 家 in ("claude", "codex", "agy"):
            for 可以做什麼 in (權限.唯讀, 權限.可編輯):
                參數 = 建立(家, 執行檔=Path("/x")).組參數("提示", 呼叫選項(權限=可以做什麼))
                assert not (set(危險) & set(參數)), f"{家} 在 {可以做什麼} 用了危險旗標"

    def test_全開才有危險旗標(self) -> None:
        """三家都要真的有一條全開的路，不然這一級是假的。"""
        對應: tuple[tuple[家族, str], ...] = (
            ("claude", "--dangerously-skip-permissions"),
            ("codex", "--dangerously-bypass-approvals-and-sandbox"),
            ("agy", "--dangerously-skip-permissions"),
        )
        for 家, 旗標 in 對應:
            參數 = 建立(家, 執行檔=Path("/x")).組參數("提示", 呼叫選項(權限=權限.全開))
            assert 旗標 in 參數, f"{家} 的全開沒有真的全開"

    def test_全開不是預設(self) -> None:
        """忘了設不會變成全開——最嚴的那一邊當預設。"""
        assert 呼叫選項().權限 is 權限.唯讀
        assert 權限.全開 is not 呼叫選項().權限

    def test_codex續接時不准出現危險旗標(self) -> None:
        """`exec resume` 不吃這些，而且權限本來就沿用原 session。"""
        參數 = 建立("codex", 執行檔=Path("/x")).組參數(
            "提示", 呼叫選項(續接="某個id", 權限=權限.全開)
        )
        assert "--dangerously-bypass-approvals-and-sandbox" not in 參數


class Test隔離設定是漏出的:
    """讀了家目錄設定，nova[claude] 就跟 nova[codex] 行為不同。"""

    def test_預設隔離(self) -> None:
        assert 呼叫選項().隔離設定 is True

    def test_claude用setting_sources隔離而不是bare(self) -> None:
        """實測：`--setting-sources ""` 讓 CLAUDE.md 讀不到，**而且訂閱登入照樣能用**。

        `--bare` 也能隔離，但它連 keychain 與 OAuth 都不讀——訂閱使用者會直接
        變成「Not logged in」。兩條都能隔離時，要選不會弄壞認證的那條。
        """
        隔離 = 建立("claude", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        不隔離 = 建立("claude", 執行檔=Path("/x")).組參數("提示", 呼叫選項(隔離設定=False))
        assert 隔離[隔離.index("--setting-sources") : 隔離.index("--setting-sources") + 2] == [
            "--setting-sources",
            "",
        ]
        assert "--bare" not in 隔離, "--bare 會弄壞訂閱登入"
        assert "--setting-sources" not in 不隔離

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


class Test持久對話:
    """記住 sid ＋ 下一輪帶回去，就能跟同一段對話繼續講。"""

    def test_預設不續接(self) -> None:
        assert 呼叫選項().續接 is None

    def test_claude用resume(self) -> None:
        參數 = 建立("claude", 執行檔=Path("/x")).組參數("提示", 呼叫選項(續接="某個id"))
        assert 參數[參數.index("--resume") : 參數.index("--resume") + 2] == ["--resume", "某個id"]

    def test_agy用conversation(self) -> None:
        參數 = 建立("agy", 執行檔=Path("/x")).組參數("提示", 呼叫選項(續接="某個id"))
        assert 參數[參數.index("--conversation") : 參數.index("--conversation") + 2] == [
            "--conversation",
            "某個id",
        ]

    def test_codex用resume子指令(self) -> None:
        """codex 的續接是**子指令**不是旗標，而且 id 是位置參數。"""
        參數 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項(續接="某個id"))
        assert 參數[:2] == ["exec", "resume"]
        assert 參數[-2:] == ["某個id", "提示"]

    def test_codex續接時不准給sandbox或核准旗標(self) -> None:
        """實測：`exec resume` 不吃這兩條，給了 exit 2。權限沿用原 session。"""
        for 可以做什麼 in 權限:
            參數 = 建立("codex", 執行檔=Path("/x")).組參數(
                "提示", 呼叫選項(續接="某個id", 權限=可以做什麼)
            )
            assert "--sandbox" not in 參數
            assert "--approve-for-me" not in 參數

    def test_codex續接時不准ephemeral(self) -> None:
        """`--ephemeral` 不落地，續接完就再也接不下去。"""
        參數 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項(續接="某個id"))
        assert "--ephemeral" not in 參數

    def test_codex不保留對話時才ephemeral(self) -> None:
        """預設不留檔（省磁碟）；要之後續接就得先 保留對話=True。"""
        不留 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項())
        要留 = 建立("codex", 執行檔=Path("/x")).組參數("提示", 呼叫選項(保留對話=True))
        assert "--ephemeral" in 不留
        assert "--ephemeral" not in 要留

    def test_三家的續接旗標都不會吞掉提示(self) -> None:
        """`--resume [value]` 這種可選值旗標放錯位置會把提示吃掉。"""
        for 家 in ("claude", "codex", "agy"):
            參數 = 建立(家, 執行檔=Path("/x")).組參數("我的提示", 呼叫選項(續接="某個id"))
            assert 參數[-1] == "我的提示", f"{家} 的提示被吞掉了"


class Test解析要容忍控制字元:
    """真實工具會吐未跳脫的控制字元，嚴格模式當場解不動 → fail-closed 成結果未知。"""

    def test_response裡有原始換行也解得動(self) -> None:
        壞掉的 = (
            '{"conversation_id":"x","status":"SUCCESS",'
            '"response":"第一行\\n第二行",'
            '"usage":{"input_tokens":1,"output_tokens":1}}'
        )
        答 = 解析agy(壞掉的, 0)
        assert 答.終局 is 終局.成功, "嚴格 JSON 解析會把這個變成『結果未知』"
        assert "第二行" in 答.文字

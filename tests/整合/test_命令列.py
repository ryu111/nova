"""CLI 是所有執行點（pre-commit、CI、agent hook）唯一的入口。

介面壞掉的話，三個地方會同時失去防護而且沒人發現，所以端到端跑真的執行檔。
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nova.契約.工作流 import 步驟結果, 種類, 結束, 結束代碼, 階段代碼
from nova.契約.模型回應 import 終局
from nova.契約.派工 import 工作種類
from nova.載體.剖析器 import 建剖析器
from nova.載體.命令列 import (
    _哪幾家,
    _工作流退出碼,
    _工作流開跑前,
    _建腦,
    _濾掉熔斷的,
    _醒來,
    _階段的工作種類,
    _階段的派法,
    主程式,
    放行,
    未知,
    處理們,
    護欄碼,
    閘紅,
    阻擋,
)
from nova.載體.帳本 import 不記帳本
from nova.載體.派工表 import 怎麼派
from nova.載體.角色 import 組提示
from nova.迴圈 import 角色提示
from nova.迴圈.狀態機 import TDD階段表

做假CLI型 = Callable[..., tuple[Path, Path]]

nova執行檔 = Path(sys.executable).parent / "nova"
專案根目錄 = Path(__file__).resolve().parent.parent.parent


def _跑(
    *參數: str,
    輸入: str | None = None,
    環境: dict[str, str] | None = None,
    在: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在 or 專案根目錄,
        env=None if 環境 is None else {**os.environ, **環境},
        capture_output=True,
        text=True,
        input=輸入,
        check=False,
    )


class Test檢查指令:
    def test_禁令退出碼是2(self) -> None:
        """2 是 agent hook 的「阻擋」約定；非 0 對一般呼叫端也是失敗。"""
        結果 = _跑("檢查指令", "git commit --no-verify -m 訊息")
        assert 結果.returncode == 2
        assert "--no-verify" in 結果.stderr

    def test_正常指令放行(self) -> None:
        assert _跑("檢查指令", "git status").returncode == 0

    def test_從stdin讀json(self) -> None:
        """agent hook 送 JSON 進來。欄位名相容 Claude Code 的 tool_input.command。"""
        載荷 = json.dumps({"tool_input": {"command": "gh pr merge 1 --admin"}})
        結果 = _跑("檢查指令", "--stdin", 輸入=載荷)
        assert 結果.returncode == 2
        assert "--admin" in 結果.stderr

    def test_stdin沒有指令時放行(self) -> None:
        """hook 會對每個工具呼叫都送 JSON，不是 Bash 的就沒有 command 欄位。"""
        結果 = _跑("檢查指令", "--stdin", 輸入=json.dumps({"tool_input": {"file_path": "甲.py"}}))
        assert 結果.returncode == 0

    def test_stdin壞掉的json算擋下(self) -> None:
        結果 = _跑("檢查指令", "--stdin", 輸入="{壞掉的")
        assert 結果.returncode == 2

    def test_擋下來的訊息要帶真的會話識別碼(self) -> None:
        """**佔位符等於沒給。**

        2026-08-30 這道護欄第一次擋到人的時候，訊息裡寫的是字面的
        `--會話 <會話識別碼>`。人照著複製會失敗；更糟的是那個佔位符含角括號，
        複製下來執行會命中重導樣式**被護欄自己擋掉**——擋了就沒有出路。

        hook 的 JSON 裡本來就有 `session_id`，接上就好。
        `檢查編輯`（Edit／Write 那條）一直都是這樣做的，只有這條漏了。
        """
        載荷 = json.dumps(
            {
                "session_id": "阿貓-1234",
                "tool_input": {"command": "echo x > src/nova/甲.py"},
            }
        )

        結果 = _跑("檢查指令", "--stdin", 輸入=載荷)

        assert 結果.returncode == 2, 結果.stdout + 結果.stderr
        assert "阿貓-1234" in 結果.stderr, f"訊息裡沒有真的會話識別碼：{結果.stderr}"

    def test_說明文字要反映檢查受管轄寫入(self) -> None:
        """檢查指令的 CLI 說明不能只寫違反禁令，必須反映也檢查寫入受管轄檔案。"""
        結果 = _跑("--help")
        assert 結果.returncode == 0
        說明行 = [行 for 行 in 結果.stdout.splitlines() if "檢查指令" in 行]
        assert 說明行, "help 輸出中找不到 檢查指令 子命令"
        assert any("管轄" in 行 for 行 in 說明行), f"說明文字未提及管轄寫入：{說明行}"

    def test_說得出理由就放行(self, tmp_path: Path) -> None:
        """**繞過必須對 Bash 這條路也有效。**

        `檢查編輯`（Edit／Write 那條）本來就會先問 `說得出理由了嗎`，
        `檢查指令`（Bash 那條）漏了——於是擋下來之後**沒有任何出路**，
        連 `nova 繞過` 自己都執行不了。
        """
        環境 = {"XDG_STATE_HOME": str(tmp_path / "state")}
        專案 = tmp_path / "某專案"
        (專案 / "src").mkdir(parents=True)

        載荷 = json.dumps(
            {
                "session_id": "s-1",
                "tool_input": {"command": "echo x > src/甲.py"},
            }
        )

        未繞過 = _跑("檢查指令", "--stdin", 輸入=載荷, 環境=環境, 在=專案)
        assert 未繞過.returncode == 2

        _跑(
            "繞過",
            "--會話",
            "s-1",
            "--因為",
            "測試用的理由",
            環境=環境,
            在=專案,
        )

        已繞過 = _跑("檢查指令", "--stdin", 輸入=載荷, 環境=環境, 在=專案)
        assert 已繞過.returncode == 0, "已經記下理由了還擋，那個繞過機制等於不存在"

    def test_沒說理由就照擋(self, tmp_path: Path) -> None:
        """**不能擋不住**——放行的條件是「說得出理由」，不是「有傳會話參數」。"""
        環境 = {"XDG_STATE_HOME": str(tmp_path / "state")}
        專案 = tmp_path / "某專案"
        (專案 / "src").mkdir(parents=True)

        載荷 = json.dumps(
            {
                "session_id": "沒記過的",
                "tool_input": {"command": "echo x > src/甲.py"},
            }
        )
        結果 = _跑("檢查指令", "--stdin", 輸入=載荷, 環境=環境, 在=專案)
        assert 結果.returncode == 2


class Test閘:
    def test_未知閘點要報錯不是靜默全綠(self) -> None:
        結果 = _跑("閘", "不存在的閘點")
        assert 結果.returncode != 0
        assert "未知的閘點" in 結果.stdout + 結果.stderr

    def test_沒給閘點要報錯(self) -> None:
        assert _跑("閘").returncode != 0

    @pytest.mark.serial
    def test_提交閘在本repo上是綠的(self) -> None:
        """會巢狀啟動 pytest 與 ruff，標 serial 避免和別的測試搶 CPU。"""
        結果 = _跑("閘", "提交")
        assert 結果.returncode == 0, 結果.stdout + 結果.stderr
        assert "lang-traditional" in 結果.stdout


class Test檢查提交訊息:
    def test_繁體訊息放行(self, tmp_path: Path) -> None:
        檔 = tmp_path / "訊息"
        檔.write_text("載體：加上閘的核心\n", encoding="utf-8")
        assert _跑("檢查提交訊息", str(檔)).returncode == 0

    def test_簡體訊息要擋(self, tmp_path: Path) -> None:
        檔 = tmp_path / "訊息"
        檔.write_text("这是简体的提交訊息\n", encoding="utf-8")  # nova:允許非繁體
        結果 = _跑("檢查提交訊息", str(檔))
        assert 結果.returncode != 0
        assert "简" in 結果.stderr or "这" in 結果.stderr  # nova:允許非繁體


class Test工作流的退出碼要分得出護欄與壞掉:
    """外圈（`/goal` 驅動的修復迴圈、CI、任何腳本）看到的是**退出碼**，不是中文句子。

    把「護欄生效」與「東西壞了」壓成同一個 `1`，外圈就只能讀 stderr 的自由文字
    做判斷——那正是規格 §4.3 說的「自由段落逼下游重建上游語意」。

    而且那個誤判有方向：**護欄最省事的「修法」是把上限調高**，
    一個分不出來的自動修復迴圈會很合理地那樣做，然後回報修好了。
    """

    def test_四種收場四個碼(self) -> None:
        對應 = {
            結束代碼.完成: 放行,
            結束代碼.護欄: 護欄碼,
            結束代碼.中止: 閘紅,
        }
        for 代碼, 期望 in 對應.items():
            assert _工作流退出碼(結束(代碼, "理由"), ()) == 期望, 代碼

    def test_結果未知蓋過一切(self) -> None:
        """有任何一步「結果未知」就是 3——**不准重跑**那條蓋過收場分類。

        護欄碼 4 代表「按設計停了，可以改題目再跑」；但只要軌跡裡有一步
        可能做了一半，重跑就會重做副作用。**保守的那個要贏。**
        """
        半 = 步驟結果(階段=階段代碼.測試, 終局=終局.結果未知, 判準綠=None, 證據="")
        assert _工作流退出碼(結束(結束代碼.護欄, "預算用完"), (半,)) == 未知

    def test_四個碼互不相同(self) -> None:
        """不然上面那些斷言可能是空的。"""
        assert len({放行, 閘紅, 未知, 護欄碼}) == 4


class Test工作流不給用哪家就照派工表:
    """派工表寫著策略，**但工作流曾經從來沒讀過它**。

    實測後果（今天一整天的帳本）：

        codex   17,058,727 token
        agy        784,156 token

    22:1。因為工作流的四個階段全都用 `--用` 那一顆，而我每次都打 codex。
    **策略寫在表裡但沒有人執行，等於沒有策略**——那正是「提示裡的是懇求」。

    分法照 `工作種類` 的定義，不是我發明的：
    測試／實作／重構是「照現成樣子寫、答案對不對看得出來」＝例行；
    審查是「設計取捨、找漏洞、答案對不對要靠推理」＝推理。

    這一格守的是**階段到工作種類的對應**。哪一家排第一順位是策略，
    住在 `tests/單元/test_派工表.py`——在這裡再抄一份的話，翻面時要改兩處，
    而漏改的那處會用一句過時的斷言把新策略judge成錯的。
    """

    def test_不給用哪家時例行階段走派工表的例行(self) -> None:
        assert 怎麼派(工作種類.例行).腦們, "例行鏈是空的，走派工表這條路等於沒派"
        for 階段 in (階段代碼.測試, 階段代碼.實作, 階段代碼.重構):
            assert _階段的工作種類(階段) is 工作種類.例行, 階段

    def test_審查走推理(self) -> None:
        assert _階段的工作種類(階段代碼.審查) is 工作種類.推理
        assert 怎麼派(工作種類.推理).模型 is not None, "推理不指名模型會拿到便宜的預設"

    def test_每個模型階段都要有工作種類(self) -> None:
        """**窮舉**：加階段忘了配工作種類，會在跑到那一階時才炸。"""
        for 定義 in TDD階段表:
            if 定義.種類 is not 種類.判準:
                assert _階段的工作種類(定義.代碼) is not None, 定義.代碼

    def test_不給用哪家也不會被自寫自評擋下(self) -> None:
        """派工表挑出來的兩家必須不同，不然工作流開頭那道檢查會擋下來。"""
        例行 = 怎麼派(工作種類.例行).腦們[0]
        推理 = 怎麼派(工作種類.推理).腦們[0]
        assert 例行 != 推理, "派工表挑出同一家，審查就變成自寫自評"

    def test_例行階段的思考深度是high(self) -> None:
        for 階段 in (階段代碼.測試, 階段代碼.實作, 階段代碼.重構):
            assert _階段的派法(階段).思考深度 == "high", 階段

    def test_審查階段的思考深度是max(self) -> None:
        assert _階段的派法(階段代碼.審查).思考深度 == "max"


class Test不給用哪家也不准自寫自評:
    """真跑才抓到的一個 `AttributeError`。

    `--用` 變成非必填之後，那道檢查 `參數.用.split(",")` 直接
    `AttributeError: 'NoneType' object has no attribute 'split'`。

    **假輸入測不到這一格**——單元測試餵的是已經填好的字串。
    這就是「墊片證明的是轉遞形狀，不是可達性」的又一次。

    而且這道檢查不能只是「不炸」：它守的是硬規則 5（不得自寫自評），
    走派工表的時候也要真的問得出兩邊各是誰。

    **但重疊本身不再是那條紅線**（`#140`）：判準是**對話**不是家族名，
    三家不給續接時本來就都是新對話，`固定提示角色` 連續接欄位都沒有——
    同一個對話裡自寫自評在結構上不可能。門口那一格由
    `tests/驗收/test_委派給其他llm.py::test_同一家不再擋在門口` 背書。
    """

    def test_不給旗標時兩邊都問得出非空的鏈(self) -> None:
        """守的是「這條路走得通」：兩階都問得到派法，而且都不是空鏈。

        空鏈會讓 `_哪幾家` 回空集合，資格檢查就變成「沒有人不合格」——
        **fail-open**，看起來綠但什麼都沒守到。
        """
        例行 = set(_階段的派法(階段代碼.測試).腦們)
        推理 = set(_階段的派法(階段代碼.審查).腦們)
        assert 例行 and 推理, f"派工表挑出空鏈：例行={例行} 推理={推理}"

    def test_跑得起來不會炸(self) -> None:
        """不給 `--用` 與 `--審查用`，走到派工表那條路而不是 `AttributeError`。

        **只斷言不炸，不斷言退出碼**——這一格被 CI 教過一次：
        CI 沒裝三家 CLI，而推理那條鏈只有一顆（`可以缺席=False`），
        建角色時就 `FileNotFoundError` 了，退出碼是 2 不是 4。
        本機綠、CI 紅，差別是**環境**（硬規則 6 的第一層）。

        退出碼的對應由 `test_四種收場四個碼` 用純函式守，不必在這裡重測——
        在這裡測等於把一條純函式的保證綁在「這台機器裝了什麼」上。
        """
        結果 = _跑("工作流", "--最多步數", "0", "--判準", "true", "隨便")
        assert "AttributeError" not in 結果.stderr, 結果.stderr[:400]
        assert 結果.returncode != 放行, "什麼都沒跑不該回成功"

    def test_沒給旗標時哪幾家要問派工表(self) -> None:
        """**負控抓到的洞。**

        把 `_哪幾家` 改成「沒給旗標就回空集合」，上面那兩支照樣綠——
        因為空集合跟空集合不重疊，自寫自評的檢查會「通過」。
        **那正是護欄失效卻看起來正常的樣子。**

        所以要直接釘住接縫本身：沒給旗標時，比對的必須是派工表挑出來的家。
        """
        assert _哪幾家(None, 階段代碼.測試) == set(_階段的派法(階段代碼.測試).腦們)
        assert _哪幾家(None, 階段代碼.審查) == set(_階段的派法(階段代碼.審查).腦們)
        assert _哪幾家(None, 階段代碼.測試), "空集合跟任何東西都不重疊，等於沒檢查"

    def test_給了旗標就以旗標為準(self) -> None:
        assert _哪幾家("codex,agy", 階段代碼.測試) == {"codex", "agy"}


class Test本地腦沒有審查資格:
    """9B 本地模型不能驗收另一顆腦的產出。"""

    def test_本地腦不准當審查員(self, tmp_path: Path) -> None:
        """即使和執行者不同家，也要在啟動模型前擋下 local 審查員。"""
        參數 = 建剖析器(處理們).parse_args(
            [
                "工作流",
                "--用",
                "codex",
                "--審查用",
                "local",
                "--工作目錄",
                str(tmp_path),
                "隨便",
            ]
        )
        這次 = _醒來()

        碼 = _工作流開跑前(參數, tmp_path, None, 這次)

        assert 碼 == 阻擋, "local 當審查員時，應在啟動模型前被擋下"
        assert "local" in 這次.理由
        assert "審查" in 這次.理由


class Test進度檔在工作目錄裡要被擋下來:
    """純函式擋得住不代表 CLI 擋得住——**要真的有人叫它**。

    這一格是真跑七階段時被種進去的：模型讀了進度檔、照抄格式、
    接了一段自己的摘要上去。純函式在 `tests/單元/test_進度檔.py` 守，
    這裡守的是「CLI 有沒有接上」。
    """

    def test_CLI要真的擋(self, tmp_path: Path) -> None:
        結果 = _跑(
            "工作流",
            "--工作目錄",
            str(tmp_path),
            "--進度檔",
            str(tmp_path / "進度.md"),
            "--最多步數",
            "0",
            "--判準",
            "true",
            "隨便",
        )
        assert 結果.returncode == 阻擋, f"沒擋下來：{結果.returncode}／{結果.stderr[:200]}"
        assert "工作目錄" in 結果.stderr

    def test_放外面就放行(self, tmp_path: Path) -> None:
        """**這支防的是擋過頭**——擋掉全部就沒有進度檔可以用了。"""
        工作區 = tmp_path / "工作區"
        工作區.mkdir()
        結果 = _跑(
            "工作流",
            "--工作目錄",
            str(工作區),
            "--進度檔",
            str(tmp_path / "進度.md"),
            "--最多步數",
            "0",
            "--判準",
            "true",
            "隨便",
        )
        # **斷言看訊息不看退出碼**——這一格被 CI 教過一次：
        # CI 沒裝三家 CLI，建腦時 FileNotFoundError，一樣回 2。
        # 退出碼在那裡是對的，只是不是這支測試在守的那件事。
        assert "在工作目錄" not in 結果.stderr, 結果.stderr[:300]


class Test帳本按專案分:
    """純函式分得出來不代表 CLI 分得出來——**要真的有人叫它**。

    這一格的兩條軸容易被改壞成單軸：只顧完整性就變回全域混在一起，
    只顧歸屬就把帳本寫進專案裡讓模型摸得到。三支測試各守一邊。

    斷言看的是 **CLI 自己講的落點**（`nova 帳本` 在沒有紀錄時會印出來），
    不是「有沒有真的產生檔案」——後者要先叫一次模型，那是燒 token 測接線。
    """

    def _落點(self, 專案: Path, 狀態: Path) -> str:
        return _跑("帳本", 環境={"XDG_STATE_HOME": str(狀態)}, 在=專案).stdout

    def test_在不同專案跑會指向不同目錄(self, tmp_path: Path) -> None:
        狀態 = tmp_path / "狀態"
        甲 = tmp_path / "甲"
        乙 = tmp_path / "乙"
        for 專案 in (甲, 乙):
            專案.mkdir()
        assert self._落點(甲, 狀態) != self._落點(乙, 狀態)

    def test_落點看得出是哪個專案(self, tmp_path: Path) -> None:
        """純雜湊看不出是誰的帳，而**人查得動**正是帳本存在的理由。"""
        狀態 = tmp_path / "狀態"
        專案 = tmp_path / "某個專案"
        專案.mkdir()
        assert "某個專案" in self._落點(專案, 狀態)

    def test_落點不在專案裡面(self, tmp_path: Path) -> None:
        """**歸屬換了，完整性不准跟著換掉**——落在專案裡模型就摸得到。"""
        狀態 = tmp_path / "狀態"
        專案 = tmp_path / "甲"
        專案.mkdir()
        assert str(專案.resolve()) not in self._落點(專案, 狀態)


#: 每個子命令跑得起來的最小參數。**窮舉測試要餵得出合法輸入才問得到 `執行`。**
_子命令的最小參數 = {
    "閘": ["閘", "提交"],
    "檢查指令": ["檢查指令", "ls"],
    "檢查編輯": ["檢查編輯", "--stdin"],
    "繞過": ["繞過", "--會話", "s-1", "--因為", "理由"],
    "檢查提交訊息": ["檢查提交訊息", "訊息"],
    "問": ["問", "--用", "codex", "提示"],
    "重構": ["重構", "--用", "codex", "題目"],
    "工作流": ["工作流", "任務"],
    "跑": ["跑", "任務"],
    "排程": ["排程"],
    "狀態": ["狀態"],
    "秘密": ["秘密"],
    "收件": ["收件"],
    "收": ["收"],
    "已處理": ["已處理"],
    "帳本": ["帳本"],
    "生圖": ["生圖", "描述"],
    "額度": ["額度"],
    "線": ["線"],
}


def _最小參數(名: str) -> list[str]:
    return _子命令的最小參數[名]


class Test子命令只准有一份登記來源:
    """重構抽出 `剖析器.py` 時踩到的坑，由工作流的審查階段抓出來。

    抽出去之後 `剖析器.py` 要 `set_defaults(執行=處理函式)` 就得 import
    `命令列.py` 的函式——**循環相依**。第一版的做法是在 `命令列.py` 另設一張
    `_子命令分派` 對照表繞開，於是子命令的名字有**兩份**登記：
    剖析器宣告一份、分派表寫一份。新增或改名時漏掉一邊，
    要到使用者真的打那個子命令才炸成 `KeyError`。

    正解是**依賴反轉**：剖析器宣告旗標，處理函式由呼叫端傳進來，
    在宣告的當下就 `set_defaults` 綁上去。少一格會在**建剖析器時**就炸，
    不是等到分派。
    """

    def test_每個子命令都綁得到處理函式(self) -> None:
        剖 = 建剖析器(處理們)
        for 名 in 處理們:
            參數 = 剖.parse_args(_最小參數(名))
            assert 參數.執行 is 處理們[名], 名

    def test_少一格就在建剖析器時炸(self) -> None:
        """**不准等到分派才發現。** 那時候使用者已經打完指令了。"""
        少一格 = {名: 函 for 名, 函 in 處理們.items() if 名 != "帳本"}
        with pytest.raises(KeyError, match="帳本"):
            建剖析器(少一格)

    def test_沒有第二份登記表(self) -> None:
        """名字只准出現在剖析器裡。第二份對照表就是這條 bug 的形狀。"""
        原始碼 = (專案根目錄 / "src" / "nova" / "載體" / "命令列.py").read_text(encoding="utf-8")
        assert "_子命令分派" not in 原始碼


class Test熔斷要真的改變行為:
    """純函式存在不等於熔斷存在——**沒有呼叫端的判斷只是 Evidence，不是 State**。

    `docs/設計/06` 對持久化那格的判準原話是「有沒有任何一行程式碼會因為
    帳本裡的東西改變行為」。`該跳過嗎` 剛做好時沒有任何呼叫端，
    所以那一格還是空的。

    接在哪：**建腦之前**。熔斷的意思是「不要打出去」，
    等打完再判就只是事後記錄，一點都沒省。
    """

    def test_連續失敗的家會被從接力鏈裡拿掉(self) -> None:
        鏈 = _濾掉熔斷的("agy,codex", lambda 家: 家 == "agy")
        assert 鏈 == ["codex"], 鏈

    def test_沒熔斷就原封不動(self) -> None:
        """**這支防的是擋過頭**——濾錯了會讓正常的鏈少一顆備援。"""
        assert _濾掉熔斷的("agy,codex", lambda _: False) == ["agy", "codex"]

    def test_全部都熔斷時不准濾成空的(self) -> None:
        """濾成空鏈等於「什麼都不能做」，那比讓它去撞牆更糟——

        使用者拿到的會是「至少要指定一家」這種看不懂的錯誤，
        而真正的原因（三家都連續失敗了）完全沒被講出來。
        **寧可留最後一顆讓它去試，也不要無聲地把鏈清空。**
        """
        assert _濾掉熔斷的("agy,codex", lambda _: True) == ["codex"]

    def test_建腦時真的會問熔斷(self, tmp_path: Path) -> None:
        """**接線本身要有測試**——純函式在、但沒人叫，熔斷就不存在。

        用一個「說每家都熔斷了」的假判斷：接線接上的話，
        `agy,codex` 會被濾到只剩最後一顆，腦的名稱就不再是接力鏈的形狀。
        """
        假 = tmp_path / "假CLI"
        假.touch()
        腦 = _建腦("agy,codex", 假, 不記帳本(), 熔斷了=lambda _: True)
        assert "→" not in 腦.名稱, f"還是接力鏈，代表沒問熔斷：{腦.名稱}"

    def test_預設不熔斷任何一家(self, tmp_path: Path) -> None:
        """**這支防的是預設值把熔斷寫死成開路。**"""
        假 = tmp_path / "假CLI"
        假.touch()
        腦 = _建腦("agy,codex", 假, 不記帳本())
        assert "→" in 腦.名稱, f"預設就把鏈濾掉了：{腦.名稱}"


def _寫連續失敗帳(目錄: Path, 家: str = "codex", 次數: int = 3) -> None:
    目錄.mkdir(parents=True, exist_ok=True)
    現在字串 = datetime.now(UTC).isoformat()
    for 序號 in range(次數):
        識別 = f"20260830T000{序號}00Z-失敗{序號}"
        檔 = 目錄 / f"{識別}.jsonl"
        事件們 = [
            {
                "run": 識別,
                "seq": 1,
                "ts": 現在字串,
                "event": "call_started",
                "call": 1,
                "family": 家,
            },
            {
                "run": 識別,
                "seq": 2,
                "ts": 現在字串,
                "event": "call_finished",
                "call": 1,
                "family": 家,
                "outcome": "failed",
                "input_tokens": 100,
                "output_tokens": 20,
            },
        ]
        檔.write_text(
            "".join(json.dumps(事, ensure_ascii=False) + "\n" for 事 in 事件們),
            encoding="utf-8",
        )


class Test跨執行熔斷預設關閉:
    """跨執行熔斷預設關閉：看帳跟關流程是兩件事。

    帳本要繼續記、繼續讀得到，但預設不准因為帳本裡的歷史而不去叫某一家腦；
    只有使用者明確給了 `--熔斷` 旗標時才啟用過濾。
    """

    def test_預設不熔斷就算帳本有連續失敗也照樣叫(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, 做假CLI: 做假CLI型
    ) -> None:
        """帳本只負責記與讀，不准在未明確指定 --熔斷 時自動阻擋呼叫。"""
        帳本目錄 = tmp_path / "帳"
        _寫連續失敗帳(帳本目錄, 家="codex", 次數=3)
        假_codex, 紀錄_codex = 做假CLI("codex")
        假_agy, _ = 做假CLI("agy")
        monkeypatch.setattr(
            "nova.載體.模型.轉接.找執行檔",
            lambda 家, **_: 假_codex if 家 == "codex" else 假_agy,
        )
        碼 = 主程式(["問", "--用", "codex,agy", "--帳本目錄", str(帳本目錄), "在嗎"])
        assert 碼 == 0
        assert 紀錄_codex.exists(), "預設不開熔斷時，就算帳本有連續失敗也應該呼叫 codex"

    def test_明確指定熔斷旗標時連續失敗的家會被濾掉(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, 做假CLI: 做假CLI型
    ) -> None:
        """只有在明確給了 --熔斷 時，連續失敗的家才會被熔斷濾掉並走下一家。"""
        帳本目錄 = tmp_path / "帳"
        _寫連續失敗帳(帳本目錄, 家="codex", 次數=3)
        假_codex, 紀錄_codex = 做假CLI("codex")
        假_agy, 紀錄_agy = 做假CLI("agy")
        monkeypatch.setattr(
            "nova.載體.模型.轉接.找執行檔",
            lambda 家, **_: 假_codex if 家 == "codex" else 假_agy,
        )
        碼 = 主程式(["問", "--用", "codex,agy", "--帳本目錄", str(帳本目錄), "--熔斷", "在嗎"])
        assert 碼 == 0
        assert not 紀錄_codex.exists(), "明確指定 --熔斷 時，連續失敗的 codex 應該被濾掉"
        assert 紀錄_agy.exists(), "接力鏈應該換下一顆 agy 執行"


class Test角色併接只准有一份實作:
    """`nova 重構` 走的併接，必須是 `載體.角色.組提示` 那一份。

    命令列原本自己抄了一份分隔符字面量——**同一個知識兩份實作**，
    而且沒有任何測試把兩者釘在一起：改了 `_分隔`，`nova 問` 那條路會跟著變，
    `nova 重構` 這條不會，兩條路送給模型的東西從此不一樣，而且沒人會發現。

    負控是雙向的，兩邊都跑過：把 `角色.py` 的 `_分隔` 改掉——
    併接還是兩份時**紅**（命令列沒跟上），改成共用同一份之後**綠**。
    紅那一邊證明測試守得住，綠那一邊證明命令列真的走了 `組提示`。
    """

    def test_重構送出去的提示等於組提示產出的(self, 做假CLI: 做假CLI型, tmp_path: Path) -> None:
        """直接呼叫 `主程式`，不開子程序。

        coverage 追不到子程序的行，變異閘會判成 `WRONG_TEST`——
        `#141` 踩過一次，這票又踩一次。
        """
        執行檔, 紀錄 = 做假CLI("claude")
        任務 = "把重複的併接抽掉"
        主程式(
            [
                "重構",
                "--用",
                "claude",
                "--執行檔",
                str(執行檔),
                "--不記帳",
                "--工作目錄",
                str(tmp_path),
                任務,
            ]
        )
        assert 紀錄.exists(), "假 CLI 沒被呼叫"
        送出去的 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"][-1]
        assert 送出去的 == 組提示(角色提示.重構員, 任務)

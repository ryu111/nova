"""CLI 是所有執行點（pre-commit、CI、agent hook）唯一的入口。

介面壞掉的話，三個地方會同時失去防護而且沒人發現，所以端到端跑真的執行檔。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from nova.契約.工作流 import 步驟結果, 種類, 結束, 結束代碼, 階段代碼
from nova.契約.模型回應 import 終局
from nova.契約.派工 import 工作種類
from nova.載體.命令列 import (
    _哪幾家,
    _工作流退出碼,
    _階段的工作種類,
    _階段的派法,
    放行,
    未知,
    護欄碼,
    閘紅,
    阻擋,
)
from nova.載體.派工表 import 怎麼派
from nova.迴圈.狀態機 import TDD階段表

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
    """派工表寫著「例行給 agy 分擔額度」，**但工作流從來沒讀過它**。

    實測後果（今天一整天的帳本）：

        codex   17,058,727 token
        agy        784,156 token

    22:1。因為工作流的四個階段全都用 `--用` 那一顆，而我每次都打 codex。
    **策略寫在表裡但沒有人執行，等於沒有策略**——那正是「提示裡的是懇求」。

    分法照 `工作種類` 的定義，不是我發明的：
    測試／實作／重構是「照現成樣子寫、答案對不對看得出來」＝例行；
    審查是「設計取捨、找漏洞、答案對不對要靠推理」＝推理。

    而且這個分法本身就省 codex：**多次的便宜呼叫給 agy，一次的難題給 sol。**
    """

    def test_不給用哪家時例行階段走派工表的例行(self) -> None:
        派 = 怎麼派(工作種類.例行)
        assert 派.腦們[0] == "agy", "例行第一順位不是 agy 的話這條策略就沒了"
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


class Test不給用哪家也不准自寫自評:
    """真跑才抓到的一個 `AttributeError`。

    `--用` 變成非必填之後，那道檢查 `參數.用.split(",")` 直接
    `AttributeError: 'NoneType' object has no attribute 'split'`。

    **假輸入測不到這一格**——單元測試餵的是已經填好的字串。
    這就是「墊片證明的是轉遞形狀，不是可達性」的又一次。

    而且這道檢查不能只是「不炸」：它守的是硬規則 5（不得自寫自評），
    走派工表的時候也要真的比對兩邊挑出來的家。
    """

    def test_不給旗標時檢查要拿派工表挑出來的家去比(self) -> None:
        例行 = set(_階段的派法(階段代碼.測試).腦們)
        推理 = set(_階段的派法(階段代碼.審查).腦們)
        assert not (例行 & 推理), f"派工表挑出同一家就是自寫自評：{例行 & 推理}"

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

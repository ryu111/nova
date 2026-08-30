"""使用者說的那句話：把 codex／agy／claude 做成同一個 llm cli 介面，而且真的被使用。

驗收的方式是**同一條指令換一家都跑得動、回應同形**。
用假 CLI 跑，所以不燒 token、CI 也能跑。
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

nova執行檔 = Path(sys.executable).parent / "nova"
專案根目錄 = Path(__file__).resolve().parents[2]
實錄 = 專案根目錄 / "tests" / "整合" / "實錄"

三家 = ("claude", "codex", "agy")
成功實錄 = {"claude": "claude_ok.json", "codex": "codex_ok2.jsonl", "agy": "agy_ok.json"}
失敗實錄 = {"claude": "claude_bad.txt", "codex": "codex_bad.txt", "agy": "agy_bad.txt"}

#: 走 `sys.executable` 不走 `/usr/bin/env python3`——後者在這台機器上指到系統的
#: 3.9.6，不是專案釘的 3.13。
假CLI內容 = f"""#!{sys.executable}
import os, sys, pathlib
sys.stdout.write(pathlib.Path(os.environ["假CLI_實錄"]).read_text(encoding="utf-8"))
sys.exit(int(os.environ.get("假CLI_結束碼", "0")))
"""


@pytest.fixture(scope="session")
def 假CLI(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """整個 session 一支，不是每支測試重寫一份。

    行為靠環境變數切（`假CLI_實錄`／`假CLI_結束碼`），所以內容本來就一樣。
    實測（macOS）新寫一份執行檔的第一次執行要 122 毫秒，重複執行只要 14 毫秒——
    那 100 毫秒是「剛寫出來的新執行檔」的第一次檢查，每支測試白付一次。
    """
    路徑 = tmp_path_factory.mktemp("假cli") / "假cli"
    路徑.write_text(假CLI內容, encoding="utf-8")
    路徑.chmod(路徑.stat().st_mode | stat.S_IEXEC)
    return 路徑


def _問(
    家: str, 假CLI: Path, 實錄檔: str, 結束碼: int = 0, *額外: str
) -> subprocess.CompletedProcess[str]:
    環境 = {**os.environ, "假CLI_實錄": str(實錄 / 實錄檔), "假CLI_結束碼": str(結束碼)}
    return subprocess.run(
        [str(nova執行檔), "問", "--用", 家, "--執行檔", str(假CLI), *額外, "在嗎"],
        cwd=專案根目錄,
        capture_output=True,
        text=True,
        env=環境,
        check=False,
    )


@pytest.mark.parametrize("家", 三家)
def test_同一條指令換一家都跑得動(家: str, 假CLI: Path) -> None:
    """這就是使用者那句話的驗收：介面被使用，而且三家同形。"""
    結果 = _問(家, 假CLI, 成功實錄[家])
    assert 結果.returncode == 0, 結果.stdout + 結果.stderr
    assert 結果.stdout.strip() == "ok", "stdout 只放模型講的話，才能直接 pipe 給下一個指令"


@pytest.mark.parametrize("家", 三家)
def test_三家的失敗都被分類成同一組代碼(家: str, 假CLI: Path) -> None:
    結果 = _問(家, 假CLI, 失敗實錄[家], 1)
    assert 結果.returncode != 0, "失敗一定要有非 0 的結束碼，不然腳本串不起來"
    assert "model-not-found" in 結果.stderr


@pytest.mark.parametrize("家", 三家)
def test_json輸出是結構化證據(家: str, 假CLI: Path) -> None:
    結果 = _問(家, 假CLI, 成功實錄[家], 0, "--json")
    證據 = json.loads(結果.stdout)
    assert 證據["終局"] == "success"
    assert 證據["失敗代碼"] == "none"
    assert set(證據) >= {"文字", "終局", "失敗代碼", "原始結束碼", "對話識別碼", "用量"}
    assert "成功" not in 證據, "任務成敗不由這層給"
    assert "執行成功" not in 證據, "布林會把『結果未知』壓成『確定失敗』"


def test_成本只有claude給其餘是空的(假CLI: Path) -> None:
    """不對稱能力降級成 Optional，不准為了對稱去估算。"""
    claude證據 = json.loads(_問("claude", 假CLI, 成功實錄["claude"], 0, "--json").stdout)
    codex證據 = json.loads(_問("codex", 假CLI, 成功實錄["codex"], 0, "--json").stdout)
    assert claude證據["用量"]["成本美金"] is not None
    assert codex證據["用量"]["成本美金"] is None


@pytest.mark.parametrize("家", 三家)
def test_確定失敗的退出碼是1(家: str, 假CLI: Path) -> None:
    """模型不存在＝請求沒出門＝確定失敗，重跑是安全的。"""
    結果 = _問(家, 假CLI, 失敗實錄[家], 1)
    assert 結果.returncode == 1
    assert "確定失敗" in 結果.stderr


@pytest.mark.parametrize("家", 三家)
def test_結果未知的退出碼是3而不是1(家: str, 假CLI: Path) -> None:
    """輸出解析不出來時我們不知道工作做了沒——腳本必須分得出來，才不會盲目重跑。

    `agy` issue #76 就是這種：stdout 全空但結束碼 0。
    """
    結果 = _問(家, 假CLI, "README.md", 0)
    assert 結果.returncode == 3, "結果未知不能跟確定失敗共用退出碼"
    assert "不准自動重跑" in 結果.stderr


def test_不認得的家要當場報錯(假CLI: Path) -> None:
    結果 = _問("不存在的家", 假CLI, "claude_ok.json")
    assert 結果.returncode != 0
    assert "不存在的家" in 結果.stderr


def test_工作流有token預算這個旋鈕() -> None:
    """成本上限要在命令列上看得見——藏在程式碼裡的預設值，使用者沒辦法調。

    行為本身由 `tests/整合/test_門面.py::test_預算用完就一步都不准跑` 背書；
    這裡只守「這個旋鈕沒有在某次重構裡消失」。
    """
    結果 = subprocess.run(
        [str(nova執行檔), "工作流", "--help"],
        cwd=專案根目錄,
        capture_output=True,
        text=True,
        check=False,
    )
    assert 結果.returncode == 0
    assert "--最多token" in 結果.stdout


class Test工作流的換腦保證:
    """自己審自己等於沒審——硬規則 4。判準是**對話**不是家族名（`#140`）。

    家族名重疊不再被擋：三家不給續接時本來就都是新對話（codex `--ephemeral`、
    claude 不給 `--resume`、agy 不給 `--conversation`），新對話看不到做事那邊的
    推理過程。真正要擋的自寫自評是跑在同一個對話裡，而那在結構上不可能——
    精確定義由 `tests/單元/test_換腦判準.py` 守。

    這一格守的是**真執行檔、真 argv 走得通**：同一家不再停在門口，
    而是一路走到停止規則（判準三：墊片測得出轉遞形狀，測不出可達性）。
    """

    def test_同一家不再擋在門口(self, 假CLI: Path) -> None:
        """走到護欄才停（退出碼 4），不是停在參數檢查（退出碼 2）。

        `--最多步數 0` 讓迴圈一步都不跑（`range(0)` 是空迴圈），所以這一格
        證明「檢查放行了」而**不燒任何 token**；假 CLI 是第二層保險——
        步數旗標哪天接錯了也打不到真模型。這個檔案的前提就是不燒 token，
        原本這兩格是唯二沒帶 `--執行檔` 的，只因為門口擋著才沒露餡。
        """
        環境 = {
            **os.environ,
            "假CLI_實錄": str(實錄 / 成功實錄["codex"]),
            "假CLI_結束碼": "0",
        }
        結果 = subprocess.run(
            [
                str(nova執行檔),
                "工作流",
                "--用",
                "codex",
                "--審查用",
                "codex",
                "--執行檔",
                str(假CLI),
                "--最多步數",
                "0",
                "--不記帳",
                "任務",
            ],
            cwd=專案根目錄,
            capture_output=True,
            text=True,
            env=環境,
            check=False,
        )
        assert 結果.returncode == 4, 結果.stderr
        assert "換一顆腦" not in 結果.stderr

    def test_審查用這個旋鈕沒有消失(self) -> None:
        """使用者要能指名審查家——這個旋鈕不准在某次重構裡消失。

        原本這一格叫「審查用是必要參數」，斷言 `"審查用" in stderr`——**那是假綠**：
        `--審查用` 從來不是 required（不給就走派工表），它會綠是因為**另一條規則**
        的錯誤訊息「…同時出現在 --用 與 --審查用」剛好含這三個字。
        子字串斷言撞上別條規則的訊息就會這樣，而且拆掉那條規則才會現形。
        """
        結果 = subprocess.run(
            [str(nova執行檔), "工作流", "--help"],
            cwd=專案根目錄,
            capture_output=True,
            text=True,
            check=False,
        )
        assert 結果.returncode == 0
        assert "--審查用" in 結果.stdout

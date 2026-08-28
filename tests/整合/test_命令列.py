"""CLI 是所有執行點（pre-commit、CI、agent hook）唯一的入口。

介面壞掉的話，三個地方會同時失去防護而且沒人發現，所以端到端跑真的執行檔。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

nova執行檔 = Path(sys.executable).parent / "nova"
專案根目錄 = Path(__file__).resolve().parent.parent.parent


def _跑(*參數: str, 輸入: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=專案根目錄,
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

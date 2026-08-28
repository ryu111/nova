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

假CLI內容 = """#!/usr/bin/env python3
import os, sys, pathlib
sys.stdout.write(pathlib.Path(os.environ["假CLI_實錄"]).read_text(encoding="utf-8"))
sys.exit(int(os.environ.get("假CLI_結束碼", "0")))
"""


@pytest.fixture
def 假CLI(tmp_path: Path) -> Path:
    路徑 = tmp_path / "假cli"
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

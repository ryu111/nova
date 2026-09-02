"""測試階收尾機械格式化：測試員寫完測試檔後自動整理排版。

## 這支釘的是哪個洞

測試員段未要求整理 lint/format，寫完測試若排版不符合規範或含有可自動修復的 safe fix，
會導致 `驗證綠` 提交閘（ruff-format / ruff check）紅掉，
而實作員被禁止修改測試檔，進而造成流程在實作階陷入死局或撞護欄。
機械排版問題必須在測試階結束時立即修復並格式化消掉。

## 這支怎麼接線

門面（`nova.派工`）與命令列（`nova 跑`）兩大入口都需注入測試檔整理器。
測試階段動過哪幾個 `tests/` 檔由快照偵測出來，
在測試階結束、進入護欄判斷與下一步之前，
呼叫注入的測試檔整理器（先跑 ruff check --fix 再跑 ruff format）。
"""

import subprocess
import sys
from pathlib import Path

import pytest

import nova
from nova.載體.命令列 import 主程式

_ruff = Path(sys.executable).parent / "ruff"
專案根目錄 = Path(__file__).resolve().parent.parent.parent
實錄目錄 = Path(__file__).resolve().parent / "實錄"


@pytest.fixture
def 寫壞測試的假CLI(tmp_path: Path) -> Path:
    """模擬測試員寫出含有未用 import（待 safe fix）且排版不良的測試檔。"""
    實錄 = 實錄目錄 / "claude_ok.json"
    腳本 = tmp_path / "fake-claude-tester"
    腳本.write_text(
        f"""#!{sys.executable}
import pathlib, sys

# 測試員在工作目錄下寫出排版壞掉且有未用 import 的測試檔
目標 = pathlib.Path("tests/test_排版壞掉.py")
目標.parent.mkdir(parents=True, exist_ok=True)
目標.write_text('''import os
import sys

def 相加(甲: int, 乙: int) -> int:
    return 甲 + 乙

def test_新寫的(  )   ->   None:
    assert   相加( 1,   2 )  ==  3
''', encoding="utf-8")

sys.stdout.write(pathlib.Path({str(實錄)!r}).read_text(encoding="utf-8"))
""",
        encoding="utf-8",
    )
    腳本.chmod(0o755)
    return 腳本


@pytest.mark.skipif(not _ruff.exists(), reason="這個 venv 裡沒有 ruff")
def test_排版壞掉且含待修項的測試檔跑完測試階會被整理(
    tmp_path: Path, 寫壞測試的假CLI: Path
) -> None:
    """守住透過門面派工時，測試階產出的排版違規與待修 lint 測試檔會在收尾時自動修復並格式化。"""
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    (工作區 / "tests").mkdir()
    (工作區 / "pyproject.toml").write_text(
        (專案根目錄 / "pyproject.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    測試檔 = 工作區 / "tests" / "test_排版壞掉.py"

    nova.派工(
        "寫測試",
        用="claude",
        審查用="claude",
        工作目錄=工作區,
        最多步數=1,
        執行檔=寫壞測試的假CLI,
        審查執行檔=寫壞測試的假CLI,
        判準指令=["true"],
        帳本目錄=tmp_path / "帳",
    )

    assert 測試檔.exists(), "測試員應該寫出測試檔"

    # 1. 驗證 safe fix（如 F401 未用 import）已被修復
    assert "import os" not in 測試檔.read_text(encoding="utf-8"), (
        "未用 import 應在收尾被 safe fix 移除"
    )

    檢查結果 = subprocess.run(
        [str(_ruff), "check", "--no-cache", "tests/test_排版壞掉.py"],
        cwd=工作區,
        capture_output=True,
        text=True,
        check=False,
    )
    assert 檢查結果.returncode == 0, (
        f"測試階結束後，測試檔的 safe fix 應該已被修復，但 ruff check 失敗：\n"
        f"{檢查結果.stderr or 檢查結果.stdout}"
    )

    # 2. 驗證測試檔已經被 ruff format 整理好（需在 fix 之後執行 format 才能乾淨）
    排版結果 = subprocess.run(
        [str(_ruff), "format", "--check", "--no-cache", "tests/test_排版壞掉.py"],
        cwd=工作區,
        capture_output=True,
        text=True,
        check=False,
    )
    assert 排版結果.returncode == 0, (
        f"測試階結束後，測試檔應該已被自動格式化，但 ruff format --check 失敗：\n"
        f"{排版結果.stderr or 排版結果.stdout}"
    )


@pytest.mark.skipif(not _ruff.exists(), reason="這個 venv 裡沒有 ruff")
def test_命令列跑入口也會對測試階動過的測試檔整理排版(
    tmp_path: Path, 寫壞測試的假CLI: Path
) -> None:
    """守住命令列 nova 跑 入口在測試階結束後也會整理動過的測試檔。"""
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    (工作區 / "tests").mkdir()
    (工作區 / "pyproject.toml").write_text(
        (專案根目錄 / "pyproject.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    測試檔 = 工作區 / "tests" / "test_排版壞掉.py"

    退出碼 = 主程式(
        [
            "跑",
            "寫測試",
            "--用",
            "claude",
            "--審查用",
            "claude",
            "--執行檔",
            str(寫壞測試的假CLI),
            "--工作目錄",
            str(工作區),
            "--最多步數",
            "1",
            "--判準",
            "true",
            "--不記帳",
        ]
    )
    assert 退出碼 == 4, "撞到最多步數 1 應回傳護欄碼 4"

    assert 測試檔.exists(), "測試員應該寫出測試檔"

    # 驗證測試檔已被自動格式化
    排版結果 = subprocess.run(
        [str(_ruff), "format", "--check", "--no-cache", "tests/test_排版壞掉.py"],
        cwd=工作區,
        capture_output=True,
        text=True,
        check=False,
    )
    assert 排版結果.returncode == 0, (
        f"命令列跑完測試階後，測試檔應該已被自動格式化，但 ruff format --check 失敗：\n"
        f"{排版結果.stderr or 排版結果.stdout}"
    )

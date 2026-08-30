"""閘紅落成收件票的整合測試。

會 fork 子程序執行真實的 nova CLI，驗證在不同情境下的落票行為。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from nova.載體.收件 import 待處理, 收件目錄

nova執行檔 = Path(sys.executable).parent / "nova"


def _跑nova(
    *參數: str,
    在: Path,
    環境: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env=None if 環境 is None else {**os.environ, **環境},
        capture_output=True,
        text=True,
        check=False,
    )


def _建git倉庫(路徑: Path, 分支: str = "main") -> None:
    subprocess.run(["git", "init", "-b", 分支], cwd=路徑, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "測試員"], cwd=路徑, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@nova.local"],
        cwd=路徑,
        check=True,
        capture_output=True,
    )


@pytest.mark.serial
def test_main上排程執行閘紅自動落成收件票(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    專案 = tmp_path / "專案"
    專案.mkdir()
    _建git倉庫(專案, "main")

    狀態根 = tmp_path / "狀態"
    狀態根.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(狀態根))
    環境 = {"XDG_STATE_HOME": str(狀態根)}

    # 製造一個會讓 lang-traditional 紅的檔案
    壞檔 = 專案 / "壞.py"
    壞檔.write_text("# 简体中文\n", encoding="utf-8")  # nova:允許非繁體
    subprocess.run(["git", "add", "."], cwd=專案, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "第一版"], cwd=專案, check=True, capture_output=True)

    # 執行 nova 閘 提交 --喚醒來源 schedule
    結果 = _跑nova("閘", "提交", "--喚醒來源", "schedule", 在=專案, 環境=環境)
    assert 結果.returncode != 0
    assert "lang-traditional" in 結果.stdout

    目錄 = 收件目錄(專案)
    票們 = 待處理(目錄)
    assert len(票們) == 1
    票內容 = 票們[0].read_text(encoding="utf-8")
    assert "# 閘紅：lang-traditional" in 票內容
    assert "- 分支：main" in 票內容
    assert "## 紅在哪" in 票內容


@pytest.mark.serial
def test_手動跑閘紅了不准落成收件票(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    專案 = tmp_path / "專案"
    專案.mkdir()
    _建git倉庫(專案, "main")

    狀態根 = tmp_path / "狀態"
    狀態根.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(狀態根))
    環境 = {"XDG_STATE_HOME": str(狀態根)}

    壞檔 = 專案 / "壞.py"
    壞檔.write_text("# 简体中文\n", encoding="utf-8")  # nova:允許非繁體
    subprocess.run(["git", "add", "."], cwd=專案, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "第一版"], cwd=專案, check=True, capture_output=True)

    # 手動跑閘（預設喚醒來源 manual）
    結果 = _跑nova("閘", "提交", 在=專案, 環境=環境)
    assert 結果.returncode != 0

    目錄 = 收件目錄(專案)
    assert 待處理(目錄) == []


@pytest.mark.serial
def test_開發分支上排程跑閘紅了不准落成收件票(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    專案 = tmp_path / "專案"
    專案.mkdir()
    _建git倉庫(專案, "feat-tdd")

    狀態根 = tmp_path / "狀態"
    狀態根.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(狀態根))
    環境 = {"XDG_STATE_HOME": str(狀態根)}

    壞檔 = 專案 / "壞.py"
    壞檔.write_text("# 简体中文\n", encoding="utf-8")  # nova:允許非繁體
    subprocess.run(["git", "add", "."], cwd=專案, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "第一版"], cwd=專案, check=True, capture_output=True)

    # 開發分支上排程跑閘
    結果 = _跑nova("閘", "提交", "--喚醒來源", "schedule", 在=專案, 環境=環境)
    assert 結果.returncode != 0

    目錄 = 收件目錄(專案)
    assert 待處理(目錄) == []


@pytest.mark.serial
def test_重複排程跑閘不重複落票(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    專案 = tmp_path / "專案"
    專案.mkdir()
    _建git倉庫(專案, "main")

    狀態根 = tmp_path / "狀態"
    狀態根.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(狀態根))
    環境 = {"XDG_STATE_HOME": str(狀態根)}

    壞檔 = 專案 / "壞.py"
    壞檔.write_text("# 简体中文\n", encoding="utf-8")  # nova:允許非繁體
    subprocess.run(["git", "add", "."], cwd=專案, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "第一版"], cwd=專案, check=True, capture_output=True)

    # 第一次排程跑閘
    結果1 = _跑nova("閘", "提交", "--喚醒來源", "schedule", 在=專案, 環境=環境)
    assert 結果1.returncode != 0
    目錄 = 收件目錄(專案)
    assert len(待處理(目錄)) == 1

    # 第二次排程跑閘
    結果2 = _跑nova("閘", "提交", "--喚醒來源", "schedule", 在=專案, 環境=環境)
    assert 結果2.returncode != 0
    assert len(待處理(目錄)) == 1

"""`nova 線` 的唯讀看板整合測試。

**直接呼叫 `主程式`，不開子程序**：coverage 追不到子程序的行，
變異閘會判成 `WRONG_TEST：沒覆蓋`（`#141` 實測踩過同一個坑）。
底下的 `git` 子程序是**建測試資料**，不是被測對象，所以留著。
"""

import subprocess
from pathlib import Path

import pytest

from nova.載體 import 命令列


def _做一個乾淨的工作樹(專案: Path) -> None:
    專案.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=專案, check=True)
    (專案 / "README.md").write_text("測試用工作樹\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=專案, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=測試",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "初始化",
        ],
        cwd=專案,
        check=True,
    )


def test_沒有成果帳本時上一次怎麼收要誠實說查不到(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """沒有成果帳本時，不准把缺資料編成「成功」或退出碼 0。"""
    專案 = tmp_path / "某條線"
    _做一個乾淨的工作樹(專案)

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "狀態"))
    monkeypatch.chdir(專案)
    碼 = 命令列.主程式(["--根目錄", str(專案), "線"])

    輸出 = capsys.readouterr()
    合起來 = 輸出.out + 輸出.err
    assert 碼 == 0, 合起來
    收場欄 = next(行 for 行 in 輸出.out.splitlines() if "上一次怎麼收的" in 行)
    assert "查不到" in 收場欄, 輸出.out
    assert "成功" not in 收場欄, 收場欄
    assert "退出碼 0" not in 收場欄, 收場欄

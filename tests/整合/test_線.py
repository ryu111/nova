"""`nova 線` 的唯讀看板整合測試。"""

import os
import subprocess
import sys
from pathlib import Path

nova執行檔 = Path(sys.executable).parent / "nova"


def test_沒有成果帳本時上一次怎麼收要誠實說查不到(tmp_path: Path) -> None:
    """沒有成果帳本時，不准把缺資料編成「成功」或退出碼 0。"""
    專案 = tmp_path / "某條線"
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

    結果 = subprocess.run(
        [str(nova執行檔), "--根目錄", str(專案), "線"],
        cwd=專案,
        env={**os.environ, "XDG_STATE_HOME": str(tmp_path / "狀態")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert 結果.returncode == 0, 結果.stdout + 結果.stderr
    收場欄 = next(行 for 行 in 結果.stdout.splitlines() if "上一次怎麼收的" in 行)
    assert "查不到" in 收場欄, 結果.stdout
    assert "成功" not in 收場欄, 收場欄
    assert "退出碼 0" not in 收場欄, 收場欄

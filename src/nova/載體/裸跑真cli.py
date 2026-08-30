"""「這支測試會打到真的 CLI」的機械判準。

判準是跑出來的不是讀出來的：用一個只含空目錄的 `PATH` 把測試再跑一次，
真的要 exec `codex`／`claude`／`agy` 的那些會炸 `FileNotFoundError`，
而給了 `--執行檔`／假 CLI／monkeypatch 換掉腦的不靠 `PATH`，照樣綠。
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

#: 帶這兩個標記的測試本來就該打真的外部 CLI／端點，
#: 在空 `PATH` 下 exec 不到執行檔是預期結果，不是嫌疑。
排除本來就該打真外部的 = "not 真cli and not 真端點"


def _在空PATH下跑一次(根目錄: Path) -> str:
    """在一個 exec 不到任何執行檔的環境裡跑全測試，回傳 pytest 的 stdout。"""
    with tempfile.TemporaryDirectory() as 空目錄:
        結果 = subprocess.run(  # noqa: S603 —— 指令由這裡寫死，只有目錄是外面給的
            [
                sys.executable,
                "-m",
                "pytest",
                str(根目錄),
                "-p",
                "no:cacheprovider",
                "-q",
                "--tb=no",
                "-rf",  # 只要失敗的短摘要：判準要的是「哪一支、炸在什麼」
                "-m",
                排除本來就該打真外部的,
            ],
            cwd=根目錄,
            env={**os.environ, "PATH": 空目錄},
            capture_output=True,
            text=True,
            check=False,
        )
    return 結果.stdout


def _挑出exec不到執行檔的(pytest輸出: str) -> list[str]:
    """從 `-rf` 的失敗摘要裡挑出炸在 `FileNotFoundError` 的那幾行。"""
    return [
        行
        for 行 in pytest輸出.splitlines()
        if 行.startswith("FAILED") and "FileNotFoundError" in 行
    ]


def 檢查裸跑真cli(根目錄: Path) -> tuple[bool, str]:
    """用空 `PATH` 跑一次全測試，指名會 exec 到真 CLI 的那幾支。回傳 (放行, 證據)。"""
    嫌疑 = _挑出exec不到執行檔的(_在空PATH下跑一次(根目錄))
    if not 嫌疑:
        return True, ""
    return False, "空 PATH 下 exec 不到執行檔，代表這幾支打的是真 CLI：\n" + "\n".join(嫌疑)

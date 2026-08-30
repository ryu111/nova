"""阿姆達爾定律門禁：serial 測試佔比不可超過門檻。

業界實測：serial 測試若沒有門禁，每季自然增長 15~25%。
而阿姆達爾定律鎖死平行加速比——10% 的測試是 serial，再多核心也快不過總時間的十分之一。
nova 現在 serial 6 支、全部約 930 支（0.6%），門檻抓 8% 留很大餘裕，
守的是「有沒有人在看」，不是現在的數字。
"""

import os
import subprocess
import sys
from pathlib import Path

from nova.載體.程序 import 具名啟動

預設門檻 = 0.08


def 判定serial佔比(serial數: int, 總測試數: int, *, 門檻: float = 預設門檻) -> tuple[bool, str]:
    """判定 serial 測試比例是否合乎門檻。回傳 (通過, 證據)。"""
    if 總測試數 == 0:
        return True, "沒有測試"
    佔比 = serial數 / 總測試數
    if 佔比 > 門檻:
        return False, (
            f"serial 測試有 {serial數} 支，佔全體 {總測試數} 支的 {佔比:.1%}（門檻 {門檻:.1%}）。"
            "超過門檻不是調高門檻，是把那些測試的共享狀態拆掉"
        )
    return (
        True,
        f"serial 測試有 {serial數} 支，佔全體 {總測試數} 支的 {佔比:.1%}（門檻 {門檻:.1%}）",
    )


def _數collect測試(根目錄: Path, *參數: str) -> int:
    """透過 pytest --collect-only 數出符合條件的測試數。"""
    工具目錄 = Path(sys.executable).parent
    執行檔 = 工具目錄 / "pytest"
    指令 = [
        "pytest",
        *參數,
        "--collect-only",
        "-q",
        "-p",
        "no:randomly",
    ]
    完整, 角色標記 = 具名啟動(執行檔 if 執行檔.exists() else Path("pytest"), 指令[1:])
    結果 = subprocess.run(  # noqa: S603 —— 指令由內部指定，不吃外部輸入
        完整,
        cwd=根目錄,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "APP_ROLE": 角色標記},
    )
    if 結果.returncode not in (0, 5):  # 5 是 pytest 的 no tests collected
        return 0
    return sum(1 for 行 in 結果.stdout.splitlines() if "::" in 行)


def 檢查serial佔比(根目錄: Path, *, 門檻: float = 預設門檻) -> tuple[bool, str]:
    """比對 repo 內的 serial 測試數與全部測試數。回傳 (放行, 證據)。"""
    總數 = _數collect測試(根目錄)
    serial數 = _數collect測試(根目錄, "-m", "serial and not 真cli")
    return 判定serial佔比(serial數, 總數, 門檻=門檻)

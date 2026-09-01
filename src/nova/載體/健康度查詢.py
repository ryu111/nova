"""查健康度閘需要的四個現場指標。

這裡只查資料，不決定綠或紅；`健康度.py` 收到完整指標後才做二元判定。
每一項查不到就回 `None`，讓閘採安全側停止自主推進。
"""

import json
import subprocess
from pathlib import Path

from nova.載體.健康度 import 健康度指標
from nova.載體.收件 import 卡住的, 收件目錄
from nova.載體.線 import 查並行現況


def 查健康度指標(專案: Path) -> 健康度指標:
    """查出四個指標；個別查不到時保留該欄的 `None`。"""
    return 健康度指標(
        main綠嗎=_查main的CI(專案),
        卡住的線數=_查卡住的線數(專案),
        沒收尾的件數=_查沒收尾的件數(專案),
        壞掉的PR數=_查壞掉的PR數(專案),
    )


def _查main的CI(專案: Path) -> bool | None:
    """只看 main 最新一筆已完成的 CI；沒有結果或仍在跑就是查不到。"""
    結果 = _跑gh(
        專案,
        "run",
        "list",
        "--branch",
        "main",
        "--json",
        "status,conclusion",
        "--limit",
        "1",
    )
    if 結果 is None:
        return None
    try:
        runs = json.loads(結果)
    except (TypeError, ValueError):
        return None
    if not isinstance(runs, list) or not runs or not isinstance(runs[0], dict):
        return None
    status = runs[0].get("status")
    conclusion = runs[0].get("conclusion")
    if status != "completed" or not isinstance(conclusion, str):
        return None
    return conclusion == "success"


def _查卡住的線數(專案: Path) -> int | None:
    """把現有查詢回報「在跑」的線數當作目前佔住的線數。"""
    try:
        線們 = 查並行現況(專案)
    except (OSError, ValueError):
        return None
    if any(一條.在跑嗎 is None for 一條 in 線們):
        return None
    return sum(一條.在跑嗎 is True for 一條 in 線們)


def _查沒收尾的件數(專案: Path) -> int | None:
    """沿用收件匣既有的 30 分鐘查詢；有讀不動的檔就無法知道總數。"""
    try:
        清單 = 卡住的(收件目錄(專案))
    except (OSError, ValueError):
        return None
    return None if 清單.跳過幾個 else len(清單)


def _查壞掉的PR數(專案: Path) -> int | None:
    """數開啟 PR 中 CI 失敗或有合併衝突的那些。"""
    結果 = _跑gh(專案, "pr", "list", "--json", "mergeStateStatus")
    if 結果 is None:
        return None
    try:
        PR們 = json.loads(結果)
    except (TypeError, ValueError):
        return None
    if not isinstance(PR們, list):
        return None

    #: `DIRTY` 是衝突，`BLOCKED`／`UNSTABLE` 是保護檢查或 CI 沒過。
    壞掉的狀態 = {"DIRTY", "BLOCKED", "UNSTABLE"}
    可判定的狀態 = 壞掉的狀態 | {"CLEAN", "BEHIND", "DRAFT"}
    數量 = 0
    for PR in PR們:
        if not isinstance(PR, dict) or not isinstance(PR.get("mergeStateStatus"), str):
            return None
        狀態 = PR["mergeStateStatus"]
        if 狀態 not in 可判定的狀態:
            return None
        數量 += 狀態 in 壞掉的狀態
    return 數量


def _跑gh(專案: Path, *參數: str) -> str | None:
    """跑唯讀 gh 查詢；工具不可用、非零或無輸出都算查不到。"""
    try:
        結果 = subprocess.run(  # noqa: S603, S607 —— 指令由這裡固定，只讀 gh 查詢
            ["gh", *參數],  # noqa: S607
            cwd=專案,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if 結果.returncode != 0:
        return None
    return 結果.stdout

"""nova 收子命令：確定性收尾閉包（閘 → commit → push → PR → required CI → merge）。"""

import argparse
import subprocess
import sys
from pathlib import Path

from nova.契約.退出碼 import 放行, 未知, 閘紅
from nova.載體.規則表 import 建規則表
from nova.載體.閘 import 跑閘

__all__ = [
    "子命令_收",
    "_收尾閘",
    "_跑並印收尾指令",
    "_跑收尾指令",
]


def _跑收尾指令(根目錄: Path, *指令: str, 逾時秒: float | None = None) -> tuple[int, str]:
    """在專案裡跑一個收尾指令，回傳 nova 退出碼與輸出。"""
    try:
        結果 = subprocess.run(  # noqa: S603 —— 收尾指令由這個節點固定組出
            list(指令),
            cwd=根目錄,
            capture_output=True,
            text=True,
            check=False,
            timeout=逾時秒,
        )
    except subprocess.TimeoutExpired:
        return 未知, f"指令等不到結果（{' '.join(指令)}）"
    except OSError as 錯:
        return 閘紅, f"指令跑不起來（{' '.join(指令)}）：{錯}"
    輸出 = (結果.stdout + 結果.stderr).strip()
    if 結果.returncode:
        return 閘紅, 輸出 or f"指令退出碼 {結果.returncode}：{' '.join(指令)}"
    return 放行, 輸出


def _跑並印收尾指令(根目錄: Path, *指令: str, 逾時秒: float | None = None) -> int:
    """跑一個收尾指令並印出它的輸出。"""
    碼, 輸出 = _跑收尾指令(根目錄, *指令, 逾時秒=逾時秒)
    if 輸出:
        sys.stdout.write(f"{輸出}\n")
    return 碼


def _收尾閘(參數: argparse.Namespace, 根目錄: Path) -> int:
    """只跑提交閘；閘紅時不碰 git 與 gh。"""
    from nova.載體 import 命令列  # noqa: PLC0415 —— 延遲匯入避免循環依賴

    try:
        with 命令列._開帳(參數) as 帳:  # noqa: SLF001 —— 借用命令列共用開帳
            結果表 = 跑閘("提交", 建規則表(根目錄), 提前停止=True, 帳=帳)
    except (OSError, ValueError) as 錯:
        sys.stderr.write(f"{錯}\n")
        return 閘紅
    return 命令列._印結果(結果表)  # noqa: SLF001 —— 借用命令列共用印結果


def 子命令_收(參數: argparse.Namespace) -> int:
    """確定性收尾：閘 → commit → push → PR → required CI → merge。"""
    from nova.載體 import 命令列  # noqa: PLC0415 —— 延遲匯入避免循環依賴

    根 = 命令列._專案脈絡(參數).根目錄  # noqa: SLF001 —— 借用命令列共用專案脈絡
    if (碼 := _收尾閘(參數, 根)) != 放行:
        return 碼

    訊息 = 參數.訊息 or " ".join(參數.提交訊息) or "nova：收尾"
    for 指令 in (
        ("git", "add", "-A"),
        ("git", "commit", "-m", 訊息),
        ("git", "push", "--set-upstream", "origin", "HEAD"),
        ("gh", "pr", "create", "--title", 訊息, "--body", 訊息),
    ):
        if (碼 := _跑並印收尾指令(根, *指令)) != 放行:
            return 碼

    if (
        碼 := _跑並印收尾指令(根, "gh", "pr", "checks", "--required", "--watch", 逾時秒=參數.等CI秒)
    ) != 放行:
        return 碼

    _, 頭分支 = _跑收尾指令(根, "git", "branch", "--show-current")
    頭分支 = 頭分支.strip()

    if (碼 := _合併這個PR(根)) != 放行:
        return 碼

    return _查證本地分支已刪(根, 頭分支)


def _合併這個PR(根目錄: Path) -> int:
    """既有政策：squash 合併並刪遠端分支，絕不帶 `--admin`。"""
    return _跑並印收尾指令(
        根目錄,
        "gh",
        "pr",
        "merge",
        "--squash",
        "--delete-branch",
    )


def _查證本地分支已刪(根目錄: Path, 頭分支: str) -> int:
    """`gh pr merge` 回 0 只代表 GitHub 那端；本地分支還在就是沒收乾淨。"""
    if not 頭分支:
        return 放行
    _, 殘留 = _跑收尾指令(根目錄, "git", "branch", "--list", 頭分支)
    if not 殘留.strip():
        return 放行
    sys.stderr.write(
        f"GitHub 已合併這個 PR，但本地分支 {頭分支} 沒刪乾淨（多半還被某棵 worktree 佔著）。\n"
        f"不要再跑一次 merge；先清掉佔用它的 worktree，再刪本地分支 {頭分支}。\n"
    )
    return 閘紅

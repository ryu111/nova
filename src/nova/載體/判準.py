"""機械判準：跑一條指令，看它綠不綠。

**不是模型。** 硬規則 4 禁止同一個模型自寫自評；驗收權不在執行者手上。
判準只有一個判斷依據：退出碼。模型講什麼都不算數。
"""

import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path

from nova.契約.工作流 import 任務, 判準

#: TDD 內圈的判準就是測試本身。
預設判準指令 = ("uv", "run", "pytest", "-q")
_證據上限 = 4000


def 建判準(指令: Sequence[str] = 預設判準指令, *, 逾時秒: float = 600.0) -> 判準:
    """做一個判準：在任務的工作目錄跑這條指令，退出碼 0 就是綠。

    指令是**選填**（有真正的預設值）。逾時當紅處理——判準跑不完就是沒通過，
    不能因為「不知道」而放行（fail-closed）。
    """

    def 跑(任: 任務) -> tuple[bool, str]:
        try:
            結果 = subprocess.run(  # noqa: S603 —— 指令由呼叫端明確給定
                list(指令),
                cwd=任.工作目錄,
                capture_output=True,
                text=True,
                timeout=逾時秒,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, f"判準超過 {逾時秒} 秒沒跑完（當紅處理）"
        except FileNotFoundError as 錯:
            return False, f"判準指令跑不起來：{錯}"
        輸出 = (結果.stdout + 結果.stderr).strip()
        return 結果.returncode == 0, 輸出[-_證據上限:]

    return 跑


def 判準指令(文字: str | None) -> tuple[str, ...]:
    """把使用者給的字串切成指令。沒給就用預設。"""
    if not 文字 or not 文字.strip():
        return 預設判準指令
    return tuple(shlex.split(文字))


def 在哪跑(工作目錄: str | None) -> Path:
    """判準與角色共用的工作目錄。沒給就是現在這個目錄。"""
    return Path(工作目錄).resolve() if 工作目錄 else Path.cwd()

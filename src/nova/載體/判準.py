"""機械判準：跑一條指令，看它綠不綠。

**不是模型。** 硬規則 4 禁止同一個模型自寫自評；驗收權不在執行者手上。
判準只有一個判斷依據：退出碼。模型講什麼都不算數。
"""

import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path

from nova.契約.工作流 import 任務, 判準, 判準終局

#: TDD 內圈的判準就是測試本身。
預設判準指令 = ("uv", "run", "pytest", "-q")
_證據上限 = 4000


def 建判準(指令: Sequence[str] = 預設判準指令, *, 逾時秒: float = 600.0) -> 判準:
    """做一個判準：在任務的工作目錄跑這條指令，退出碼 0 就是綠。

    指令是**選填**（有真正的預設值）。逾時當紅處理——判準跑不完就是沒通過，
    不能因為「不知道」而放行（fail-closed）。
    """

    def 跑(任: 任務) -> tuple[判準終局, str]:
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
            # **逾時刻意留在「紅」。** 它分不出是環境壞了還是測試真的卡住，
            # fail-closed 當紅是既有的決定；卡住偵測器會在第 3 次擋下來。
            return 判準終局.紅, f"判準超過 {逾時秒} 秒沒跑完（當紅處理）"
        except OSError as 錯:
            # **跑不起來不是紅。** 指令不存在、沒有執行權限、路徑不是目錄——
            # 那是環境（診斷順序第一條），重跑一百次還是同一個環境。
            # 當紅回報的話工作流會回去「再實作一次」，而實作要叫模型。
            # 實測 2026-08-30：launchd 的 PATH 沒有 uv，單次燒掉 997,031 token。
            return 判準終局.跑不起來, f"判準指令跑不起來（環境問題，不是測試沒過）：{錯}"
        輸出 = (結果.stdout + 結果.stderr).strip()
        收場 = 判準終局.綠 if 結果.returncode == 0 else 判準終局.紅
        return 收場, 輸出[-_證據上限:]

    return 跑


def 判準指令(文字: str | None) -> tuple[str, ...]:
    """把使用者給的字串切成指令。沒給就用預設。"""
    if not 文字 or not 文字.strip():
        return 預設判準指令
    return tuple(shlex.split(文字))


def 在哪跑(工作目錄: str | None) -> Path:
    """判準與角色共用的工作目錄。沒給就是現在這個目錄。"""
    return Path(工作目錄).resolve() if 工作目錄 else Path.cwd()

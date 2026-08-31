"""機械判準：跑一條指令，看它綠不綠。

**不是模型。** 硬規則 4 禁止同一個模型自寫自評；驗收權不在執行者手上。
判準只有一個判斷依據：退出碼。模型講什麼都不算數。
"""

import shlex
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from nova.契約.工作流 import 任務, 判準, 判準終局
from nova.載體.閘鎖 import 佔不到, 佔住

#: TDD 內圈的判準就是測試本身。
預設判準指令 = ("uv", "run", "pytest", "-q")
_證據上限 = 4000

#: **跟 `nova 閘` 同一把鎖。** 判準跟閘搶的是同一份 CPU，各拿各的話兩邊照樣
#: 同時跑滿，卻長得像有鎖。名稱一致是「同一把」的唯一依據。
_機器鎖名稱 = "閘"

#: pytest 自己的退出碼裡，**「根本沒驗到」**的那兩個。
#:
#: 原本的分界線劃在「Python 端有沒有丟例外」——那條線只抓得到指令不存在。
#: pytest 好端端地跑起來、卻回報「一支測試都沒收集到」時 Python 端沒有例外，
#: 於是判準說紅、工作流回去「再實作一次」，每一輪夾一個模型階段。
#: exit 5 正是「研究題誤進 TDD 工作流」的準確形狀：沒有測試檔，永遠收集不到。
_pytest沒驗到 = {
    5: "pytest 沒收集到任何測試（exit 5）",
    4: "pytest 用法錯誤，旗標打錯或路徑不存在（exit 4）",
}


def _像pytest(指令: Sequence[str]) -> bool:
    """**退出碼語意是各程式自己的知識，不是通用常識。**

    nova 自己的 4 是「護欄生效」而不是「用法錯誤」。無條件把 4／5 翻成
    跑不起來，等於把別人給的回饋偽裝成環境問題——正好是 `判準終局.跑不起來`
    存在理由的鏡像錯誤。所以這個映射綁在 pytest 上；認不出來（例如自寫的
    包裝腳本）就退回當紅，降級方向是安全的。
    """
    return any("pytest" in 段 for 段 in 指令)


def _佔住機器跑(
    指令: Sequence[str], *, 工作目錄: Path, 逾時秒: float
) -> subprocess.CompletedProcess[str]:
    """在機器鎖底下跑子程序。

    **鎖只圈住這一段。** 圈大一點（整個判準階段）就等於一次只能跑一條工作流，
    而工作流大部分時間是在等模型，那幾分鐘不該排隊。
    """
    with 佔住(_機器鎖名稱):
        return subprocess.run(  # noqa: S603 —— 指令由呼叫端明確給定
            list(指令),
            cwd=工作目錄,
            capture_output=True,
            text=True,
            timeout=逾時秒,
            check=False,
        )


def _判讀退出碼(
    結果: subprocess.CompletedProcess[str], 指令: Sequence[str]
) -> tuple[判準終局, str]:
    """指令跑完了，看退出碼決定收場。"""
    輸出 = (結果.stdout + 結果.stderr).strip()[-_證據上限:]
    if 結果.returncode == 0:
        return 判準終局.綠, 輸出
    沒驗到 = _pytest沒驗到.get(結果.returncode) if _像pytest(指令) else None
    if 沒驗到 is not None:
        # **沒驗到不等於驗不過。** 跟 OSError 那格同一個道理：這是環境／設定，
        # 重跑一百次還是同一個結果，而每次重跑中間都夾著一個模型階段。
        return 判準終局.跑不起來, f"判準跑不起來（環境問題，不是測試沒過）：{沒驗到}\n{輸出}"
    return 判準終局.紅, 輸出


def 建判準(指令: Sequence[str] = 預設判準指令, *, 逾時秒: float = 600.0) -> 判準:
    """做一個判準：在任務的工作目錄跑這條指令，退出碼 0 就是綠。

    指令是**選填**（有真正的預設值）。逾時當紅處理——判準跑不完就是沒通過，
    不能因為「不知道」而放行（fail-closed）。
    """

    def 跑(任: 任務) -> tuple[判準終局, str]:
        try:
            結果 = _佔住機器跑(指令, 工作目錄=任.工作目錄, 逾時秒=逾時秒)
        except 佔不到 as 錯:
            # **佔不到鎖不是紅。** 判準根本沒跑，回紅的話工作流會回去
            # 「再實作一次」，叫一顆模型去改一份沒問題的程式碼。
            # 跟 `_子命令_閘` 佔不到時回 3（結果未知）同一個判斷。
            return 判準終局.跑不起來, f"判準沒跑（機器忙，不是測試沒過）：{錯}"
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
        return _判讀退出碼(結果, 指令)

    return 跑


def 建重構判準() -> 判準:
    """建出重構結束時使用的 lint 與格式判準。"""
    ruff = str(Path(sys.executable).parent / "ruff")
    檢查們 = (
        ("ruff-check", 建判準((ruff, "check", "--no-cache", "."))),
        ("ruff-format", 建判準((ruff, "format", "--check", "--no-cache", "."))),
    )

    def 跑(任: 任務) -> tuple[判準終局, str]:
        收場們: list[判準終局] = []
        證據們: list[str] = []
        for 名稱, 檢查 in 檢查們:
            收場, 證據 = 檢查(任)
            收場們.append(收場)
            證據們.append(f"[{名稱}] {證據}")
        if any(收場 is 判準終局.跑不起來 for 收場 in 收場們):
            return 判準終局.跑不起來, "\n".join(證據們)
        收場 = 判準終局.綠 if all(項 is 判準終局.綠 for 項 in 收場們) else 判準終局.紅
        return 收場, "\n".join(證據們)

    return 跑


def 判準指令(文字: str | None) -> tuple[str, ...]:
    """把使用者給的字串切成指令。沒給就用預設。"""
    if not 文字 or not 文字.strip():
        return 預設判準指令
    return tuple(shlex.split(文字))


def 在哪跑(工作目錄: str | None) -> Path:
    """判準與角色共用的工作目錄。沒給就是現在這個目錄。"""
    return Path(工作目錄).resolve() if 工作目錄 else Path.cwd()

"""禁令的機械化版本：檢查是否違反禁令與寫入受管轄檔案。

這是**加速器不是保證**——agent 換掉、或直接在終端機打，這裡就攔不到。
前兩條（繞過閘門）的真正兜底是 CI 的 required check 與 GitHub ruleset（bypass 名單空的）；
第三條（合併刪除分支）則無伺服器端保證，純靠此處機械攔截與流程紀律。
寫入管轄檔案則守住 Bash 繞過護欄的缺口。
"""

import re
import shlex
from pathlib import Path

from nova.載體.自己動手 import 在管轄範圍嗎, 擋的話要說什麼, 說得出理由了嗎

#: 拆不開時用的關鍵詞掃描。這幾個字串夠獨特，直接在原文找不會誤傷。
_危險詞 = ("--no-verify", "--admin")

#: 重導寫入的正規表達式（捕捉 > 或 >> 後方的目標路徑）
_重導樣式 = re.compile(r"(?:>>|>)\s*(?:'([^']*)'|\"([^\"]*)\"|([^\s>&|;]+))")

#: Python 寫檔呼叫樣式
_PYTHON寫檔樣式 = re.compile(r'open\s*\([^)]*[\'"][wax]')

#: 管轄範圍關鍵目錄前綴
_管轄前綴 = ("src/", "tests/", "docs/")


def _拆得開的判斷(詞集: set[str]) -> tuple[bool, str]:
    if "--no-verify" in 詞集:
        return False, "禁令 --no-verify：繞過 pre-commit 快閘。要繞過閘門，先修閘門"
    if {"git", "commit", "-n"} <= 詞集:
        return False, "禁令 git commit -n：`-n` 就是 `--no-verify` 的短寫"
    if {"gh", "merge", "--admin"} <= 詞集:
        return False, "禁令 --admin：用管理員權限跳過 required check，等於自己拆掉執法點"
    if {"gh", "pr", "merge"} <= 詞集 and "--delete-branch" not in 詞集:
        return False, "禁令 gh pr merge 缺少 --delete-branch：合併要連分支一起收掉，不然流程沒走完"
    return True, ""


def _拆不開的判斷(命令: str) -> tuple[bool, str]:
    """`shlex` 拆不開時的退路：直接在原文找關鍵詞。

    **不硬擋**。硬擋看起來安全，實際上會把 heredoc、巢狀引號這種完全正常的
    指令全部誤擋掉——實測擋到過一次，而且擋在跟禁令毫無關係的地方。

    退成關鍵詞掃描不會變寬鬆：`--no-verify` 與 `--admin` 這種字串出現在
    原文裡就足以判定，反而比拆詞更容易命中（會多擋不會少擋）。
    唯一擋不住的是刻意混淆，而這裡的對象不是對手，是會手滑的執行者。
    """
    命中 = [詞 for 詞 in _危險詞 if 詞 in 命令]
    if 命中:
        return False, f"禁令 {命中[0]}（指令拆不開，退回關鍵詞掃描）：不准繞過閘門"
    return True, ""


def _python腳本寫入管轄嗎(命令: str) -> bool:
    """判斷 Python heredoc 或 inline 指令是否同時包含寫檔呼叫與管轄路徑。"""
    有寫檔 = "write_text" in 命令 or bool(_PYTHON寫檔樣式.search(命令))
    if not 有寫檔:
        return False
    return any(前綴 in 命令 for 前綴 in _管轄前綴)


def _是受管轄的路徑(目標: str, 根: Path) -> bool:
    """這個 token 是不是真的指向受管轄的檔案。

    **不能只問 `在管轄範圍嗎`。** 它的語意是「這個路徑歸不歸 nova 管」，
    而對任何相對路徑都成立（只要不以 `.` 開頭、不在 `scratchpad` 底下）——
    於是 `echo 說明 > 一句話` 裡那句中文也被當成受管轄的路徑。

    2026-08-30 這道護欄接上的那一刻就把作者鎖在外面：`nova 繞過` 自己
    執行不了，因為訊息裡的佔位符含角括號，照抄下來就命中重導樣式。
    **它印給人照做的那句話，照做就被自己擋。**

    所以收緊成「要真的落在 `src/`、`tests/`、`docs/` 底下」，
    跟 python heredoc 那條用同一份前綴表。漏掉 `README.md` 這種是刻意的：
    擋過頭的閘會被繞過，繞過一次就等於不存在。
    """
    相對 = 目標.removeprefix(f"{根}/") if 目標.startswith(str(根)) else 目標
    if not any(相對.startswith(前綴) for 前綴 in _管轄前綴):
        return False
    return 在管轄範圍嗎(Path(目標), 根目錄=根)


def _重導寫入管轄嗎(命令: str, 根: Path) -> bool:
    """檢查命令中的 > 或 >> 重導目標是否落在管轄範圍。"""
    for 匹配 in _重導樣式.finditer(命令):
        目標 = next(filter(None, 匹配.groups()), None)
        if 目標 and _是受管轄的路徑(目標, 根):
            return True
    return False


def _cp_mv寫入管轄嗎(詞列: list[str], 根: Path) -> bool:
    if 詞列[0] in ("cp", "mv") and len(詞列) > 1:
        return _是受管轄的路徑(詞列[-1], 根)
    return False


def _tee寫入管轄嗎(詞列: list[str], 根: Path) -> bool:
    if "tee" not in 詞列:
        return False
    位置 = 詞列.index("tee")
    return any(
        _是受管轄的路徑(參數, 根) for 參數 in 詞列[位置 + 1 :] if 參數 and not 參數.startswith("-")
    )


def _sed寫入管轄嗎(詞列: list[str], 根: Path) -> bool:
    if 詞列[0] != "sed":
        return False
    有就地旗標 = any(t == "-i" or t.startswith("-i") or t == "--in-place" for t in 詞列)
    if not 有就地旗標 or not 詞列[-1] or 詞列[-1].startswith("-"):
        return False
    return _是受管轄的路徑(詞列[-1], 根)


def _分拆子命令(詞列: list[str]) -> list[list[str]]:
    子命令們: list[list[str]] = []
    目前: list[str] = []
    for 詞 in 詞列:
        if 詞 in ("|", "||", ";", "&&", "&"):
            if 目前:
                子命令們.append(目前)
                目前 = []
        else:
            目前.append(詞)
    if 目前:
        子命令們.append(目前)
    return 子命令們


def _詞列會寫到管轄嗎(詞列: list[str], *, 根: Path) -> bool:
    """從已剖析的詞列中檢查 sed -i、tee、cp、mv 是否寫入管轄範圍。"""
    for 子詞列 in _分拆子命令(詞列):
        if not 子詞列:
            continue
        if _cp_mv寫入管轄嗎(子詞列, 根) or _tee寫入管轄嗎(子詞列, 根) or _sed寫入管轄嗎(子詞列, 根):
            return True
    return False


def 會寫到管轄範圍嗎(命令: str, 根目錄: Path | None = None) -> bool:
    """判斷 shell 指令是否會寫入受管轄的檔案（純函式）。"""
    根 = 根目錄 if 根目錄 is not None else Path.cwd()

    # 5. python heredoc
    if _python腳本寫入管轄嗎(命令):
        return True

    # 1. 重導
    if _重導寫入管轄嗎(命令, 根):
        return True

    # 2, 3, 4: sed -i, tee, cp, mv
    try:
        詞列 = shlex.split(命令)
    except ValueError:
        return False

    return _詞列會寫到管轄嗎(詞列, 根=根)


def _檢查硬禁令(命令: str) -> tuple[bool, str]:
    """檢查是否違反現有硬禁令（--no-verify、--admin、缺少 --delete-branch）。"""
    try:
        詞 = shlex.split(命令)
    except ValueError:
        return _拆不開的判斷(命令)
    return _拆得開的判斷(set(詞))


def 檢查指令(
    命令: str,
    根目錄: Path | None = None,
    *,
    會話: str = "",
    專案: Path | None = None,
) -> tuple[bool, str]:
    """判斷一條 shell 指令是否違反禁令或寫入管轄檔案。回傳 (放行, 原因)。

    **`會話` 與 `專案` 是出路那一半**：說得出理由（`nova 繞過` 記過了）就放行。
    `檢查編輯`（Edit／Write 那條）本來就會先問 `說得出理由了嗎`，
    這條（Bash）漏了——於是擋下來之後**沒有任何出路**，
    連 `nova 繞過` 這條指令自己都執行不了（2026-08-30 實測死鎖）。

    三條硬禁令**不吃繞過**：那是「先修閘門再繞過」，不是「說得出理由就放行」。
    """
    放行, 原因 = _檢查硬禁令(命令)
    if not 放行:
        return False, 原因
    if not 會寫到管轄範圍嗎(命令, 根目錄=根目錄):
        return True, ""
    if 會話 and 說得出理由了嗎(會話, 專案=專案 or (根目錄 or Path.cwd())):
        return True, ""
    return False, 擋的話要說什麼(會話 or "你這次的會話識別碼")

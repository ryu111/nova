"""禁令的機械化版本：依指令會做的事檢查禁令與寫入受管轄檔案。

硬禁令看的是 shell 解析後真正會執行的命令與參數，不是原文裡出現過哪些字。

這是**加速器不是保證**——agent 換掉、或直接在終端機打，這裡就攔不到。
前兩條（繞過閘門）的真正兜底是 CI 的 required check 與 GitHub ruleset（bypass 名單空的）；
第三條（合併刪除分支）則無伺服器端保證，純靠此處機械攔截與流程紀律。
寫入管轄檔案則守住 Bash 繞過護欄的缺口。
"""

import re
import shlex
from pathlib import Path

from nova.載體.自己動手 import 在管轄範圍嗎, 擋的話要說什麼, 相對專案路徑, 說得出理由了嗎

#: 重導寫入的正規表達式（捕捉 > 或 >> 後方的目標路徑）
_重導樣式 = re.compile(r"(?:>>|>)\s*(?:'([^']*)'|\"([^\"]*)\"|([^\s>&|;]+))")

#: Python open(...) 寫檔呼叫樣式（識別 'w'、'a'、'x' 等寫入模式）
_PYTHON_OPEN寫檔樣式 = re.compile(r'open\s*\([^)]*[\'"][wax]')

#: Python 寫檔方法特徵詞
_PYTHON寫檔方法名 = ("write_text", "write_bytes")

#: 寫入護欄窄化管轄的頂層目錄名稱（單一不可變集合來源）
_BASH寫入管轄目錄 = frozenset({"src", "tests", "docs"})

#: Python 腳本寫檔偵測用的管轄目錄路徑特徵（由 _BASH寫入管轄目錄 衍生）
_PYTHON腳本管轄特徵 = tuple(f"{目錄}/" for 目錄 in _BASH寫入管轄目錄)


_HEREDOC樣式 = re.compile(
    r"'[^'\r\n]*'|\"(?:\\\\.|[^\"\\\\\r\n])*\"|(?<!<)<<(?P<忽略定位字元>-?)(?!<)\s*"
    r"(?P<標記>'[^'\r\n]*'|\"[^\"\r\n]*\"|[^\s<>&|;]+)"
)


def _去掉heredoc內文(命令: str) -> str:
    """去掉 shell heredoc 的內文，只留下真正的命令行。

    普通 `<<` 的結束標記必須完全相等；只有 `<<-` 會忽略標記前的 tab。
    """
    結果: list[str] = []
    待結束: list[tuple[str, bool]] = []
    for 行 in 命令.splitlines(keepends=True):
        if 待結束:
            結束標記, 忽略定位字元 = 待結束[0]
            比對行 = 行.rstrip("\r\n")
            if 忽略定位字元:
                比對行 = 比對行.lstrip("\t")
            if 比對行 == 結束標記:
                待結束.pop(0)
            continue
        結果.append(行)
        待結束.extend(
            (
                匹配.group("標記").strip("'\""),
                bool(匹配.group("忽略定位字元")),
            )
            for 匹配 in _找出引號外的heredoc(行)
        )
    return "".join(結果)


_指令分隔詞 = {"|", "||", ";", "&&", "&", "\n", "(", ")"}


def _讀取命令詞列(命令: str) -> tuple[list[str], bool]:
    """以保留引號的方式讀取 shell 命令詞列。

    保留引號是必要的：引號內的 `--no-verify` 只是文字，不是傳給程式的旗標；
    `posix=True` 會把引號剝掉，讓文字誤變成旗標。
    """
    讀取 = shlex.shlex(
        _去掉heredoc內文(命令),
        posix=False,
        punctuation_chars="|;&()\n",
    )
    讀取.whitespace = " \t\r"
    讀取.whitespace_split = True
    詞列: list[str] = []
    try:
        while True:
            詞 = 讀取.get_token()
            if 詞 is None or 詞 == 讀取.eof:
                break
            詞列.append(詞)
    except ValueError:
        return 詞列, False
    return 詞列, True


_環境變數樣式 = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")


def _去掉命令前綴(詞列: list[str]) -> list[str]:
    """去掉環境變數與 sudo／env 外殼，留下真正執行的命令。"""
    起點 = 0
    while 起點 < len(詞列):
        if _環境變數樣式.fullmatch(詞列[起點]):
            起點 += 1
            continue
        if 詞列[起點] not in ("sudo", "env"):
            break
        起點 += 1
        while 起點 < len(詞列):
            詞 = 詞列[起點]
            if _環境變數樣式.fullmatch(詞):
                起點 += 1
            elif 詞 == "--":
                起點 += 1
                break
            elif 詞.startswith("-"):
                起點 += 2 if 詞 in ("-u", "--user", "-g", "--group", "-C", "--chdir") else 1
            else:
                break
    return 詞列[起點:]


def _判斷git禁令(詞列: list[str]) -> tuple[bool, str]:
    詞列 = _去掉命令前綴(詞列)
    if not 詞列 or 詞列[0] != "git":
        return True, ""
    子命令位置 = 1
    while 子命令位置 < len(詞列) and 詞列[子命令位置].startswith("-"):
        if 詞列[子命令位置] in (
            "-C",
            "-c",
            "--git-dir",
            "--work-tree",
            "--namespace",
            "--exec-path",
        ):
            子命令位置 += 2
        else:
            子命令位置 += 1
    if 子命令位置 >= len(詞列):
        return True, ""
    命令, 參數 = 詞列[子命令位置], 詞列[子命令位置 + 1 :]
    if 命令 == "commit" and any(_是提交跳過驗證旗標(詞) for 詞 in 參數):
        return False, "禁令 --no-verify：繞過 pre-commit 快閘。要繞過閘門，先修閘門"
    if 命令 == "push" and "--no-verify" in 參數:
        return False, "禁令 --no-verify：繞過 pre-push 快閘。要繞過閘門，先修閘門"
    return True, ""


def _找出引號外的heredoc(行: str) -> list[re.Match[str]]:
    """找出引號外的 heredoc 樣式；引號內的匹配會先被樣式消耗後排除。"""
    return [匹配 for 匹配 in _HEREDOC樣式.finditer(行) if 匹配.group("標記")]


def _判斷gh禁令(詞列: list[str]) -> tuple[bool, str]:
    詞列 = _去掉命令前綴(詞列)
    if 詞列[:3] != ["gh", "pr", "merge"]:
        return True, ""
    if "--admin" in 詞列[3:]:
        return False, "禁令 --admin：用管理員權限跳過 required check，等於自己拆掉執法點"
    if "--delete-branch" not in 詞列[3:]:
        return False, (
            "禁令 gh pr merge 缺少 --delete-branch：合併要連分支一起收掉，不然流程沒走完"
        )
    return True, ""


def _是提交跳過驗證旗標(詞: str) -> bool:
    """判斷詞是否是 `git commit` 的跳過驗證旗標或其短寫。"""
    return 詞 == "--no-verify" or (詞.startswith("-n") and not 詞.startswith("--"))


def _硬禁令判斷(命令: str) -> tuple[bool, str]:
    詞列, 拆得開 = _讀取命令詞列(命令)
    for 子命令 in _分拆子命令(詞列):
        for 禁令判斷 in (_判斷git禁令, _判斷gh禁令):
            通過, 原因 = 禁令判斷(子命令)
            if not 通過:
                if not 拆得開:
                    原因 = f"{原因}（指令拆不開，依已解析的命令段判斷）"
                return False, 原因
    return True, ""


def _python腳本寫入管轄嗎(命令: str) -> bool:
    """透過文字特徵掃描，判斷 Python 腳本或 heredoc 是否同時包含寫檔呼叫與管轄路徑特徵。"""
    有寫檔 = any(方法 in 命令 for 方法 in _PYTHON寫檔方法名) or bool(
        _PYTHON_OPEN寫檔樣式.search(命令)
    )
    if not 有寫檔:
        return False
    return any(特徵 in 命令 for 特徵 in _PYTHON腳本管轄特徵)


def _是Bash寫入管轄路徑(目標: str, 根: Path) -> bool:
    """這個 token 是不是落在 Bash 寫入護欄窄化的管轄範圍。

    **不能只問 `在管轄範圍嗎`。** 它的語意是「這個路徑歸不歸 nova 管」，
    而對任何相對路徑都成立（只要不以 `.` 開頭、不在 `scratchpad` 底下）——
    於是 `echo 說明 > 一句話` 裡那句中文也被當成受管轄的路徑。

    2026-08-30 這道護欄接上的那一刻就把作者鎖在外面：`nova 繞過` 自己
    執行不了，因為訊息裡的佔位符含角括號，照抄下來就命中重導樣式。
    **它印給人照做的那句話，照做就被自己擋。**

    所以收緊成「要真的落在 `src/`、`tests/`、`docs/` 底下」，
    跟 python heredoc 那條用同一份窄化目錄來源。漏掉 `README.md` 這種是刻意的：
    擋過頭的閘會被繞過，繞過一次就等於不存在。
    """
    路徑 = Path(目標)
    if not 在管轄範圍嗎(路徑, 根目錄=根):
        return False
    相對 = 相對專案路徑(路徑, 根目錄=根)
    return bool(相對 and 相對.parts and 相對.parts[0] in _BASH寫入管轄目錄)


def _重導寫入管轄嗎(命令: str, 根: Path) -> bool:
    """檢查命令中的 > 或 >> 重導目標是否落在管轄範圍。"""
    # 已知限制：這裡掃的是原文，字串裡的 > 仍可能被視為重導。
    for 匹配 in _重導樣式.finditer(命令):
        目標 = next((組 for 組 in 匹配.groups() if 組), None)
        if 目標 and _是Bash寫入管轄路徑(目標, 根):
            return True
    return False


def _擷取_cp_mv_目標(詞列: list[str]) -> str:
    """從 cp 或 mv 參數中擷取寫入目標。

    優先解析 -t / --target-directory，否則取最後一個非選項參數。
    """
    for i, 詞 in enumerate(詞列):
        if 詞 in ("-t", "--target-directory") and i + 1 < len(詞列):
            return 詞列[i + 1]
        if 詞.startswith("-t") and 詞 != "-t":
            return 詞.removeprefix("-t")
        if 詞.startswith("--target-directory="):
            return 詞.split("=", 1)[1]
    位置參數 = [詞 for 詞 in 詞列[1:] if not 詞.startswith("-")]
    return 位置參數[-1] if 位置參數 else ""


def _cp_mv寫入管轄嗎(詞列: list[str], 根: Path) -> bool:
    if 詞列[0] not in ("cp", "mv") or len(詞列) <= 1:
        return False
    目標 = _擷取_cp_mv_目標(詞列)
    return bool(目標 and _是Bash寫入管轄路徑(目標, 根))


def _tee寫入管轄嗎(詞列: list[str], 根: Path) -> bool:
    if "tee" not in 詞列:
        return False
    位置 = 詞列.index("tee")
    return any(
        _是Bash寫入管轄路徑(參數, 根)
        for 參數 in 詞列[位置 + 1 :]
        if 參數 and not 參數.startswith("-")
    )


def _sed寫入管轄嗎(詞列: list[str], 根: Path) -> bool:
    if 詞列[0] != "sed":
        return False
    有就地旗標 = any(詞.startswith(("-i", "--in-place")) for 詞 in 詞列)
    if not 有就地旗標:
        return False
    return any(_是Bash寫入管轄路徑(詞, 根) for 詞 in 詞列[1:] if 詞 and not 詞.startswith("-"))


def _分拆子命令(詞列: list[str]) -> list[list[str]]:
    子命令們: list[list[str]] = []
    目前: list[str] = []
    for 詞 in 詞列:
        if 詞 in _指令分隔詞:
            if 目前:
                子命令們.append(目前)
                目前 = []
        else:
            目前.append(詞)
    if 目前:
        子命令們.append(目前)
    return 子命令們


def _子命令寫入管轄嗎(子詞列: list[str], 根: Path) -> bool:
    return _cp_mv寫入管轄嗎(子詞列, 根) or _tee寫入管轄嗎(子詞列, 根) or _sed寫入管轄嗎(子詞列, 根)


def _詞列會寫到管轄嗎(詞列: list[str], *, 根: Path) -> bool:
    """從已剖析的詞列中檢查 sed -i、tee、cp、mv 是否寫入管轄範圍。"""
    return any(_子命令寫入管轄嗎(子詞列, 根) for 子詞列 in _分拆子命令(詞列))


def 會寫到管轄範圍嗎(命令: str, 根目錄: Path | None = None) -> bool:
    """判斷 shell 指令是否會寫入受管轄的檔案（純函式）。

    硬禁令判斷會去掉 heredoc 內文，因為它只判斷真正執行的命令；這裡刻意保留
    原文，因為 Python heredoc 的寫檔呼叫與路徑就在內文裡。
    """
    根 = 根目錄 if 根目錄 is not None else Path.cwd()

    if _python腳本寫入管轄嗎(命令):
        return True

    if _重導寫入管轄嗎(命令, 根):
        return True

    try:
        詞列 = shlex.split(命令)
    except ValueError:
        return False

    return _詞列會寫到管轄嗎(詞列, 根=根)


def _檢查硬禁令(命令: str) -> tuple[bool, str]:
    """檢查是否違反現有硬禁令（--no-verify、--admin、缺少 --delete-branch）。"""
    return _硬禁令判斷(命令)


def 檢查指令(
    命令: str,
    專案: Path | None = None,
    *,
    會話: str = "",
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
    專案目錄 = 專案 if 專案 is not None else Path.cwd()
    if not 會寫到管轄範圍嗎(命令, 根目錄=專案目錄):
        return True, ""
    if 會話 and 說得出理由了嗎(會話, 專案=專案目錄):
        return True, ""
    return False, 擋的話要說什麼(會話 or "你這次的會話識別碼")

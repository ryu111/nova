"""繁體中文規則的機械化版本：抓簡體字與日文新字體。

CLAUDE.md 的「一律繁體中文」是提示詞——模型會忘，換模型就沒了。這裡把它變成閘。

判準用標準庫的 Big5 編碼表：**Big5 收的就是標準繁體字集**，編不進去的就不是繁體。
不用手打字表——手打表既會誤報（把「角」「谷」當簡體）又會漏報（漏掉「無」「來」
「機」這種高頻字），而且沒人維護得動。

只看 CJK 漢字，emoji 與符號一律略過（Big5 也編不動它們，但那不是語言問題）。

從簡: Big5 收了少數異體字（見 `_補抓`），在現代繁體幾乎只當簡體用，所以另外補一份
小清單。天花板是 Big5 沒收的罕用繁體字會被誤判；真的遇到就用 `允許標記` 放行那一行。
"""

from pathlib import Path

from nova.載體.git查詢 import 追蹤中的檔案

# 含此標記的行整行不檢查——引用非繁體原文、或用到罕用字時的逃生門。
允許標記 = "nova:允許非繁體"

# Big5 收了，但在現代繁體幾乎只會以簡體身分出現的字。
_補抓 = frozenset("万与机极网构据惊")  # nova:允許非繁體

# 會被掃的副檔名。
掃描副檔名 = frozenset({".py", ".md", ".yml", ".yaml", ".toml", ".cfg", ".sh"})


def 是漢字(字: str) -> bool:
    """是不是 CJK 漢字。不是的話（英數、標點、emoji）語言規則不管。"""
    return "\u3400" <= 字 <= "\u9fff" or "\uf900" <= 字 <= "\ufaff" or 字 >= "\U00020000"


def 是非繁體字(字: str) -> bool:
    """單一漢字是不是「不該出現在繁體中文裡」。"""
    if not 是漢字(字):
        return False
    if 字 in _補抓:
        return True
    try:
        字.encode("big5")
    except UnicodeEncodeError:
        return True
    return False


def 找非繁體字(文字: str) -> list[tuple[int, str, str]]:
    """回傳 (行號從 1 起, 命中的字, 整行內容)，沒命中就是空清單。

    帶整行出來是為了可行動——只說「第 47 行有非繁體字」還要人自己去翻。
    """
    命中: list[tuple[int, str, str]] = []
    for 行號, 整行 in enumerate(文字.splitlines(), start=1):
        if 允許標記 in 整行:
            continue
        命中.extend((行號, 字, 整行) for 字 in 整行 if 是非繁體字(字))
    return 命中


def 檢查繁體中文(根目錄: Path) -> tuple[bool, str]:
    """掃 git 追蹤中的原始碼與文件，回傳 (放行, 證據)。

    範圍用 git ls-files 決定——不必自己維護 .venv／快取的排除表。
    """
    問題: list[str] = []
    for 相對 in 追蹤中的檔案(根目錄):
        路徑 = 根目錄 / 相對
        if 路徑.suffix not in 掃描副檔名 or not 路徑.is_file():
            continue
        for 行號, 字, 整行 in 找非繁體字(路徑.read_text(encoding="utf-8")):
            問題.append(f"{相對}:{行號} 出現「{字}」 → {整行.strip()[:60]}")
    return (not 問題), "\n".join(問題)

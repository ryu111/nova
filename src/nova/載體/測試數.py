"""「刪測試不是簡化，是拆掉驗收機制」的機械化版本。"""

import re
from pathlib import Path

from nova.載體.git查詢 import ref存在, ref裡的檔案, 讀取版本

_測試定義 = re.compile(r"^\s*(?:async\s+)?def\s+test_", re.MULTILINE)


def 數測試(內容: str) -> int:
    """數一份原始碼裡有幾個測試函式。只認行首的 def，字串裡的不算。"""
    return len(_測試定義.findall(內容))


def 比較測試數(前: int, 後: int) -> tuple[bool, str]:
    """測試數只准持平或變多。回傳 (放行, 原因)。"""
    if 後 < 前:
        return False, f"測試數從 {前} 掉到 {後}，少了 {前 - 後} 支。刪測試＝拆掉驗收機制"
    return True, ""


def 數某個ref的測試(根目錄: Path, ref: str) -> int:
    """某個 ref 上的全 repo 測試總數。"""
    return sum(
        數測試(內容)
        for 相對 in ref裡的檔案(根目錄, ref)
        if 相對.endswith(".py")
        if (內容 := 讀取版本(根目錄, 相對, ref=ref)) is not None
    )


def 數工作區的測試(根目錄: Path) -> int:
    """工作區當下的全 repo 測試總數。"""
    return sum(
        數測試(路徑.read_text(encoding="utf-8"))
        for 路徑 in 根目錄.rglob("*.py")
        if 路徑.is_file() and not _要略過(路徑, 根目錄)
    )


def 檢查測試數(根目錄: Path, *, 基準: str = "HEAD") -> tuple[bool, str]:
    """比對基準 ref 與工作區的**全 repo 測試總數**，回傳 (放行, 證據)。

    比總數而不是逐檔比——逐檔比會把改名與搬移誤判成刪測試。

    `基準` 預設 `HEAD`，那是 commit 前的用法。**CI 上必須改成 base branch**
    （例如 `origin/main`）：CI checkout 之後工作區就是 HEAD，前 == 後永遠成立，
    這條規則會整條空轉。
    """
    if not ref存在(根目錄, 基準):
        return False, f"抓不到基準 ref `{基準}`。CI 要先 git fetch（checkout 預設只抓一層深度）"
    return 比較測試數(數某個ref的測試(根目錄, 基準), 數工作區的測試(根目錄))


def _要略過(路徑: Path, 根目錄: Path) -> bool:
    略過目錄 = {".venv", ".git", ".mypy_cache", ".ruff_cache", ".pytest_cache", "build", "dist"}
    return bool(略過目錄 & set(路徑.relative_to(根目錄).parts))

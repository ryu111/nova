"""架構測試：`src/nova/載體/線呈現.py` 呈現層不得直接讀程序表或引入程序觀測。

呈現層的職責是純排版與人話格式化，輸入為 `線現況` 快照資料，
不准直接跑 `ps`、不准 import `subprocess`、不准依賴 `程序觀測` 或 `工作樹觀測`。
"""

import ast
from pathlib import Path

專案根目錄 = Path(__file__).resolve().parents[2]
線呈現原始碼路徑 = 專案根目錄 / "src" / "nova" / "載體" / "線呈現.py"

_禁用的模組們 = frozenset(
    {
        "subprocess",
        "psutil",
        "nova.載體.程序觀測",
        "nova.載體.工作樹觀測",
    }
)


def _取得import的模組們(樹: ast.Module) -> set[str]:
    模組們: set[str] = set()
    for 節點 in ast.walk(樹):
        if isinstance(節點, ast.Import):
            for 名 in 節點.names:
                模組們.add(名.name)
        elif isinstance(節點, ast.ImportFrom):
            if 節點.module:
                模組們.add(節點.module)
            for 名 in 節點.names:
                if 節點.module:
                    模組們.add(f"{節點.module}.{名.name}")
                else:
                    模組們.add(名.name)
    return 模組們


def test_線呈現模組必須存在() -> None:
    """呈現層必須被獨立拆分為 `src/nova/載體/線呈現.py`。"""
    assert 線呈現原始碼路徑.is_file(), f"找不到呈現層模組：{線呈現原始碼路徑}"


def test_線呈現模組不准import程序觀測或subprocess() -> None:
    """呈現層不准直接讀程序或引入程序觀測模組。"""
    assert 線呈現原始碼路徑.is_file(), f"找不到呈現層模組：{線呈現原始碼路徑}"
    原始碼 = 線呈現原始碼路徑.read_text(encoding="utf-8")
    語法樹 = ast.parse(原始碼, filename=str(線呈現原始碼路徑))
    匯入模組們 = _取得import的模組們(語法樹)

    違規 = 匯入模組們 & _禁用的模組們
    assert not 違規, f"線呈現模組違規匯入了禁用模組：{sorted(違規)}"

    # 同時確保沒有任何子字串形式直接呼叫 ps 命令或 lsof
    assert '["ps"' not in 原始碼 and "['ps'" not in 原始碼, "線呈現模組不准直接呼叫 ps"
    assert '["lsof"' not in 原始碼 and "['lsof'" not in 原始碼, "線呈現模組不准直接呼叫 lsof"

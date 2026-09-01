"""架構邊界測試：把 nova 收的獨占閉包搬出命令列。

所有權閉包判準（AST 可達性）：
- 只被 `子命令_收` 可達的專用 helper（`_收尾閘`, `_跑收尾指令`, `_跑並印收尾指令`）
  必須搬移至 `nova.載體.命令.收`，不得留在 `src/nova/載體/命令列.py`。
- `命令列.py` 只保留 CLI composition root 與轉交 wiring。
"""

import ast
import importlib
from pathlib import Path

專案根 = Path(__file__).resolve().parents[2]
命令列原始碼路徑 = 專案根 / "src/nova/載體/命令列.py"
收命令原始碼路徑 = 專案根 / "src/nova/載體/命令/收.py"

_收成獨占閉包函式們 = frozenset(
    {
        "_收尾閘",
        "_跑收尾指令",
        "_跑並印收尾指令",
    }
)


def test_收成專用輔助函式不准以函式定義留在命令列AST() -> None:
    """`_收尾閘`、`_跑收尾指令`、`_跑並印收尾指令` 不得以頂層 FunctionDef 留在命令列.py AST。"""
    原始碼 = 命令列原始碼路徑.read_text(encoding="utf-8")
    語法樹 = ast.parse(原始碼)

    頂層函式名 = {
        節點.name
        for 節點 in 語法樹.body
        if isinstance(節點, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    違規殘留 = 頂層函式名 & _收成獨占閉包函式們
    assert not 違規殘留, f"收成獨占閉包函式仍以實作定義住在命令列.py AST 中：{sorted(違規殘留)}"


def test_收命令模組存在且定義收成閉包() -> None:
    """`src/nova/載體/命令/收.py` 必須存在，並包含收成閉包實作。"""
    assert 收命令原始碼路徑.is_file(), f"收命令模組檔案不存在：{收命令原始碼路徑}"

    模組 = importlib.import_module("nova.載體.命令.收")
    for 符號名 in _收成獨占閉包函式們:
        assert hasattr(模組, 符號名), f"nova.載體.命令.收 缺少收成閉包函式：{符號名}"
    assert hasattr(模組, "子命令_收"), (
        "nova.載體.命令.收 必須提供**公開的**收成入口函式——"
        "跨模組去拿 `_` 開頭的名字，等於要求呼叫端整檔關掉 SLF001"
    )


def test_命令列處理們引用的收命令來自收模組() -> None:
    """`命令列.處理們['收']` 必須指向 `nova.載體.命令.收` 中的實作或轉發入口。"""
    收模組 = importlib.import_module("nova.載體.命令.收")
    from nova.載體 import 命令列

    assert "收" in 命令列.處理們
    收處理器 = 命令列.處理們["收"]
    assert callable(收處理器)
    assert 收處理器 is 收模組.子命令_收

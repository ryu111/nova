"""架構測試：CPU 額度政策不准把 `閘鎖` 跟 `規則表` 綁成一個環。

現在的環是這樣繞的：

    閘鎖 →（要一個 `平行成數`）→ 規則表 →（要 `規則`／`抽乾整池`）→ 閘
         ← （函式內 import）← 閘

`載體/閘.py` 的 `_拿這條的額度` 只好把 `from nova.載體.閘鎖 import ...`
藏進函式體，還配一個 `# noqa: PLC0415`——**函式內匯入不是解法，是症狀**：
它讓循環在 import 時看不見，於是下一個人再加一條邊也不會有人喊停，
而真的爆炸那天（誰先被 import 決定成敗）錯誤訊息會指到毫不相干的地方。

治法是把「這台機器分幾份 CPU」這個政策搬到一個誰都能依賴的中立模組，
讓 `額度 ← 閘鎖 ← 閘 ← 規則表` 全部單向。

這一支純讀原始碼、零 fork，但住 `tests/驗收/` 而不是 `tests/單元/`：
跟另外兩支架構測試同一層，而且它讀硬碟上的檔。
"""

import ast
from pathlib import Path

專案根目錄 = Path(__file__).resolve().parents[2]
閘鎖原始碼路徑 = 專案根目錄 / "src" / "nova" / "載體" / "閘鎖.py"
閘原始碼路徑 = 專案根目錄 / "src" / "nova" / "載體" / "閘.py"

#: 閘鎖不准依賴的模組。兩個都是「往下游要東西」——`規則表` 更是整份規則的家，
#: 為了一個成數把它拉進來，等於讓一把鎖依賴所有規則的宣告。
_閘鎖不准依賴的 = frozenset({"nova.載體.規則表", "nova.載體.閘"})


def _取得import的模組們(樹: ast.Module) -> set[str]:
    """整棵樹裡 import 到的模組名（含 `from x import y` 的 `x.y`）。

    跟 `test_線呈現不直接讀程序.py` 是同一份複製品：測試目錄沒有 `__init__.py`
    可以跨檔 import，複製比為了三十行去建套件便宜。
    """
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


def _剖析(路徑: Path) -> ast.Module:
    assert 路徑.is_file(), f"找不到原始碼：{路徑}"
    return ast.parse(路徑.read_text(encoding="utf-8"), filename=str(路徑))


def test_CPU額度政策不准讓閘鎖與規則表互相依賴() -> None:
    """**一把鎖要的是一個成數，不是整份規則表。**

    `閘鎖` 只需要「這台機器分幾份」這一個政策數字。為了它去 import `規則表`，
    就把「所有規則怎麼宣告」整包綁進了鎖的依賴裡——而 `規則表` 反過來要 `閘`，
    `閘` 又要 `閘鎖`，環就成了。政策該住在誰都能依賴的中立模組（或注入進來）。
    """
    匯入模組們 = _取得import的模組們(_剖析(閘鎖原始碼路徑))

    違規 = 匯入模組們 & _閘鎖不准依賴的
    assert not 違規, (
        f"閘鎖為了一個成數依賴了 {sorted(違規)}，而規則表依賴閘、閘又依賴閘鎖——這是循環。"
        "把 CPU 額度政策搬到中立模組（或注入），恢復單向依賴"
    )


def test_閘不准用函式內匯入遮住循環依賴() -> None:
    """**函式內匯入是把環藏起來，不是把環解開。**

    藏起來之後，靜態工具、`import nova.載體.閘` 的人、下一個加邊的人
    都看不到環還在；等到哪天 import 順序一變真的炸了，
    錯誤訊息會指向一個跟這個決定毫無關係的檔案。
    """
    語法樹 = _剖析(閘原始碼路徑)

    for 節點 in ast.walk(語法樹):
        if not isinstance(節點, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        裡面 = [子 for 子 in ast.walk(節點) if isinstance(子, ast.Import | ast.ImportFrom)]
        assert not 裡面, f"{節點.name} 用函式內匯入遮住循環依賴：{[ast.unparse(子) for 子 in 裡面]}"

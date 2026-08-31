"""三層落點閘的固定負控刀。

閘本身會綠不代表它在看：把閘的判斷一刀一刀弄壞，對應的測試就要紅。
沒有這幾刀，閘退化成「永遠放行」時沒有任何訊號。
"""

from pathlib import Path

from tests.負控.登記 import 刪除一次, 替換一次, 變異

登記 = (
    變異(
        識別="迴圈的禁令消失",
        目標檔=Path("src/nova/載體/架構閘.py"),
        操作=刪除一次('"迴圈": ("載體",),'),
        該紅=("tests/單元/test_架構閘.py::test_迴圈import載體時指名檔案行號與違反的那條",),
        最多秒=10.0,
    ),
    變異(
        識別="型別檢查底下的import也一起算",
        目標檔=Path("src/nova/載體/架構閘.py"),
        操作=替換一次(
            "if isinstance(節點, ast.Import | ast.ImportFrom) and 節點 not in 放行",
            "if isinstance(節點, ast.Import | ast.ImportFrom)",
        ),
        該紅=("tests/單元/test_架構閘.py::test_型別檢查底下的import放行但搬到執行期就紅",),
        最多秒=10.0,
    ),
    變異(
        識別="任何屬性叫TYPE_CHECKING都當成型別檢查",
        目標檔=Path("src/nova/載體/架構閘.py"),
        操作=替換一次(
            "        isinstance(條件, ast.Attribute)\n"
            '        and 條件.attr == "TYPE_CHECKING"\n'
            "        and isinstance(條件.value, ast.Name)\n"
            '        and 條件.value.id == "typing"\n',
            '        isinstance(條件, ast.Attribute) and 條件.attr == "TYPE_CHECKING"\n',
        ),
        該紅=("tests/單元/test_架構閘.py::test_自己取名叫TYPE_CHECKING的執行期旗標不算型別檢查",),
        最多秒=10.0,
    ),
    變異(
        識別="三層落點沒登進規則表",
        目標檔=Path("src/nova/載體/規則表.py"),
        操作=刪除一次(
            "        規則(\n"
            '            代碼="layer-boundaries",\n'
            '            名稱="三層落點（契約 ← 迴圈 ← 載體，箭頭不准反過來）",\n'
            "            閘點=提交與CI,\n"
            '            負責層="載體",\n'
            "            檢查=lambda: 檢查架構落點(根目錄),\n"
            "            階段=靜態,\n"
            "        ),\n"
        ),
        該紅=("tests/單元/test_架構閘.py::test_三層落點登記在提交閘也登記在ci閘",),
        最多秒=10.0,
    ),
)

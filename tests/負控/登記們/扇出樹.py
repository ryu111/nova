"""守「開不出工作樹的分支不准跑」的刀。

靜默退回共用工作目錄是假隔離——比沒有隔離更糟，因為它看起來像有。
"""

from pathlib import Path

from tests.負控.登記 import 替換一次, 變異

登記 = (
    變異(
        識別="開不出工作樹的分支照樣派出去",
        目標檔=Path("src/nova/迴圈/扇出.py"),
        操作=替換一次(
            "    return isinstance(工作項.工作樹, 開不出工作樹)",
            "    return False",
        ),
        該紅=("tests/單元/test_扇出.py::test_開不出工作樹的分支不准跑而且分得出它沒跑",),
        最多秒=20.0,
    ),
)

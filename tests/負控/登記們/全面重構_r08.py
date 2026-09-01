"""全面重構 R08：線觀測來源、工作樹查詢與呈現分開的負控刀。

呈現層只負責輸出排版與人話格式化，不得跨過邊界直接引入 subprocess 或程序觀測。
"""

from pathlib import Path

from tests.負控.登記 import 替換一次, 變異

登記 = (
    #: 呈現層不得越界直接讀取程序或引入 subprocess。若呈現層直接讀程序，架構測試必須抓到並報紅。
    變異(
        識別="全面重構-R08-線呈現不得直接讀程序",
        目標檔=Path("src/nova/載體/線呈現.py"),
        操作=替換一次(
            "_成功退出碼 = 0",
            "_成功退出碼 = 0\nimport subprocess",
        ),
        必須覆蓋=frozenset(),
        該紅=(
            "tests/驗收/test_線呈現不直接讀程序.py::test_線呈現模組不准import程序觀測或subprocess",
        ),
        最多秒=10.0,
    ),
)

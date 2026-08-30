"""行號錨點推導的回歸測試。"""

from pathlib import Path

from . import 執行器
from .登記 import 替換一次, 變異

專案根目錄 = Path(__file__).resolve().parents[2]


def test_跨行錨點的每個可執行行都被推導() -> None:
    操作 = 替換一次(
        "@property\n"
        "    def 結果(self) -> 結果代碼:\n"
        '        """回傳結果未知終局。"""\n'
        "        return 結果代碼.結果未知\n",
        "",
    )
    一筆 = 變異(
        識別="跨行推導",
        目標檔=Path("src/nova/契約/節點.py"),
        操作=操作,
        該紅=(),
        最多秒=1.0,
    )

    推導的行 = 執行器._推導破壞行(專案根目錄 / 一筆.目標檔, 一筆)

    assert len(推導的行) == 3

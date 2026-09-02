"""守審查員提示的範圍外回報規矩不被刪掉。"""

from pathlib import Path

from tests.負控.登記 import 替換一次, 變異

_審查員的FOLLOW_UP規矩 = (
    "1. 只審這張票宣告的範圍與這次的 diff；範圍外的發現寫 `FOLLOW-UP: <描述>`，"
    "不算 ISSUE、不影響判定。\n"
)
_該紅 = (
    (
        "tests/單元/test_角色提示.py::Test退回原因已回饋進提示"
        "::test_審查員只審票的範圍範圍外寫FOLLOW_UP"
    ),
)


登記 = (
    變異(
        識別="角色提示刪掉審查員範圍外FOLLOW-UP規矩",
        目標檔=Path("src/nova/迴圈/角色提示.py"),
        操作=替換一次(_審查員的FOLLOW_UP規矩, ""),
        該紅=_該紅,
        最多秒=5.0,
    ),
)

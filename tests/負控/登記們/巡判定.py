"""守「巡的判定不准把『查不到在不在跑』當成『沒在跑』」的那把刀。

`是否在跑` 是三態。`None` 當作沒在跑的話，巡會在一棵**可能正在跑**的樹上
叫醒同一張票，兩個工作流搶同一棵樹；而拿 flock 當替代也擋不住——
拿不到鎖那條路照樣會把 `狀態.json` 覆寫成 busy，把 `resume_not_before` 洗掉。
所以放行條件只認 `is False`，這把刀就是拿掉那個「只認 False」。
"""

from pathlib import Path

from tests.負控.登記 import 替換一次, 變異

登記 = (
    #: 錨點吊在 `def` 那一行上（不吊在 docstring 或裸的 `is False` 上：那些措辭
    #: 會被改寫、那三個字別處也長得出來，錨點對不上要當場炸，不能靜靜打空）。
    #: 在函式開頭插一行提早 return，把三態壓成「不是 True 就是沒在跑」。
    變異(
        識別="巡把查不到當作沒在跑",
        目標檔=Path("src/nova/載體/巡.py"),
        操作=替換一次(
            "def 能不能叫(在跑: bool | None) -> bool:\n",
            "def 能不能叫(在跑: bool | None) -> bool:\n"
            "    return 在跑 is not True  # 負控：None 當作沒在跑\n",
        ),
        該紅=("tests/整合/test_巡的判定.py::test_查不到在不在跑就不算到期",),
        最多秒=120.0,
    ),
)

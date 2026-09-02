"""守「單次上限比的是燒了多少，不是上下文多大」那兩把刀。

實測 21 筆被收 4 的 `single_token_exceeded` 全是 codex，`cache_read` 佔 input
90%～98%，扣掉快取之後的新鮮量只有 154,360～684,765——**沒有一筆碰到 2,000,000**。
它們被擋的理由是「上下文很大」，而這條護欄要擋的是「一次呼叫燒掉的錢」。

第三把砍的是接力鏈的加總：`快取建立token` 不能套「有一顆給不出來就整個不給」，
因為 codex／agy 的 `None` 不是「不知道」而是「這家沒有這個量」，
而 `新鮮token` 又把 `None` 當 0——兩條規則湊起來就是換腦時整條低報。

三把刀砍的都是**公式**而不是欄位：`新鮮token` 這個屬性照樣讀得到、
`快取讀取token` 照樣有值，只是量法換回原本那個——最容易假綠的就是這種
「欄位還在、語意換掉」的改法，所以要有刀當場把它殺掉。
"""

from pathlib import Path

from tests.負控.登記 import 替換一次, 變異

_新鮮量 = "tests/單元/test_單次上限量新鮮token.py"
_解析 = "tests/單元/test_模型解析.py::Testcodex"
_接力 = "tests/單元/test_接力腦.py::Test快取建立要跟著新鮮量走"

登記 = (
    #: 把快取讀取加回新鮮量＝護欄又變回量「上下文多大」。
    #: 30 回合每回合重讀 70k 上下文就是 2.1M cache_read，工只有 output 那兩萬，
    #: 加回去之後這種呼叫立刻被收 4——那正是這張票要修掉的病。
    變異(
        識別="新鮮量把快取讀取加回去",
        目標檔=Path("src/nova/契約/模型回應.py"),
        操作=替換一次(
            "return self.輸入token + self.輸出token + (self.快取建立token or 0)",
            "return self.輸入token + self.輸出token + (self.快取建立token or 0)"
            " + (self.快取讀取token or 0)",
        ),
        該紅=(f"{_新鮮量}::test_快取讀取三百萬不算燒錢_不准收手",),
        最多秒=60.0,
    ),
    #: 把 codex 的 `輸入token` 改回原值＝三家的語意又不對齊。
    #: codex 的 `input_tokens` **含** `cached_input_tokens`（`non_cached_input =
    #: input − cached`，codex-rs/protocol/src/protocol.rs），claude 的不含；
    #: 不在解析器扣掉，這個不對稱就會洩到上限、本輪累計與預算三個地方。
    變異(
        識別="codex的輸入token不扣快取",
        目標檔=Path("src/nova/載體/模型/解析.py"),
        操作=替換一次(
            "輸入token=_codex的非快取輸入(用了),",
            '輸入token=int(用了.get("input_tokens", 0)),',
        ),
        該紅=(f"{_解析}::test_輸入token是非快取輸入_三家在解析器對齊",),
        最多秒=60.0,
    ),
    #: 把接力鏈上每一顆的 `快取建立token` 抹成 `None`＝退回「任一 `None`
    #: 就整體 `None`」那條規則。它跟「`新鮮token` 把 `None` 當 0」湊在一起
    #: 就是低報：claude 那顆真的燒掉、而且按 1.25× 計價的新鮮輸入，
    #: 在換腦的那一刻整條消失（實例：逐顆 19,048 → 聚合後 2,380）。
    #: 錨點挑函式簽名而不是那一行聚合寫法——寫法會改，簽名不會。
    變異(
        識別="接力把快取建立整條丟掉",
        目標檔=Path("src/nova/載體/模型/接力.py"),
        操作=替換一次(
            "def _加總用量(花過: Sequence[用量]) -> 用量:",
            "def _加總用量(花過: Sequence[用量]) -> 用量:\n"
            "    花過 = [replace(用, 快取建立token=None) for 用 in 花過]",
        ),
        該紅=(f"{_接力}::test_混合接力的快取建立不准整條丟掉",),
        最多秒=60.0,
    ),
)

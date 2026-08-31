"""負控刀那個檔只准被閘跑一次。

`registered-mutation` 跑 `tests/負控/` 底下的登記負控，那是它的工作；
`pytest-parallel` 因為那些檔就在 `tests/` 底下，收集時又跑了一次。
實測這重複的一次讓 `pytest-parallel` 從 17.62 秒漲到 61.97 秒。

修法不是在平行那條寫死一行 `--ignore=tests/負控/test_登記的變異會被殺.py`——
那是口頭約定：之後多一個負控檔，得有人記得回來補，沒人守著。
要的是**一個來源**：負控檔清單只寫在一處，兩條規則都從那裡讀。
所以這支測試不准自己手寫檔名，只准從 `負控檔們` 讀。
"""

from collections.abc import Callable
from pathlib import Path

from nova.載體.規則表 import 建規則表, 負控檔們
from nova.載體.閘 import 規則

#: `挖pytest命令列` fixture 的形狀。跨檔 import conftest 會讓 mypy 把它
#: 算成兩個模組（見 `tests/conftest.py` 開頭），所以型別各寫一份。
_挖命令列型 = Callable[[規則], tuple[str, ...]]


def _取(代碼: str) -> 規則:
    表 = 建規則表(Path(__file__).resolve().parents[2])
    條 = next((條 for 條 in 表 if 條.代碼 == 代碼), None)
    assert 條 is not None, f"規則表裡找不到 {代碼}"
    return 條


def _位置參數(命令列: tuple[str, ...]) -> set[str]:
    """命令列裡的路徑參數（`pytest` 自己與選項都不算）。"""
    return {參數 for 參數 in 命令列[1:] if not 參數.startswith("-")}


def _排除清單(命令列: tuple[str, ...]) -> set[str]:
    """`--ignore=` 排掉的路徑。"""
    return {參數.split("=", 1)[1] for 參數 in 命令列 if 參數.startswith("--ignore=")}


def test_來源不是空的() -> None:
    """空的來源推不出任何東西，另外兩支測試會空轉成假綠。"""
    assert 負控檔們, "`負控檔們` 是空的——那 registered-mutation 等於沒在跑負控"


def test_登記負控規則跑的就是來源那份清單(挖pytest命令列: _挖命令列型) -> None:
    """`registered-mutation` 的目標檔＝來源清單，一個不多一個不少。

    來源要是有一筆沒被跑，它就不是來源，只是一份沒人用的註解。
    """
    跑的 = _位置參數(挖pytest命令列(_取("registered-mutation")))
    assert 跑的 == set(負控檔們), (
        f"registered-mutation 實際跑 {sorted(跑的)}，來源說是 {sorted(負控檔們)}"
    )


def test_平行測試排除了來源裡的每一個負控檔(挖pytest命令列: _挖命令列型) -> None:
    """`pytest-parallel` 的排除清單要蓋滿來源裡的每一個負控檔。

    排除清單是從 `負控檔們` 推出來的，所以往來源加一筆**不會**讓這支紅——
    它守的是另一個退化：有人把規則表裡展開排除參數的那一段拿掉、
    或改成手寫 `--ignore=...`。那時排除清單就跟來源脫鉤，這裡才會紅。
    """
    排除 = _排除清單(挖pytest命令列(_取("pytest-parallel")))
    for 負控檔 in 負控檔們:
        assert 負控檔 in 排除, (
            f"pytest-parallel 沒排除 {負控檔}——registered-mutation 已經在跑它了，"
            f"目前只排除了 {sorted(排除)}"
        )


def test_平行測試的排除清單不准多出來源以外的東西(挖pytest命令列: _挖命令列型) -> None:
    """排除清單只准是來源推出來的。

    多出來的那筆代表有人手寫了一行 `--ignore=...`——分岔就是從那一行開始的。
    """
    排除 = _排除清單(挖pytest命令列(_取("pytest-parallel")))
    多出來的 = 排除 - set(負控檔們)
    assert not 多出來的, f"pytest-parallel 排除了來源沒登記的 {sorted(多出來的)}"

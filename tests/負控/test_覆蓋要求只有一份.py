"""「該紅的測試必須走到哪幾行」只准有一份判定。

`要求覆蓋的行`（`tests/負控/執行器.py`）的 docstring 自己寫著它存在的理由是
「讓跑前體檢算的行跟這裡是同一份，抄第二份的話體檢說過、CI 說沒過」。
`跑前體檢.py` 確實是問它的，**但 `_覆蓋率前置` 自己還留著一份逐條相同的
`if/elif/elif/else`**——也就是說現在有兩份：

* 秒級的跑前體檢問 `要求覆蓋的行`；
* 最後的權威 `registered-mutation`（158 秒那條）走 `_覆蓋率前置` 那份拷貝。

兩份各自看起來都對，**卻沒有任何測試斷言它們相等**：改一份（例如把
`_是模組層常數替換` 那個空覆蓋特例的條件放寬），另一份照樣綠，症狀就是
「體檢說過、CI 說 WRONG_TEST」——回饋提早了，卻提早給了一個不算數的答案。

這支測試守的是**機制**：`_覆蓋率前置` 不准自己知道那幾行怎麼算，得去問
`要求覆蓋的行`。機制成立，兩份相等就是結構上的事實，不必再逐筆比對 143 筆。

作法照 `tests/單元/test_派法只有一份.py` 的先例：把被依賴的那份換成間諜，
看它有沒有被問。間諜記下問題後直接丟哨兵，**問到就停在那裡**——所以
`_覆蓋率前置` 若是自己算完就往下跑，這支會在「開 coverage 子程序」那一步
被擋下並指名。這裡一個 coverage 子程序都不開。
"""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Never, NoReturn

import pytest

from . import 執行器
from .登記 import 登記, 變異

專案根目錄 = Path(__file__).resolve().parents[2]


class 哨兵(Exception):
    """只用來證明「有問到」的例外，不代表任何判定結果。"""


class 記下來的要求覆蓋的行:
    """假的 `要求覆蓋的行`：記下被問過的參數，然後丟哨兵停住。"""

    def __init__(self) -> None:
        """開一本空的「被問過什麼」帳。"""
        self.問過: list[tuple[Path, 變異]] = []

    def __call__(self, 目標: Path, 一筆: 變異) -> NoReturn:
        self.問過.append((目標, 一筆))
        raise 哨兵


def _第一筆會走到覆蓋這一關的() -> 變異:
    """挑一筆 Python 目標、且真的點名了 `該紅` 的登記。

    不寫死識別：寫死的話那一筆被別條線改掉，這支就跟著紅，
    而它要測的是機制，不是某一把刀。
    """
    for 一筆 in 登記:
        if 一筆.目標檔.suffix == ".py" and 一筆.該紅:
            return 一筆
    pytest.fail("登記裡沒有任何 Python 目標且有該紅的刀，這支測試的前提不成立")


def test_覆蓋率前置的必須覆蓋是問來的不是自己算的(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_覆蓋率前置` 得問 `要求覆蓋的行`，不准留第二份 if/elif 判定。"""
    一筆 = _第一筆會走到覆蓋這一關的()
    間諜 = 記下來的要求覆蓋的行()
    monkeypatch.setattr(執行器, "要求覆蓋的行", 間諜)
    monkeypatch.setattr(執行器, "_丟掉pycache", lambda *_: None)

    def _不准開子程序(*_args: object, **_kwargs: object) -> Never:
        訊息 = (
            "_覆蓋率前置 沒問過 要求覆蓋的行 就開了 coverage 子程序："
            "必須覆蓋還是自己那份 if/elif 算的，等於第二份真相"
        )
        raise AssertionError(訊息)

    monkeypatch.setattr(
        執行器,
        "subprocess",
        SimpleNamespace(run=_不准開子程序, TimeoutExpired=subprocess.TimeoutExpired),
    )

    with pytest.raises(哨兵):
        執行器._覆蓋率前置(專案根目錄, 一筆)

    assert 間諜.問過 == [(專案根目錄 / 一筆.目標檔, 一筆)]

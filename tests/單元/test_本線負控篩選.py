"""本線負控只跑「這條 diff 動過的登記檔」裡那幾把刀，選不到就不准是綠的。

篩選與判定是兩個**純函式**，住 `nova.載體.本線負控`：
`tests/conftest.py` 的 `--登記檔` 只是把 pytest 的 item 餵進去、再把 deselect 掛回去，
而閘那條規則（`registered-mutation-diff`）要拿同一份判定當證據。

住載體不住 `tests/` 的理由是機械的：`tests/` 整棵樹每一輪都會被拍快照，
實作階段動到就會被還原刪掉——把被測的東西放在那裡，它永遠等不到人來實作。
載體照樣不 import `tests.`：刀是**當參數傳進去**的（只認 `識別` 與 `來源` 兩個屬性），
「哪一把刀住哪個檔」仍然是 `tests/負控/登記.py` 收集當下記下來的知識。

**兩格都是純函式，不 fork**：`tests/單元` 是提交閘唯一的測試規則，
混一支 fork 進去就是每次 commit 都付那個錢。
"""

import importlib.util
from pathlib import Path

from nova.載體.本線負控 import 判定選到的刀, 挑出本線動過的刀
from tests.負控.登記 import 登記

_登記們目錄 = Path(__file__).resolve().parents[1] / "負控" / "登記們"
_登記們相對路徑 = "tests/負控/登記們"

#: `登記們/__init__.py` 是 package 標記，不是登記模組（同 `登記.py` 的 `_不是登記模組`）。
_不是登記模組 = frozenset({"__init__.py"})


def _挑一個真的登記檔() -> Path:
    """從硬碟上現算一個登記模組。**不手抄檔名**：抄了的話那個檔改名就恆綠。"""
    候選 = sorted(檔 for 檔 in _登記們目錄.glob("*.py") if 檔.name not in _不是登記模組)
    assert 候選, f"{_登記們相對路徑}/ 底下一個登記模組都沒有，這支測試在測空氣"
    return 候選[0]


def _這個檔登記了哪些識別(檔: Path) -> frozenset[str]:
    """直接讀那個模組的 `登記`，當篩選結果的對照組。

    右手邊不走被測的那條路（不看 `變異` 身上的來源標記），
    不然標錯來源時兩邊會一起錯、一起綠。
    """
    規格 = importlib.util.spec_from_file_location(f"本線負控試讀.{檔.stem}", 檔)
    assert 規格 is not None and 規格.loader is not None, f"{檔} 載不進來"
    模組 = importlib.util.module_from_spec(規格)
    規格.loader.exec_module(模組)
    這批 = vars(模組)["登記"]
    return frozenset(一筆.識別 for 一筆 in 這批)


def test_只選這幾個登記檔的刀_選不到就不是綠() -> None:
    """守兩件事：指名一個登記檔時只留下那個檔裡的刀；指名了檔卻選到 0 把時不是綠。

    第一格擋的是「選太多」（把全量 220 把偷偷跑進線裡）與「選太少」（漏掉刀）。
    第二格擋的是本票唯一一種看起來完美的假綠：檔名打錯、模組改名或 deselect
    邏輯壞掉時，一把都沒選到卻一路綠到 CI。訊息裡要指名是哪幾個檔選不到刀，
    只回一個 False 的話沒人看得出來要去修哪裡。
    """
    檔 = _挑一個真的登記檔()
    路徑 = f"{_登記們相對路徑}/{檔.name}"
    預期識別們 = _這個檔登記了哪些識別(檔)
    assert 預期識別們, f"{路徑} 一把刀都沒登記，這支測試在測空氣"
    assert len(預期識別們) < len(登記), "挑到的檔就是全部的刀，第一格會恆真"

    選到 = 挑出本線動過的刀(登記, (路徑,))
    assert {一筆.識別 for 一筆 in 選到} == 預期識別們, (
        f"指名 {路徑} 時選到的刀不是那個檔登記的那幾把："
        f"多了 {sorted({一筆.識別 for 一筆 in 選到} - 預期識別們)}、"
        f"少了 {sorted(預期識別們 - {一筆.識別 for 一筆 in 選到})}"
    )

    通過, 摘要 = 判定選到的刀((路徑,), ())
    assert 通過 is False, f"指名了 {路徑} 卻一把刀都沒選到，這是假綠不是綠；摘要是 {摘要!r}"
    assert 檔.name in 摘要, f"判定的摘要沒指名選不到刀的是哪個檔：{摘要!r}"

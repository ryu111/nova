"""本線負控的兩個純函式：挑刀與判定。

`registered-mutation-diff` 只跑「這條 diff 動過的登記檔」裡那幾把刀。
篩選由 `tests/conftest.py` 的 `--登記檔` 掛上 pytest 的 deselect，判定的結果當閘的證據，
**兩邊用的是這裡同一份程式**——各寫一份的話兩邊會慢慢對不起來，而症狀是假綠。

住載體不住 `tests/`：`tests/` 整棵樹每一輪都會被拍快照還原，被測的東西放那裡等不到人實作。
載體照樣不 `import tests.`：刀是**當參數傳進來**的，這裡只認 `識別` 與 `來源` 兩個屬性，
「哪一把刀住哪個檔」仍然是 `tests/負控/登記.py` 收集當下記下來的知識。
"""

from collections.abc import Iterable, Sequence
from typing import Any

# 刀的兩個屬性一律用 `getattr` 問，**型別上收 `object`**：呼叫端之一是 `tests/conftest.py`，
# 它手上的 item 參數本來就只是 `object`（不 import `tests.負控.登記` 就問不出更精確的型別）。
# 要求一個 Protocol 的話，會逼呼叫端去 cast——那是把型別麻煩推給不准 import 的那一側。


def 挑出本線動過的刀(刀們: Iterable[object], 動過的登記檔們: Sequence[str]) -> tuple[Any, ...]:
    """只留下 `來源` 落在 `動過的登記檔們` 裡的那幾把，順序照原本的。

    兩邊比的都是 repo 根的相對路徑（`tests/負控/登記們/<主題>.py`）：
    git 那側吐這種路徑，收集那側也把來源寫成這種路徑。
    """
    指名 = frozenset(動過的登記檔們)
    return tuple(刀 for 刀 in 刀們 if getattr(刀, "來源", None) in 指名)


def 判定選到的刀(動過的登記檔們: Sequence[str], 選到: Iterable[object]) -> tuple[bool, str]:
    """選到的刀算不算數，以及要印哪一句證據。

    **動過的檔非空卻一把都選不到就是紅**（fail-closed）：檔名打錯、模組改名或
    deselect 邏輯壞掉時，一把都沒跑卻一路綠到 CI，那是本票唯一一種看起來完美的假綠。
    所以那句話要指名是哪幾個檔選不到刀，不然沒人看得出來要去修哪裡。

    證據一律列出選到的 `識別` 名字：只印把數的話，選錯了一樣看不出來。
    """
    識別們 = sorted(str(getattr(一把, "識別", 一把)) for 一把 in 選到)
    if not 動過的登記檔們:
        return True, "[本線負控] 0 把（本線沒動 tests/負控/登記們/）"
    檔名單 = "、".join(sorted(動過的登記檔們))
    if not 識別們:
        return False, f"[本線負控] 這幾個登記檔一把刀都選不到（是假綠不是綠）：{檔名單}"
    return True, f"[本線負控] {len(識別們)} 把（來自 {檔名單}）：{'、'.join(識別們)}"

"""重構員不准動測試。**這條要是機械的。**

`迴圈/角色提示.py` 的重構員第一條規矩就寫著「不准改任何測試檔」——
但那句話在**提示**裡，模型可以忽略它，而且忽略了沒有人會發現：
測試被改掉之後跑出來還是綠的。CLAUDE.md 的判準是「規則寫在 prompt 裡
是虛線的懇求，寫在包住執行者的程式碼裡才是實線的包圍環」。

## 判準是「跑之前 vs 跑之後」，不是「模型說它沒改」

拍兩張快照比對。**新增與刪除都算**：刪掉一支測試是最嚴重的那種，
而它在「逐檔比對內容」裡長得像什麼都沒發生。

同一條判準養出兩格護欄，共用 `_動過的檔`：`動到測試了嗎`（動測試檔了沒）
與 `跑出範圍了嗎`（把手伸到指名的模組外面了沒）。

住載體不住契約：「哪些路徑算測試」是這個 repo 的知識，
而且拍快照要碰硬碟。比對本身是純函式，所以測得動。
"""

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path

#: 這些路徑底下的東西都算測試。**`conftest.py` 不是 `test_` 開頭**，
#: 但動它等於動了每一支測試，所以判準是「在不在 tests/ 底下」，
#: 不是「檔名長什麼樣」。
測試根 = "tests"


class 測試檔快照能力:
    """拍測試摘要並保管可供還原的內容。

    迴圈只拿到路徑與雜湊，原始位元組留在這個載體物件裡；因此退回測試員時，
    不必把測試內容放進迴圈的軌跡或區域變數。`__call__` 是舊呼叫端把它當
    `拍快照` 函式使用時的相容形狀。
    """

    def __init__(self) -> None:
        """建立空的載體快照儲存。"""
        self._內容: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, bytes]] = {}

    @staticmethod
    def _鍵(根目錄: Path, 快照: Mapping[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
        return str(根目錄.resolve()), tuple(sorted(快照.items()))

    @staticmethod
    def _讀出測試檔們(根目錄: Path) -> dict[str, bytes]:
        """`tests/` 底下每個檔的原始位元組，鍵是相對路徑；沒有那棵樹就是空的。"""
        在哪 = 根目錄 / 測試根
        if not 在哪.is_dir():
            return {}
        return {
            str(檔.relative_to(根目錄)): 檔.read_bytes()
            for 檔 in sorted(在哪.rglob("*"))
            if 檔.is_file() and "__pycache__" not in 檔.parts
        }

    def 拍快照(self, 根目錄: Path) -> dict[str, str]:
        """把 `tests/` 底下每個檔的內容雜湊記下來，並在載體內保留原始內容。

        **摘要取雜湊不是為了防篡改**，是為了不讓比對把整棵測試樹再比一次；
        這裡不需要抗碰撞，所以取前 16 個十六進位字元就夠。
        """
        內容 = self._讀出測試檔們(根目錄)
        摘要 = {路徑: hashlib.sha256(位元組).hexdigest()[:16] for 路徑, 位元組 in 內容.items()}
        self._內容[self._鍵(根目錄, 摘要)] = 內容
        return 摘要

    def __call__(self, 根目錄: Path) -> dict[str, str]:
        """相容舊的 `拍快照(根目錄)` 呼叫。"""
        return self.拍快照(根目錄)

    def 還原(
        self,
        根目錄: Path,
        動過的測試檔: tuple[str, ...],
        前快照: Mapping[str, str],
    ) -> str | None:
        """把指定測試檔還原到快照；快照沒有的新增檔交給刪除能力處理。"""
        內容 = self._內容.get(self._鍵(根目錄, 前快照))
        if 內容 is None:
            return "找不到實作階段開始前的測試快照內容"
        try:
            for 檔 in 動過的測試檔:
                if 檔 in 內容:
                    (根目錄 / 檔).write_bytes(內容[檔])
                    continue
                失敗 = self.刪掉新增的測試檔(根目錄, (檔,))
                if 失敗 is not None:
                    return 失敗
            未還原 = tuple(檔 for 檔 in 動過的測試檔 if not _還原到位了(根目錄 / 檔, 內容.get(檔)))
        except OSError as 錯:
            return str(錯)
        if 未還原:
            return f"仍有檔案未還原：{'、'.join(未還原)}"
        return None

    def 刪掉新增的測試檔(self, 根目錄: Path, 檔案們: tuple[str, ...]) -> str | None:
        """刪掉快照裡不存在、由違規階段新增的測試檔。"""
        try:
            for 檔 in 檔案們:
                (根目錄 / 檔).unlink(missing_ok=True)
        except OSError as 錯:
            return str(錯)
        未刪除 = tuple(檔 for 檔 in 檔案們 if (根目錄 / 檔).exists())
        return f"仍有新增測試檔未刪除：{'、'.join(未刪除)}" if 未刪除 else None


def _還原到位了(檔: Path, 前內容: bytes | None) -> bool:
    """這個檔回到快照的樣子了嗎？

    **快照裡沒有的（違規階段新增的）算「回到樣子」是它不存在**——寫回空內容
    不算還原，那會留下一支多出來的測試檔。
    """
    if 前內容 is None:
        return not 檔.exists()
    return 檔.is_file() and 檔.read_bytes() == 前內容


def 建立測試檔快照能力() -> 測試檔快照能力:
    """建立一輪工作流專用的測試檔快照能力。"""
    return 測試檔快照能力()


# 相容舊呼叫端（如單元／整合測試與命令列的單節點重構）。
拍測試快照 = 建立測試檔快照能力()
拍快照 = 拍測試快照

#: 拍全樹時跳過的目錄。**不是為了乾淨，是為了跑得完**——
#: `.venv` 與 `.git` 各有幾萬個檔，每次重構前後各拍一次要等到天荒地老。
#: 這些目錄底下的東西也不該算「重構員動的」：它們是工具的產物。
不拍的目錄 = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tox",
        "dist",
        "build",
        ".eggs",
    }
)


def 拍全樹快照(根目錄: Path) -> dict[str, str]:
    """整棵樹的內容雜湊。**範圍護欄要用這個，不是 `拍測試快照`。**

    `跑出範圍了嗎` 問的是「有沒有動到範圍外的檔」，而範圍通常指的是
    `src/` 底下的某幾格——只拍 `tests/` 的話那個問題**永遠回答不了**：
    快照裡根本沒有那些檔，差集是空的，護欄放行。

    **那是最貴的那種假綠**：測試綠、閘綠、護欄在，但它守不到任何東西。
    """
    return {
        str(檔.relative_to(根目錄)): hashlib.sha256(檔.read_bytes()).hexdigest()[:16]
        for 檔 in sorted(根目錄.rglob("*"))
        if 檔.is_file() and not (不拍的目錄 & set(檔.relative_to(根目錄).parts))
    }


def _動過的檔(前: Mapping[str, str], 後: Mapping[str, str]) -> set[str]:
    """兩張快照之間對不起來的檔。改內容、新增、刪除都算。

    **新增與刪除是靠 `.get()` 回 `None` 落進來的**：缺席那邊的值是 `None`，
    跟另一邊的雜湊一定不相等。所以這裡不必為三種情況各寫一條分支。
    """
    return {檔 for 檔 in 前.keys() | 後.keys() if 前.get(檔) != 後.get(檔)}


def _在範圍內嗎(檔: str, 範圍節點們: Sequence[tuple[str, ...]]) -> bool:
    """這個檔在不在任一格範圍底下。

    **比路徑節點，不比字元前綴**：`src/nova/載體` 在範圍內時，
    `src/nova/載體-舊/甲.py` 的字元前綴一樣中，路徑節點不中——不放行。
    """
    節點 = tuple(Path(檔).parts)
    return any(節點[: len(一格)] == 一格 for 一格 in 範圍節點們)


def 動到測試了嗎(前: Mapping[str, str], 後: Mapping[str, str]) -> tuple[str, ...]:
    """哪幾個測試檔被動了。沒動就回空 tuple。

    **三種都算**：改內容、新增、刪除。

    - 刪除最嚴重，而且在逐檔比對裡看不見（那個鍵直接消失了）
    - 新增也算：重構員的工作是「不改行為地清乾淨」，**加測試是測試員的事**；
      放行的話它可以加一支永遠綠的測試來墊高數字

    回傳**按路徑排序**——順序不穩定的話同一次違規每次印出來不一樣，沒辦法比對。

    **非測試路徑在這裡就濾掉**，不靠呼叫端先過濾好才餵進來：
    「什麼算測試」是這個函式的知識，散到呼叫端的話，第二個呼叫端
    遲早會餵一份沒濾過的快照進來，而那時候重構改實作會被誤判成違規。
    """
    測試檔 = {檔 for 檔 in _動過的檔(前, 後) if 檔.split("/")[0] == 測試根}
    return tuple(sorted(測試檔))


def 跑出範圍了嗎(
    前: Mapping[str, str], 後: Mapping[str, str], 範圍: tuple[str, ...]
) -> tuple[str, ...]:
    """哪幾個**範圍外**的檔被動了。都在範圍內就回空 tuple。

    判準跟 `動到測試了嗎` 同一條：跑之前 vs 跑之後的快照比對，
    不是模型自己說它只動了哪些。改內容、新增、刪除都算。

    範圍怎麼算「中」見 `_在範圍內嗎`：比路徑節點，不比字元前綴。

    回傳按路徑排序，同一次違規每次印出來要長一樣。
    """
    範圍節點們 = [tuple(Path(一格).parts) for 一格 in 範圍]
    出界的 = {檔 for 檔 in _動過的檔(前, 後) if not _在範圍內嗎(檔, 範圍節點們)}
    return tuple(sorted(出界的))

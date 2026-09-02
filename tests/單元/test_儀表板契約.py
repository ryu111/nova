"""儀表板契約的**落盤形狀**：`--json` 的每一格都要從 dataclass 自己數出來。

`儀表板轉字典` 現在是照一張手寫的 `(繁中屬性, ASCII 鍵)` 對照表走的。
那張表是單一來源沒錯，**但它跟 dataclass 之間沒有人在對**：

* 契約上加一欄、對照表忘了加 → 那一格**安靜地不落盤**。
  `--json` 的下游拿到的是一份「看起來完整」的 JSON，
  少的那一格不會有任何錯誤訊息，因為誰也不知道它本來該在那裡。
* 測試那邊只跟**另一份手寫的 ASCII 鍵集合**對——兩份手寫的表一起漏一格，
  兩邊還是相等的。第二份意見跟第一份出自同一隻手的話，它不是第二份意見。

所以這一支只問一件事：**對照表覆蓋不覆蓋得完 `dataclasses.fields()`**，
覆蓋不完的時候會不會**當場炸**。靜默少一格是這裡唯一不准發生的事。

這個檔同時是「落盤有哪幾格」在測試那頭的**唯一來源**（`_契約說的落盤鍵樹`）。
在這之前 `test_儀表板資料.py` 與 `test_儀表板命令.py` 各手寫了一份一模一樣的
ASCII 鍵集合，等於在契約的對照表之外又長出兩份 schema：三份要同時改才會綠，
而三份都出自同一隻手——一起漏一格的時候三邊還是相等的，
**沒有人在對的那一格就是會不見的那一格**。

純資料，不碰世界，所以住單元層。
"""

from dataclasses import fields, is_dataclass, replace
from typing import Any

import pytest

import nova.契約.儀表板 as 儀表板契約
from nova.契約.儀表板 import (
    一家用量,
    一條線,
    一階,
    儀表板,
    儀表板轉字典,
    失敗碼,
    帳本可見度,
    收件匣,
    負控覆蓋,
    退出碼分佈,
)
from nova.契約.遮罩 import 已經遮過了


def _一份填滿的() -> 儀表板:
    """**每一格的值都不一樣**：值撞在一起的話，對錯格也看不出來。"""
    return 儀表板(
        產生時間="2026-09-02T10:05:00+00:00",
        工作目錄="/工作區/專案",
        目前commit="a" * 40,
        總token=101,
        總成本美金=1.25,
        算不出成本的執行數=102,
        呼叫次數=103,
        繞過次數=104,
        在跑的線=105,
        退出碼=退出碼分佈(成功=201, 確定失敗=202, 未知=203, 護欄=204, 其他=205),
        收件匣=收件匣(等著=301, 處理中=302, 已完成=303, 讀不動=304),
        工作樹數=106,
        線們=(
            一條線(
                名字="線甲",
                路徑="/工作區/線甲",
                票標題=已經遮過了("修好收件匣", 因為="測試資料，本來就沒有祕密"),
                目前階段="test",
                在跑嗎=True,
                跑了幾秒=401,
                啟動時間="2026-09-02T09:30:00+00:00",
                退出碼=402,
                護欄原因=已經遮過了("動了測試檔", 因為="測試資料，本來就沒有祕密"),
                未提交檔案數=403,
                七階=(一階(階段="實作", 終局="綠", 判準綠=True),),
            ),
        ),
        各家=(一家用量(供應商="claude", 次數=501, token=502, 佔比=0.25, 平均每次=503),),
        可見度=帳本可見度(
            本專案token=601,
            全部token=602,
            專案鍵總數=603,
            有內容的專案鍵=604,
            跳過的檔=605,
        ),
        失敗碼們=(失敗碼(代碼="quota_exhausted", 次數=701),),
        負控=負控覆蓋(登記檔數=801, 紀錄檔數=802, 閘規則數=803, 階段數=804),
    )


def _契約說的落盤鍵樹() -> dict[str, Any]:
    """契約自己說得出落盤長什麼形狀：ASCII 鍵 → 那一格底下的鍵樹。

    被釘的介面（實作還不存在，所以這幾支現在是紅的）::

        from nova.契約.儀表板 import 落盤鍵樹
        落盤鍵樹()["inbox"]["waiting"] == {}          # 純量是空的
        落盤鍵樹()["lanes"]["stages"]["gate_green"]   # 序列給的是「元素」的樹

    **不帶參數**是重點：鍵樹是契約的形狀，不是某一份儀表板的形狀。
    今天沒有線在跑、帳本還沒有失敗碼的時候，`lanes`／`failure_codes` 底下
    有哪幾格照樣說得出來——測試（與之後要標來源的模板）才有得對，
    不必自己再手寫一份。

    在函式裡 import 而不是 module 層：這個名字還沒長出來的那一刻，
    module 層的 import 會讓 pytest **在收集期就 ERROR**，
    整個檔一支都不跑（`判準.py` 把那個退出碼收成「結果未知」）——
    紅要紅在測試函式裡，才數得出是哪一支在紅。
    """
    from nova.契約.儀表板 import 落盤鍵樹

    return 落盤鍵樹()


def _這份落盤的鍵樹(值: object) -> dict[str, Any]:
    """從真的落盤過一次的那份 dict 抽出形狀。序列抽的是它元素的形狀。

    序列的元素**一層一層併**（不是後面蓋前面）：三條線裡只有一條問得到七階的話，
    `lanes.stages` 底下有哪幾格就靠那一條說出來。蓋過去的話它會被空的那兩條抹掉。
    """
    if isinstance(值, dict):
        return {str(鍵): _這份落盤的鍵樹(內) for 鍵, 內 in 值.items()}
    if isinstance(值, list):
        出: dict[str, Any] = {}
        for 內 in 值:
            for 鍵, 子 in _這份落盤的鍵樹(內).items():
                出[鍵] = {**出.get(鍵, {}), **子}
        return 出
    return {}


def _對不上的鍵層(這次: dict[str, Any], 契約: dict[str, Any], 路徑: str = "頂層") -> list[str]:
    """這次落盤的每一層，跟契約說的那一層是不是同幾格。回空的代表層層對得上。

    **這次是空的那一層不算對不上**：純量底下本來就沒有東西，
    而「今天一條線都沒有七階」跟「契約上沒有七階」是兩件事——
    真的跑一次 CLI 拿到的那份，本來就不保證每一層都有內容
    （形狀本身由 `Test落盤的形狀只有契約說得算` 那兩支釘住）。
    """
    if not 這次:
        return []
    問題: list[str] = []
    if set(這次) != set(契約):
        問題.append(
            f"{路徑}：落盤是 {sorted(這次)}，契約說的是 {sorted(契約)}"
            f"（差在 {sorted(set(這次) ^ set(契約))}）"
        )
    問題.extend(
        一句
        for 鍵, 子 in 這次.items()
        for 一句 in _對不上的鍵層(子, 契約.get(鍵, {}), f"{路徑}.{鍵}")
    )
    return 問題


def _數格子(樹: dict[str, Any]) -> int:
    """整棵樹上總共幾格（每一層都算）。"""
    return len(樹) + sum(_數格子(子) for 子 in 樹.values())


def _契約上的每一個dataclass() -> list[type]:
    """契約這個模組自己定義的每一個 dataclass。**名單從模組裡數，不手寫。**"""
    return [
        值
        for 值 in vars(儀表板契約).values()
        if isinstance(值, type) and is_dataclass(值) and 值.__module__ == 儀表板契約.__name__
    ]


def _對得起來(物: object, 圖: object, 路徑: str = "儀表板") -> list[str]:
    """一層一層問：dataclass 有幾欄，落盤就要有幾格，而且是同幾格。

    對照表照 dataclass 的欄位順序寫，所以一欄對一格；順序對不上的話，
    「少了哪一格」根本指不出來——指得出來，紅的時候才有人修得動。
    """
    問題: list[str] = []
    if is_dataclass(物) and not isinstance(物, type):
        if not isinstance(圖, dict):
            return [f"{路徑}：契約是 {type(物).__name__}，落盤卻是 {type(圖).__name__}"]
        欄們 = fields(物)
        if len(欄們) != len(圖):
            少的 = {一欄.name for 一欄 in 欄們} if len(欄們) > len(圖) else set()
            問題.append(
                f"{路徑}：{type(物).__name__} 有 {len(欄們)} 欄、落盤只有 {len(圖)} 格"
                f"（欄位：{sorted(一欄.name for 一欄 in 欄們)}；"
                f"落盤：{sorted(圖)}；對照表少的就在 {sorted(少的)} 裡）"
            )
        for 一欄, (鍵, 值) in zip(欄們, 圖.items(), strict=False):
            問題.extend(_對得起來(getattr(物, 一欄.name), 值, f"{路徑}.{一欄.name}→{鍵}"))
        return 問題
    if isinstance(物, tuple):
        if not isinstance(圖, list) or len(物) != len(圖):
            return [f"{路徑}：契約有 {len(物)} 筆，落盤是 {圖!r}"]
        return [
            一句
            for 序, (內, 值) in enumerate(zip(物, 圖, strict=True))
            for 一句 in _對得起來(內, 值, f"{路徑}[{序}]")
        ]
    if 物 != 圖:
        問題.append(f"{路徑}：契約上是 {物!r}，落盤變成 {圖!r}")
    return 問題


class Test落盤的格數就是契約的欄數:
    """**兩份手寫的表對得起來，不代表對得起契約。**"""

    def test_每一層的每一欄都落得了盤(self) -> None:
        沒對上的 = _對得起來(_一份填滿的(), 儀表板轉字典(_一份填滿的()))

        assert not 沒對上的, "落盤的形狀對不起契約：\n" + "\n".join(
            f"  {一句}" for 一句 in 沒對上的
        )

    def test_契約多一欄而對照表沒跟上就要當場炸(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """契約長出一欄、對照表忘了加——`--json` 會**靜默少一格**。

        下游拿到的是一份看起來完整的 JSON：沒有例外、沒有警告，
        只是那一個數字從此不見了。**沒有人記得它本來在那裡**，
        所以也沒有人會去找它。少一格就要炸在寫的人臉上，不是讀的人臉上。

        這裡拿掉一列對照當作「契約多一欄」的等價情形（同一個差距、方向相反）。
        """
        monkeypatch.setattr(儀表板契約, "_欄位對照", 儀表板契約._欄位對照[:-1])

        with pytest.raises((KeyError, ValueError, AssertionError)):
            儀表板轉字典(_一份填滿的())

    def test_巢狀那幾層漏一格也要當場炸(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """頂層看得出來，巢狀那幾層更看不出來：`inbox` 少一格照樣是一個 dict。"""
        子對照 = 儀表板契約._子對照
        monkeypatch.setattr(儀表板契約, "_子對照", {**子對照, 收件匣: 子對照[收件匣][:-1]})

        with pytest.raises((KeyError, ValueError, AssertionError)):
            儀表板轉字典(_一份填滿的())

    def test_序列是空的時候元素型別的對照表照樣要驗(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """**fail-closed 不准取決於當次資料有沒有內容。**

        `線們`／`各家`／`失敗碼們` 空的那天（沒有線在跑、帳本還沒有失敗碼），
        元素那幾個 dataclass 根本不會被走到，對照表漏的那一格就沒人在對。
        等到有資料的那天，少的那一格會**安靜地不落盤**——而它偏偏是
        「今天真的出事了」那份 JSON。今天沒有那筆資料，不代表那張表是對的。
        """
        空的 = replace(_一份填滿的(), 線們=(), 各家=(), 失敗碼們=())
        原表 = 儀表板契約._子對照

        for 型 in (一條線, 一階, 一家用量, 失敗碼):
            monkeypatch.setattr(儀表板契約, "_子對照", {**原表, 型: 原表[型][:-1]})

            with pytest.raises((KeyError, ValueError, AssertionError)):
                儀表板轉字典(空的)

    def test_空序列缺少元素型別對照表也要當場炸(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """序列沒有資料時，整個元素型別的對照表也不准靜默消失。"""
        空的 = replace(_一份填滿的(), 各家=())
        子對照 = 儀表板契約._子對照
        少一型 = {型: 對照 for 型, 對照 in 子對照.items() if 型 is not 一家用量}
        monkeypatch.setattr(儀表板契約, "_子對照", 少一型)

        with pytest.raises((KeyError, ValueError, AssertionError)):
            儀表板轉字典(空的)


class Test三值在落盤上分得出來:
    """`None` 照樣要落盤——**鍵不見了跟值是 `null`，下游分不出來**。"""

    def test_查不到的格子落成null而不是整格不見(self) -> None:
        一份 = _一份填滿的()
        查不到的 = replace(一份, 總成本美金=None, 目前commit=None)

        圖: dict[str, Any] = 儀表板轉字典(查不到的)

        assert set(圖) == set(儀表板轉字典(一份)), "`None` 的格子整格不落，下游會以為沒有這一格"
        assert 圖["cost_usd"] is None
        assert 圖["head"] is None


class Test落盤的形狀只有契約說得算:
    """**「儀表板有哪幾格」只准說一次。**

    這句話原本在三個地方各寫了一次：契約的 `_欄位對照`／`_子對照`、
    `test_儀表板資料.py` 的 `_頂層鍵`、`test_儀表板命令.py` 的 `_頂層鍵`
    加一張「哪個鍵是哪個 dataclass」的手抄表。三份手抄的東西不是三份意見，
    它們出自同一隻手：契約長出一欄而三邊一起漏，三邊照樣相等，
    **那一格就從 `--json` 上安靜地消失**，下游連自己少了什麼都不知道。

    所以契約要自己說得出落盤的形狀（`落盤鍵樹()`），測試只准問它。
    """

    def test_鍵樹就是那一份落盤真正的形狀(self) -> None:
        """契約說的形狀，跟 `儀表板轉字典` 實際吐出來的形狀，逐層要一樣。

        說一套做一套的話，鍵樹會變成第四份手抄本——比原本那三份更糟，
        因為它掛著「契約自己說的」這個名字。
        """
        assert _契約說的落盤鍵樹() == _這份落盤的鍵樹(儀表板轉字典(_一份填滿的())), (
            "契約說的落盤形狀跟它真的落出來的那份對不起來"
        )

    def test_鍵樹蓋滿契約上每一個dataclass的每一欄(self) -> None:
        """整棵樹的格數 ＝ 契約上每一個 dataclass 的欄數總和。

        上面那支比的是「這次落盤的形狀」，所以**整層不見會一起不見**：
        `lanes` 底下的 `stages` 從對照表消失，落盤那份也就沒有那一層，
        兩邊還是相等的。這一支的分母從模組裡自己數（`fields()` × 每一個
        dataclass），少掉一整層就對不起來——這是這份形狀唯一的外部意見。
        """
        應該有幾格 = sum(len(fields(型)) for 型 in _契約上的每一個dataclass())

        assert _數格子(_契約說的落盤鍵樹()) == 應該有幾格, (
            f"契約上總共 {應該有幾格} 欄，鍵樹只說得出 {_數格子(_契約說的落盤鍵樹())} 格"
        )

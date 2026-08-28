"""可抽換的兩個形狀：腦（語言模型）與角色。

用 `Protocol`（結構型）不用基底類別：只要形狀對就能替換，被替換的那方
不必知道我們存在。這是 `軟體工程.md` 的多型條目，也是 mypy strict 唯一
能機械檢查「里氏替換」與「介面隔離」的方式。
"""

from pathlib import Path as 路徑
from typing import Protocol, runtime_checkable

from nova.契約.模型回應 import 回應


@runtime_checkable
class 語言模型(Protocol):
    """一顆腦。提示進去、結構化證據出來。

    這是 nova 對「llm」的全部要求——刻意做到最小，因為介面的基準形狀是
    本地模型（只有腦），不是自帶一整套載體的 claude／codex／agy。
    """

    名稱: str

    def 詢問(
        self,
        提示: str,
        *,
        模型: str | None = ...,
        工作目錄: 路徑 | None = ...,
        逾時秒: float = ...,
    ) -> 回應:
        """問一次，回結構化證據。"""
        ...


@runtime_checkable
class 角色(Protocol):
    """一個固定身分的執行者：固定的系統提示 ＋ 一顆可換的腦。

    「角色」是身分不是腦——換腦不換角色，這就是宿主反轉在這一層的樣子。
    """

    名稱: str

    def 做(self, 提示: str, *, 工作目錄: 路徑 | None = ...) -> 回應:
        """以這個角色的身分做一件事。"""
        ...

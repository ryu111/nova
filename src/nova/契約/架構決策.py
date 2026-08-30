"""系統架構師輸出的可驗證架構決策契約。"""

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

from nova.契約.節點 import 停止政策, 節點識別碼, 結果代碼, 結構識別碼, 證據項


class 工作流代碼(StrEnum):
    """架構決策所針對的工作流。"""

    TDD = "tdd"
    研究 = "research"


class 架構決策問題代碼(StrEnum):
    """架構決策不能交給計畫員的原因。"""

    缺來源 = "missing-source"
    缺停止政策 = "missing-stop-policy"
    不存在節點契約 = "unknown-node-contract"
    出口未窮舉 = "incomplete-outcomes"
    未決實驗不完整 = "incomplete-experiment"
    節點規格矛盾 = "contradictory-node-spec"


@dataclass(frozen=True, slots=True)
class 未決實驗:
    """尚未能由研究證據裁決的實驗。"""

    問題: str
    指令: tuple[str, ...]
    觀察: str
    勝負判準: str
    #: 沒有期限的未決項目會永遠卡在架構決策裡。
    到期: str = ""
    #: 沒有驗證方式就無法把實驗結果收斂回架構決策。
    驗證方式: str = ""


@dataclass(frozen=True, slots=True)
class 節點規格:
    """架構決策中的一個節點契約。"""

    節點: 節點識別碼
    輸入結構: 結構識別碼
    輸出結構: 結構識別碼
    允許結果: tuple[結果代碼, ...]
    停止: 停止政策 | None
    需要權限: str
    可否扇出: bool


@dataclass(frozen=True, slots=True)
class 架構決策:
    """研究證據轉成的節點、出口、停止與未決實驗資料。

    `節點=()` 是合法的空決策，表示研究證據裁定這次不需要執行節點；
    停止政策只適用於實際列出的節點。
    """

    依據: tuple[證據項, ...]
    工作流: 工作流代碼
    節點: tuple[節點規格, ...]
    #: 允許結果表的版本號；各節點的出口窮舉在 `節點規格.允許結果`。
    出口表版本: int
    未決: tuple[未決實驗, ...]
    風險: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class 架構決策問題:
    """驗證架構決策時發現的一個問題。"""

    代碼: 架構決策問題代碼


def 驗證架構決策(
    決策: 架構決策,
    *,
    可用節點契約: Collection[節點識別碼] | None = None,
) -> tuple[架構決策問題, ...]:
    """拒絕不能交給計畫員的架構決策。

    `可用節點契約` 是呼叫端明傳的有限清單，不在這裡偷建全域註冊表；未提供時，
    驗證器只跳過「存在性」這一項，其他完整性檢查仍照做。空節點是合法的空決策，
    不會被當成缺少停止政策。
    """
    問題們: list[架構決策問題] = []
    if not 決策.依據:
        問題們.append(架構決策問題(代碼=架構決策問題代碼.缺來源))
    if any(規格.停止 is None for 規格 in 決策.節點):
        問題們.append(架構決策問題(代碼=架構決策問題代碼.缺停止政策))
    if 可用節點契約 is not None:
        已知節點契約 = frozenset(可用節點契約)
        if any(規格.節點 not in 已知節點契約 for 規格 in 決策.節點):
            問題們.append(架構決策問題(代碼=架構決策問題代碼.不存在節點契約))
    所有結果 = frozenset(結果代碼)
    if any(
        len(規格.允許結果) != len(所有結果) or frozenset(規格.允許結果) != 所有結果
        for 規格 in 決策.節點
    ):
        問題們.append(架構決策問題(代碼=架構決策問題代碼.出口未窮舉))
    if any(not _未決實驗完整(實驗) for 實驗 in 決策.未決):
        問題們.append(架構決策問題(代碼=架構決策問題代碼.未決實驗不完整))
    節點識別碼們 = tuple(規格.節點 for 規格 in 決策.節點)
    if len(set(節點識別碼們)) != len(節點識別碼們):
        問題們.append(架構決策問題(代碼=架構決策問題代碼.節點規格矛盾))
    return tuple(問題們)


def _非空文字(值: object) -> bool:
    return isinstance(值, str) and bool(值.strip())


def _未決實驗完整(實驗: 未決實驗) -> bool:
    return (
        _非空文字(實驗.問題)
        and isinstance(實驗.指令, tuple)
        and bool(實驗.指令)
        and all(_非空文字(指令) for 指令 in 實驗.指令)
        and _非空文字(實驗.觀察)
        and _非空文字(實驗.勝負判準)
        and _非空文字(實驗.到期)
        and _非空文字(實驗.驗證方式)
    )

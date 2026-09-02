"""一次決定一個專案的工作根目錄與所有狀態落點。"""

from dataclasses import dataclass, field
from pathlib import Path

from nova.載體.已處理 import 已處理目錄
from nova.載體.帳本 import 預設帳本目錄
from nova.載體.收件 import 收件目錄
from nova.載體.顧問 import 顧問目錄


@dataclass(frozen=True, slots=True)
class 專案執行脈絡:
    """同一次執行共用的專案鍵與六個狀態路徑。"""

    根目錄: Path
    收件: Path = field(init=False)
    處理中: Path = field(init=False)
    帳本: Path = field(init=False)
    已處理: Path = field(init=False)
    鎖: Path = field(init=False)
    #: 診斷素材落這裡，**不落在工作目錄**：它是要被餵回模型的東西。
    顧問: Path = field(init=False)

    def __post_init__(self) -> None:
        """把所有狀態路徑固定在同一個專案鍵下。"""
        根 = self.根目錄.resolve()
        收件 = 收件目錄(根)
        已處理 = 已處理目錄(根)
        object.__setattr__(self, "根目錄", 根)
        object.__setattr__(self, "收件", 收件)
        object.__setattr__(self, "處理中", 收件 / "處理中")
        object.__setattr__(self, "帳本", 預設帳本目錄(根))
        object.__setattr__(self, "已處理", 已處理)
        object.__setattr__(self, "鎖", 已處理.parent / "工作流.鎖")
        object.__setattr__(self, "顧問", 顧問目錄(根))


def 建專案執行脈絡(工作目錄: str | Path | None = None) -> 專案執行脈絡:
    """依工作目錄建立不可變的專案執行脈絡。"""
    根 = Path(工作目錄) if 工作目錄 else Path.cwd()
    return 專案執行脈絡(根)

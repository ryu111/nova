"""額度契約：限額視窗、家族額度與額度快照之資料結構。"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nova.載體.額度 import 快取資料型

_代碼轉家名: dict[str, str] = {
    "cx": "codex",
    "ay": "agy",
    "cl": "claude",
}


@dataclass(frozen=True)
class 視窗:
    """單一時間視窗的限額狀態。"""

    標籤: str
    用掉百分比: int
    重置於: int


@dataclass(frozen=True)
class 家族額度:
    """單一模型家族之額度狀態。"""

    家: str
    視窗們: tuple[視窗, ...]
    失敗原因: str | None = None
    #: **這一家自己的**時戳（epoch 秒）；快取裡沒寫就退回全域 `ts`。
    #: 只有一個全域 `ts` 的話，只寫得到 `cl` 的那條路會把 cx／ay 也刷成新鮮的——
    #: 那是安靜地拿舊數字當新數字用。
    時間: int = 0


@dataclass(frozen=True)
class 額度快照:
    """額度快照。"""

    時間: int
    家族們: tuple[家族額度, ...]


def 快取轉快照(快取: "快取資料型 | Mapping[str, Any]") -> 額度快照:
    """將 ASCII 欄位之快取資料轉為額度快照契約物件。"""
    家族清單: list[家族額度] = []
    全域ts = int(快取["ts"])
    for 家族 in 快取.get("families", []):
        家名 = _代碼轉家名.get(家族["family"], 家族["family"])
        視窗元組 = tuple(
            視窗(
                標籤=str(窗["label"]),
                用掉百分比=int(窗["used_percent"]),
                重置於=int(窗["resets_at"]),
            )
            for 窗 in 家族.get("windows", [])
        )
        家族清單.append(
            家族額度(
                家=家名,
                視窗們=視窗元組,
                失敗原因=None,
                # 舊快取沒有每家的 `ts`，退回全域的——讀得回來比讀得漂亮重要。
                時間=int(家族.get("ts", 全域ts)),
            )
        )
    return 額度快照(時間=全域ts, 家族們=tuple(家族清單))

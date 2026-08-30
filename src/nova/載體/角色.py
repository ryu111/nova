"""角色的唯一實作：固定系統提示 ＋ 可換的腦（組合，不繼承）。

只有一個實作，所以不寫工廠、不寫抽象基底——`寫程式.md` 的階梯。
出現第二種角色（例如需要多輪對話的）再談抽象。
"""

from dataclasses import dataclass
from pathlib import Path

from nova.契約.模型回應 import 回應
from nova.契約.角色 import 呼叫選項, 權限, 語言模型, 預設逾時秒

_分隔 = "\n\n---\n\n"


def 組提示(系統提示: str, 使用者提示: str) -> str:
    """把角色身分與這次的任務併成一段。

    為什麼用併的、不用各家的 system prompt 旗標：**只有 claude 有
    `--system-prompt`**，codex 與 agy 查不到對應旗標（見設計文件 02）。
    走最小公倍數，三家收到的東西才一樣——換腦但行為一樣。
    """
    if not 系統提示.strip():
        return 使用者提示
    return f"{系統提示}{_分隔}{使用者提示}"


@dataclass(frozen=True, slots=True)
class 固定提示角色:
    """一個角色。`系統提示` 是它的身分，`腦` 隨時可換。"""

    名稱: str
    系統提示: str
    腦: 語言模型
    模型: str | None = None
    思考深度: str | None = None
    逾時秒: float = 預設逾時秒
    #: 這個角色能動到什麼。測試員與審查員唯讀就夠，只有實作員需要可編輯。
    權限: 權限 = 權限.唯讀
    #: 給派工者看的描述，用來判斷什麼時候輪到這個角色。
    什麼時候派我: str = ""

    def 做(self, 提示: str, *, 工作目錄: Path | None = None) -> 回應:
        """做一件事，回結構化證據。"""
        return self.腦.詢問(
            組提示(self.系統提示, 提示),
            選項=呼叫選項(
                模型=self.模型,
                思考深度=self.思考深度,
                工作目錄=工作目錄,
                逾時秒=self.逾時秒,
                權限=self.權限,
            ),
        )

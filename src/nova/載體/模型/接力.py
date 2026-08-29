"""接力：一串腦，前一顆失敗就換下一顆。

`接力腦` 本身也是一顆腦（實作 `語言模型`），所以它可以被 `角色` 持有，
也可以被套進另一條鏈——組合，不是繼承。

**最關鍵的一條規則**：能不能換下一顆，要看**權限**。

| 上一顆的終局 | 唯讀 | 可編輯 |
|---|---|---|
| 成功 | 不用換 | 不用換 |
| 確定失敗（請求沒出門） | 換 | 換 |
| **結果未知**（可能做了一半） | **換** | **不換** |

唯讀沒有副作用可以重做；可編輯可能已經改了檔案，換一顆就是做第二次。
這就是 at-most-once：寧漏不重。
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from nova.契約.模型回應 import 回應, 用量, 終局
from nova.契約.角色 import 呼叫選項, 權限, 語言模型, 預設選項

_證據上限 = 3000


def 可以換下一顆(終: 終局, 可以做什麼: 權限) -> bool:
    """上一顆這樣收場，可以換下一顆重做嗎？

    純函式，這是整個接力的判斷核心——它錯了，重試就會重做副作用。
    """
    if 終 is 終局.確定失敗:
        return True
    if 終 is 終局.結果未知:
        return 可以做什麼 is 權限.唯讀
    return False


@dataclass(frozen=True, slots=True)
class 接力腦:
    """一串腦。照順序試，第一顆成功就停。"""

    名稱: str
    腦們: tuple[語言模型, ...]

    def __post_init__(self) -> None:
        """空的鏈會回一個假的成功——當場擋掉。"""
        if not self.腦們:
            訊息 = "接力腦至少要有一顆腦"
            raise ValueError(訊息)

    def 詢問(self, 提示: str, *, 選項: 呼叫選項 = 預設選項) -> 回應:
        """照順序試，回第一個成功的；全掛就回最後一顆並附上試過誰。

        **回傳的用量是整條鏈的總和，不是最後一顆的。** 只回最後一顆的話，
        前面幾顆燒掉的 token 在預算裡憑空消失——而 `迴圈/工作流.py` 的
        token 上限就靠這個數字累計。**算錯的上限也是成本漏洞。**
        """
        試過: list[str] = []
        花過: list[用量] = []
        答 = self.腦們[0].詢問(提示, 選項=選項)
        for 序, 腦 in enumerate(self.腦們):
            if 序:  # 第一顆在迴圈外先跑了
                答 = 腦.詢問(提示, 選項=選項)
            花過.append(答.用量)
            if 答.終局 is 終局.成功:
                return replace(答, 用量=_加總用量(花過))
            試過.append(f"{腦.名稱}:{答.失敗代碼.value}")
            if not 可以換下一顆(答.終局, 選項.權限):
                break
        return replace(
            答,
            文字=f"[接力 {' → '.join(試過)}] {答.文字}"[:_證據上限],
            用量=_加總用量(花過),
        )


def _加總用量(花過: Sequence[用量]) -> 用量:
    """把鏈上每一顆的用量加起來。

    **有一顆給不出來的欄位就整個不給**（`成本美金`、`快取讀取token`、`思考token`）。
    CLAUDE.md：不准為了讓三家對稱而自己估算——只有 claude 給成本，
    把「claude 那顆的成本」當成「整條鏈的成本」是低報，
    而**低報的成本比沒有成本更危險，它看起來像個數字**。

    token 數三家都給，所以直接加。
    """
    if len(花過) == 1:
        return 花過[0]

    def 全有才加(取: str) -> int | None:
        值們 = [getattr(用, 取) for 用 in 花過]
        return None if any(值 is None for 值 in 值們) else sum(值們)

    成本們 = [用.成本美金 for 用 in 花過]
    return 用量(
        輸入token=sum(用.輸入token for 用 in 花過),
        輸出token=sum(用.輸出token for 用 in 花過),
        快取讀取token=全有才加("快取讀取token"),
        思考token=全有才加("思考token"),
        成本美金=None if any(本 is None for 本 in 成本們) else sum(成本們),  # type: ignore[arg-type]
    )

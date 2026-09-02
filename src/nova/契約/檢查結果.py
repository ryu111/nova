"""一條規則跑完之後，往下游送的東西長什麼樣。

規格 §4.3 節點三原則之二：邊承載結構化證據。自由段落會逼每個下游重建上游語意。
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class 檢查結果:
    """一條規則的判定。

    代碼   跨程序識別用，ASCII（CLAUDE.md 的 failure code 例外）
    名稱   給人看的中文
    通過   True 才放行
    負責層 這條紅了要去哪一層修：載體／迴圈／圖
    證據   實際輸出，不加工。回饋要具體才可行動
    等待毫秒 開跑前排了幾毫秒隊；0 ＝ 沒等。**帳本、證據、CLI 三個出口都從這一欄出**，
           不准各量各的——第二個來源遲早跟第一個對不上
    """

    代碼: str
    名稱: str
    通過: bool
    負責層: str
    證據: str
    等待毫秒: int = 0

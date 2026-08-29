"""從審查員的回覆裡讀出判定。

**為什麼要一個約定的標記，而不是叫模型「說清楚通不通過」**：
自由文字沒辦法分辨「它審完覺得可以」與「它根本沒審、只是隨口回一句沒問題」。
規格 §4.3 說跨層傳遞一律 schema 化，自由段落會逼下游重建上游語意——
這裡的下游就是狀態機，而它重建錯的後果是宣布一個假的完成。

標記走 ASCII（CLAUDE.md 的跨程序 semantic id 例外）：它要能被 grep、
被別的程式讀，而且模型對英文大寫標記的服從度比中文穩。
"""

import re

from nova.契約.工作流 import 審查判定

#: 約定的標記。角色提示會把這兩行原樣教給審查員。
判定標記 = "REVIEW:"
_值對判定 = {"PASS": 審查判定.通過, "CHANGES-REQUESTED": 審查判定.要求修改}
_樣式 = re.compile(rf"{判定標記}\s*([A-Za-z-]+)", re.IGNORECASE)


def 讀審查判定(文字: str) -> 審查判定:
    """回覆裡最後一個 `REVIEW: X`。讀不出來一律 `沒給結論`（fail-closed）。

    取**最後一個**是因為回覆裡可能先解釋格式再給判定——
    實測模型會寫「我會在最後給 REVIEW: PASS 或 REVIEW: CHANGES-REQUESTED」。
    """
    命中 = _樣式.findall(文字)
    if not 命中:
        return 審查判定.沒給結論
    return _值對判定.get(命中[-1].upper(), 審查判定.沒給結論)

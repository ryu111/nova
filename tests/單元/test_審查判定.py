"""審查員的判定要從回覆裡讀得出來，讀不出來就不准當成通過。

這支是被一次真實的假成功逼出來的：審查階段原本是「模型階段」，而模型階段的
規則是「跑完就算達到期望」——所以**審查員回「設計有重大問題，不通過」，
只要 CLI 的結束碼是 0，nova 照樣宣布「全綠且通過審查」**。

CLAUDE.md 硬規則第 4 條說不得以「模型說完成了」當停止條件。原本的實作比那還鬆：
它連模型有沒有說完成都不看，**只看子程序有沒有跑完**。
"""

import pytest

from nova.契約.工作流 import 審查判定
from nova.迴圈.審查 import 讀審查判定


class Test讀得出判定:
    def test_通過(self) -> None:
        assert 讀審查判定("看起來沒問題。\n\nREVIEW: PASS") is 審查判定.通過

    def test_要求修改(self) -> None:
        assert 讀審查判定("第 12 行的命名不清楚。\nREVIEW: CHANGES-REQUESTED") is 審查判定.要求修改

    def test_大小寫與空白都容忍(self) -> None:
        """模型不會每次都排版一致，但**判定本身不准模糊**。"""
        for 樣本 in ("review:  pass", "  REVIEW:PASS  ", "Review: Pass"):
            assert 讀審查判定(樣本) is 審查判定.通過, 樣本

    def test_取最後一個標記(self) -> None:
        """回覆裡可能先解釋格式再給判定——**算數的是最後那個**。"""
        文 = (
            "我會在最後給 REVIEW: PASS 或 REVIEW: CHANGES-REQUESTED。\n"
            "第 3 行有問題。\nREVIEW: CHANGES-REQUESTED"
        )
        assert 讀審查判定(文) is 審查判定.要求修改


class Test讀不出來一律不准當通過:
    @pytest.mark.parametrize(
        "文字",
        [
            "看起來沒問題",  # 說了好話但沒給標記
            "",
            "REVIEW: 通過",  # 標記在但值不是約定的那兩個
            "REVIEW: LGTM",
            "PASS",  # 只有值沒有標記
        ],
    )
    def test_沒給約定的判定就是沒給結論(self, 文字: str) -> None:
        """**這一格是整支測試的重點。**

        「看起來沒問題」讀起來像通過，但它不是**判定**——沒有約定的標記就沒辦法
        分辨「它審完覺得可以」與「它根本沒審、只是隨口回一句」。
        fail-closed：讀不出來一律當沒給結論，由狀態機去中止。
        """
        assert 讀審查判定(文字) is 審查判定.沒給結論

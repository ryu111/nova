"""結構化審查問題契約與剖析單元測試。

規格要求：
1. 審查問題具備穩定 id、種類（測試設計 vs 實作）、證據、狀態（未解 vs 已解）。
2. 有界數量（問題數量上限），防止審查問題無限膨脹。
3. 從審查回覆中剖析結構化問題，相同內容產生確定性穩定 id。
"""

import pytest

from nova.契約.審查問題 import (
    問題數量上限,
    問題狀態,
    問題種類,
    審查問題,
    讀審查問題列,
)


class Test審查問題契約:
    def test_審查問題基本欄位與預設狀態(self) -> None:
        問題 = 審查問題(
            識別碼="issue-001",
            種類=問題種類.測試設計,
            證據="測試案例未涵蓋空字串輸入",
        )
        assert 問題.識別碼 == "issue-001"
        assert 問題.種類 is 問題種類.測試設計
        assert 問題.種類.value == "test-design"
        assert 問題.證據 == "測試案例未涵蓋空字串輸入"
        assert 問題.狀態 is 問題狀態.未解
        assert 問題.狀態.value == "open"

    def test_問題種類包含測試設計與實作(self) -> None:
        assert 問題種類.測試設計.value == "test-design"
        assert 問題種類.實作.value == "impl"

    def test_問題狀態包含未解與已解(self) -> None:
        assert 問題狀態.未解.value == "open"
        assert 問題狀態.已解.value == "resolved"

    def test_問題數量上限為有界正整數(self) -> None:
        assert isinstance(問題數量上限, int)
        assert 1 <= 問題數量上限 <= 20


class Test讀審查問題列:
    def test_讀出測試設計問題(self) -> None:
        文字 = (
            "測試需要補強邊界斷言。\nISSUE: [test-design] 缺少空輸入測試\nREVIEW: CHANGES-REQUESTED"
        )
        問題列 = 讀審查問題列(文字)
        assert len(問題列) == 1
        assert 問題列[0].種類 is 問題種類.測試設計
        assert "缺少空輸入測試" in 問題列[0].證據
        assert 問題列[0].狀態 is 問題狀態.未解
        assert bool(問題列[0].識別碼)

    def test_讀出實作問題(self) -> None:
        文字 = (
            "實作邏輯未處理負數。\n"
            "ISSUE: [impl] 負數輸入會產生未預期的崩潰\n"
            "REVIEW: CHANGES-REQUESTED"
        )
        問題列 = 讀審查問題列(文字)
        assert len(問題列) == 1
        assert 問題列[0].種類 is 問題種類.實作
        assert "負數輸入會產生未預期的崩潰" in 問題列[0].證據

    def test_相同內容產生相同穩定識別碼(self) -> None:
        文字1 = "ISSUE: [test-design] 缺少空輸入測試\nREVIEW: CHANGES-REQUESTED"
        文字2 = "ISSUE: [test-design] 缺少空輸入測試\nREVIEW: CHANGES-REQUESTED"
        文字3 = "ISSUE: [test-design] 缺少超時測試\nREVIEW: CHANGES-REQUESTED"

        問題列1 = 讀審查問題列(文字1)
        問題列2 = 讀審查問題列(文字2)
        問題列3 = 讀審查問題列(文字3)

        assert 問題列1[0].識別碼 == 問題列2[0].識別碼
        assert 問題列1[0].識別碼 != 問題列3[0].識別碼

    def test_問題數量不超過有界上限(self) -> None:
        行們 = [f"ISSUE: [impl] 問題第 {i} 項" for i in range(問題數量上限 + 10)]
        行們.append("REVIEW: CHANGES-REQUESTED")
        文字 = "\n".join(行們)

        問題列 = 讀審查問題列(文字)
        assert len(問題列) == 問題數量上限

    def test_無結構標記時回傳空列(self) -> None:
        文字 = "看起來沒問題。\nREVIEW: PASS"
        問題列 = 讀審查問題列(文字)
        assert len(問題列) == 0

    @pytest.mark.parametrize(
        ("文字", "期望編號們", "證據們"),
        [
            # (a) 帶編號的行：編號照著行上寫的讀。
            ("ISSUE-2: [impl] 甲\nREVIEW: CHANGES-REQUESTED", (2,), ("甲",)),
            # (b) 不帶編號的舊行：用它在這段文字裡的位置補（1-based），不留空。
            (
                "ISSUE: [impl] 甲\nISSUE: [impl] 乙\nREVIEW: CHANGES-REQUESTED",
                (1, 2),
                ("甲", "乙"),
            ),
            # (c) 同一段證據換了個編號：講話的指稱換了，對帳的鍵不准跟著換。
            ("ISSUE-7: [impl] 甲\nREVIEW: CHANGES-REQUESTED", (7,), ("甲",)),
        ],
    )
    def test_ISSUE的編號讀得出來而且不進識別碼(
        self, 文字: str, 期望編號們: tuple[int, ...], 證據們: tuple[str, ...]
    ) -> None:
        """守：編號是講話用的指稱，識別碼是跨輪對帳用的鍵，兩者不准互相汙染。

        提示裡要說「第 2 條沒解」就得有一個數字可以指，所以每一條都要有編號，
        舊格式沒寫的用位置補——「這條沒有編號」不是一種可以拿去講話的狀態。
        同時識別碼只能是 `種類 ＋ 證據` 的函數：未解的條目原封帶到下一輪、
        重新編號之後仍然要算同一條問題，否則跨輪對帳當場斷掉。
        """
        問題列 = 讀審查問題列(文字)

        assert tuple(問.編號 for 問 in 問題列) == 期望編號們
        assert tuple(問.證據 for 問 in 問題列) == 證據們

        不帶編號的同一批 = 讀審查問題列("\n".join(f"ISSUE: [impl] {證據}" for 證據 in 證據們))
        assert tuple(問.識別碼 for 問 in 問題列) == tuple(問.識別碼 for 問 in 不帶編號的同一批), (
            "編號進了識別碼的雜湊：重新編一次號就等於換了一條問題"
        )

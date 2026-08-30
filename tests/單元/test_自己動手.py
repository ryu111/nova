"""自己動手之前要先說得出理由：**哪些路徑歸這條規則管。**

規則本身管不了「這件事該不該給 nova 做」——那不是機械判得出來的。
機械判得出來的是**「這個 session 有沒有記下一個決定」**，
所以把關的對象是那個記錄，不是那個判斷。

管轄範圍要窄，窄到不會擋到修 nova 自己的路：

| 路徑 | 管嗎 | 為什麼 |
|---|---|---|
| `src/nova/載體/收件.py` | **管** | 這正是該走 nova 的那種工作 |
| `tests/單元/test_某某.py` | **管** | 同上 |
| `.remember/now.md`、`.claude/settings.json` | 不管 | 開頭是 `.` 的都是工具自己的地盤 |
| repo 外面的任何檔案 | 不管 | 這條規則只在 nova 這個 repo 裡成立 |
"""

from pathlib import Path

import pytest

from nova.載體.自己動手 import 在管轄範圍嗎, 擋的話要說什麼

根 = Path("/repo")


class Test管轄範圍:
    @pytest.mark.parametrize(
        "相對路徑",
        ["src/nova/載體/收件.py", "tests/單元/test_某某.py", "docs/設計/01-機械化閘.md"],
    )
    def test_repo裡的一般檔案要管(self, 相對路徑: str) -> None:
        assert 在管轄範圍嗎(根 / 相對路徑, 根目錄=根)

    @pytest.mark.parametrize(
        "相對路徑",
        [
            ".remember/now.md",
            ".claude/settings.json",
            ".git/config",
            "docs/../.remember/x.md",
            "scratchpad/筆記.md",
            "scratchpad/temp.py",
        ],
    )
    def test_點開頭與暫存工作區的地盤不管(self, 相對路徑: str) -> None:
        """**修 nova 需要動這些**，擋下去會變成「工具壞了就修不了工具」。"""
        assert not 在管轄範圍嗎(根 / 相對路徑, 根目錄=根)

    def test_repo外面不管(self) -> None:
        """這條規則只在 nova 這個 repo 裡成立，不往外擴。"""
        assert not 在管轄範圍嗎(Path("/別的地方/x.py"), 根目錄=根)

    def test_根目錄自己不管(self) -> None:
        assert not 在管轄範圍嗎(根, 根目錄=根)


class Test擋的話要說什麼:
    def test_訊息裡要有兩條路(self) -> None:
        """**擋下來要能照做**，不然它只是個路障。

        兩條路都要給：走 nova（預設），或說得出理由自己動手。
        """
        訊息 = 擋的話要說什麼("abc-123")

        assert "nova 跑" in 訊息
        assert "nova 繞過" in 訊息
        assert "abc-123" in 訊息, "要把 session id 填好給人照抄，不然還要自己去找"

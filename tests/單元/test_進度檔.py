"""進度檔：讓一輪工作流的進度活得比程序久。

**為什麼不是帳本**：帳本刻意不記模型全文（repo public，遮罩還不存在），
它答得出「走到哪一階、花多少」，答不出「它當時做了什麼」。
下一輪要接得上，需要的正好是後者。
"""

from pathlib import Path

from nova.契約.工作流 import 任務, 步驟結果, 種類, 結束, 結束代碼, 階段代碼, 階段定義
from nova.契約.模型回應 import 終局
from nova.載體.進度 import 讀進度, 進度執行器

一件事 = 任務(描述="讓 X 變成 Y", 工作目錄=Path("/不存在但沒人會碰"))
一階 = 階段定義(
    代碼=階段代碼.測試,
    名稱="寫一支會紅的測試",
    種類=種類.模型,
    期望綠=None,
    綠=階段代碼.驗證紅,
    紅=結束(結束代碼.中止, "寫不出來"),
)


def _假執行(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
    del 定義, 任, 軌跡
    return 步驟結果(
        階段=階段代碼.測試, 終局=終局.成功, 判準綠=None, 證據="我寫了 test_某某，它現在是紅的"
    )


class Test進度要活得比程序久:
    def test_跑完一階就寫進檔案(self, tmp_path: Path) -> None:
        """**跑完就寫，不要等整輪結束**——被殺掉的那一輪正是最需要進度的一輪。"""
        檔 = tmp_path / "進度.md"
        進度執行器(_假執行, 檔)(一階, 一件事, ())
        內容 = 檔.read_text(encoding="utf-8")
        assert "test_某某" in 內容, "證據沒寫進去，下一輪就接不上"
        assert 階段代碼.測試.value in 內容, "沒寫是哪一階，接不回正確的位置"

    def test_不改結果(self, tmp_path: Path) -> None:
        """包住執行器的東西一律不准改結果——改了狀態機就走錯路。"""
        原 = _假執行(一階, 一件事, ())
        包 = 進度執行器(_假執行, tmp_path / "進度.md")(一階, 一件事, ())
        assert 包 == 原

    def test_第二階要接在後面不是蓋掉(self, tmp_path: Path) -> None:
        檔 = tmp_path / "進度.md"
        執行 = 進度執行器(_假執行, 檔)
        執行(一階, 一件事, ())
        執行(一階, 一件事, ())
        assert 檔.read_text(encoding="utf-8").count("test_某某") == 2

    def test_讀不到檔案就回空字串(self, tmp_path: Path) -> None:
        """第一輪沒有進度檔。**這不是錯誤**，不要炸。"""
        assert 讀進度(tmp_path / "沒有這個檔.md") == ""

    def test_讀得回剛寫的東西(self, tmp_path: Path) -> None:
        檔 = tmp_path / "進度.md"
        進度執行器(_假執行, 檔)(一階, 一件事, ())
        assert "test_某某" in 讀進度(檔)

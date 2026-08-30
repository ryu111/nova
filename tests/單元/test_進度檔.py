"""進度檔：讓一輪工作流的進度活得比程序久。

**為什麼不是帳本**：帳本記的全文是遮過的（有洞）而且超過上限會截斷，
它答得出「走到哪一階、花多少」，答不出「它當時做了什麼」。
下一輪要接得上，需要的正好是後者。
"""

from pathlib import Path

import pytest

from nova.契約.工作流 import (
    任務,
    出口標籤,
    步驟結果,
    種類,
    結束,
    結束代碼,
    階段代碼,
    階段定義,
)
from nova.契約.模型回應 import 終局
from nova.載體.進度 import 檢查進度檔位置, 讀進度, 進度執行器

一件事 = 任務(描述="讓 X 變成 Y", 工作目錄=Path("/不存在但沒人會碰"))
一階 = 階段定義(
    代碼=階段代碼.測試,
    名稱="寫一支會紅的測試",
    種類=種類.模型,
    期望綠=None,
    出口={
        出口標籤.綠: 階段代碼.驗證紅,
        出口標籤.結果未知: 結束(結束代碼.護欄, "結果未知"),
        出口標籤.確定失敗: 結束(結束代碼.中止, "寫不出來"),
    },
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


class Test進度檔不准住在模型動得到的地方:
    """**真跑七階段才發現的**：進度檔放在工作目錄裡，模型會往它裡面寫。

    實測（`/private/tmp/claude-501/七階段場`，重構階段給 agy）：

        進度檔在工作目錄裡  → nova 寫的段落數 2（多出來那段是模型寫的）
        進度檔在工作目錄外  → nova 寫的段落數 1

    同一階段、同一題目，只差進度檔的位置。多出來那段**格式跟 nova 寫的一模一樣**
    ——模型讀了那個檔，照抄格式接了一段自己的摘要上去。

    為什麼這不只是髒：進度檔下一輪會被當成 `前情` 餵回模型。
    **執行者可以在載體的記憶裡種東西給未來的自己看。**
    那是宿主反轉最不該破的一格——保證要住在包住執行者的程式碼裡，
    而這裡連狀態都住在執行者手上。

    修法是 fail-closed：路徑在工作目錄底下就當場拒絕，不是警告。
    警告會被忽略，而且忽略的那次剛好就是被種東西的那次。
    """

    def test_放在工作目錄裡要當場拒絕(self, tmp_path: Path) -> None:
        工作區 = tmp_path / "工作區"
        工作區.mkdir()
        with pytest.raises(ValueError, match="工作目錄"):
            檢查進度檔位置(工作區 / "進度.md", 工作區)

    def test_放在工作目錄的子目錄裡也要拒絕(self, tmp_path: Path) -> None:
        """**子目錄一樣動得到。** 只比對「同一層」等於沒擋。"""
        工作區 = tmp_path / "工作區"
        (工作區 / "深" / "更深").mkdir(parents=True)
        with pytest.raises(ValueError, match="工作目錄"):
            檢查進度檔位置(工作區 / "深" / "更深" / "進度.md", 工作區)

    def test_放在外面就放行(self, tmp_path: Path) -> None:
        工作區 = tmp_path / "工作區"
        工作區.mkdir()
        檢查進度檔位置(tmp_path / "進度.md", 工作區)

    def test_相對路徑也要判得對(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """**沒解析成絕對路徑就等於沒擋**——`./進度.md` 跟工作目錄比字串永遠不相等。"""
        工作區 = tmp_path / "工作區"
        工作區.mkdir()
        monkeypatch.chdir(工作區)
        with pytest.raises(ValueError, match="工作目錄"):
            檢查進度檔位置(Path("進度.md"), 工作區)

    def test_訊息要點名兩個路徑(self, tmp_path: Path) -> None:
        """「路徑不對」不可行動。要看得出是哪個檔跟哪個目錄撞在一起。"""
        工作區 = tmp_path / "工作區"
        工作區.mkdir()
        with pytest.raises(ValueError) as 錯:
            檢查進度檔位置(工作區 / "進度.md", 工作區)
        assert "進度.md" in str(錯.value)
        assert str(工作區) in str(錯.value)

"""工作流 runner：用假角色與假判準跑，零 LLM、零子程序、零 token。

能這樣測是因為 `執行一步` 是**參數**不是內建——高層決定形狀，低層去符合。
"""

import dataclasses
from pathlib import Path

import pytest

from nova.契約.工作流 import 任務, 步驟結果, 種類, 結束代碼, 階段代碼, 階段定義
from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.迴圈.工作流 import 建TDD執行器, 執行器, 跑工作流

一件事 = 任務(描述="讓 X 變成 Y", 工作目錄=Path("/不存在但沒人會碰"))


def _假回應(終: 終局 = 終局.成功, 文字: str = "做好了") -> 回應:
    return 回應(
        文字=文字,
        終局=終,
        失敗代碼=失敗代碼.無 if 終 is 終局.成功 else 失敗代碼.逾時,
        原始結束碼=0,
        對話識別碼=None,
        用量=用量(輸入token=1, 輸出token=1),
    )


class 假角色:
    """記下自己被叫過幾次、收到什麼提示。"""

    def __init__(self, 名稱: str, 回: 回應 | None = None) -> None:
        """名稱只是給錯誤訊息看的；`回` 讓測試決定這個角色會回什麼。"""
        self.名稱 = 名稱
        self._回 = 回 or _假回應()
        self.收到: list[str] = []

    def 做(self, 提示: str, *, 工作目錄: Path | None = None) -> 回應:
        del 工作目錄
        self.收到.append(提示)
        return self._回


def _執行器(
    判準序列: list[bool], 角色們: dict[str, 假角色] | None = None
) -> tuple[執行器, dict[str, 假角色]]:
    """判準依序回這些紅綠；角色一律成功。"""
    人 = 角色們 or {名: 假角色(名) for 名 in ("測試", "實作", "審查")}
    剩 = list(判準序列)

    def 跑判準(_: 任務) -> tuple[bool, str]:
        return (剩.pop(0) if 剩 else True), "假判準"

    return 建TDD執行器(測試=人["測試"], 實作=人["實作"], 審查=人["審查"], 跑判準=跑判準), 人


class Test順利的一輪:
    def test_五步走完就完成(self) -> None:
        執行, _ = _執行器([False, True])  # 驗證紅→真的紅、驗證綠→真的綠
        果 = 跑工作流(一件事, 執行一步=執行)
        assert 果.結束.代碼 is 結束代碼.完成
        assert [步.階段 for 步 in 果.軌跡] == [
            階段代碼.測試,
            階段代碼.驗證紅,
            階段代碼.實作,
            階段代碼.驗證綠,
            階段代碼.審查,
        ]

    def test_每個角色只被叫一次(self) -> None:
        執行, 人 = _執行器([False, True])
        跑工作流(一件事, 執行一步=執行)
        assert [len(人[名].收到) for 名 in ("測試", "實作", "審查")] == [1, 1, 1]

    def test_角色收得到上一步的證據(self) -> None:
        """Memory 欄位：只帶上一步，不重播整段歷史（context 會線性膨脹）。"""
        執行, 人 = _執行器([False, True])
        跑工作流(一件事, 執行一步=執行)
        assert "讓 X 變成 Y" in 人["實作"].收到[0]
        assert "假判準" in 人["實作"].收到[0], "實作要看得到『測試真的紅了』這件事"


class Testfallback:
    def test_驗證綠沒過會退回實作(self) -> None:
        """這就是回頭邊。第一次沒綠 → 再實作一次 → 綠了 → 審查。"""
        執行, 人 = _執行器([False, False, True])
        果 = 跑工作流(一件事, 執行一步=執行)
        assert 果.結束.代碼 is 結束代碼.完成
        assert [步.階段 for 步 in 果.軌跡] == [
            階段代碼.測試,
            階段代碼.驗證紅,
            階段代碼.實作,
            階段代碼.驗證綠,
            階段代碼.實作,
            階段代碼.驗證綠,
            階段代碼.審查,
        ]
        assert len(人["實作"].收到) == 2

    def test_驗證紅居然是綠的會退回測試(self) -> None:
        執行, 人 = _執行器([True, False, True])
        果 = 跑工作流(一件事, 執行一步=執行)
        assert 果.結束.代碼 is 結束代碼.完成
        assert len(人["測試"].收到) == 2, "測試沒在測東西就要重寫"


class Test停止條件:
    def test_來回不停會撞到步數上限(self) -> None:
        """缺 stop rule 的不是迴圈，是成本漏洞（§3.2）。"""
        執行, _ = _執行器([True] * 50)  # 驗證紅永遠是綠的 → 永遠退回測試
        果 = 跑工作流(一件事, 執行一步=執行, 最多步數=6)
        assert 果.結束.代碼 is 結束代碼.中止
        assert "最多步數" in 果.結束.原因
        assert len(果.軌跡) == 6

    def test_結果未知當場停(self) -> None:
        """不知道做了沒的時候，往下或退回都可能把做過的事再做一次。"""
        人 = {名: 假角色(名) for 名 in ("測試", "實作", "審查")}
        人["測試"] = 假角色("測試", _假回應(終局.結果未知))
        執行, _ = _執行器([False, True], 人)
        果 = 跑工作流(一件事, 執行一步=執行)
        assert 果.結束.代碼 is 結束代碼.中止
        assert "未知" in 果.結束.原因
        assert len(果.軌跡) == 1, "停了就不該再跑後面的角色"

    @pytest.mark.parametrize("上限", [0, 1])
    def test_步數上限很小也不會爆(self, 上限: int) -> None:
        果 = 跑工作流(一件事, 執行一步=_執行器([False, True])[0], 最多步數=上限)
        assert 果.結束.代碼 is 結束代碼.中止


class Test判準不是角色:
    def test_驗證階段不會呼叫任何角色(self) -> None:
        """硬規則 4：不得讓同一個模型自寫自評。驗證必須是機械的。"""
        執行, 人 = _執行器([False, True])
        跑工作流(一件事, 執行一步=執行)
        全部提示 = [提示 for 角 in 人.values() for 提示 in 角.收到]
        assert not any("驗證" in 提示 and "階段：全綠了嗎" in 提示 for 提示 in 全部提示)
        assert len(全部提示) == 3, "只有三個模型階段，兩個驗證階段不該叫模型"

    def test_判準階段的步驟結果帶紅綠模型階段不帶(self) -> None:
        執行, _ = _執行器([False, True])
        果 = 跑工作流(一件事, 執行一步=執行)
        for 步 in 果.軌跡:
            是判準 = 步.階段 in (階段代碼.驗證紅, 階段代碼.驗證綠)
            assert (步.判準綠 is not None) is 是判準


def test_階段定義是資料不是分支() -> None:
    """能被 dump 進 journal——這是選轉移表而不是鏈式寫法的理由之一。"""
    定義 = 階段定義(
        代碼=階段代碼.測試,
        名稱="x",
        種類=種類.模型,
        期望綠=None,
        綠=階段代碼.實作,
        紅=階段代碼.審查,
    )
    assert 定義.代碼.value == "test"


def test_步驟結果不可變() -> None:
    步 = 步驟結果(階段=階段代碼.測試, 終局=終局.成功, 判準綠=None, 證據="")
    with pytest.raises(dataclasses.FrozenInstanceError):
        步.證據 = "改掉"  # type: ignore[misc]

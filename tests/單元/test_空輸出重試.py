"""CLI 說成功卻一個字都沒回：唯讀時再問一次，可編輯時不准。

實測 2026-09-01（帳本全量）：agy 這樣收場 14 次，`input+output` 燒掉
4,318,931 token，另有約 2,680 萬快取讀取——而**每一次都是零產出**：
空輸出被降成結果未知，可編輯下接力不准換腦，整輪 TDD 停在護欄。

重試的邊界由權限決定，不由 CLI 自報決定：agy 的信封只有
`status`／`error`／`response`／`usage`／`conversation_id`，**沒有 `num_turns`**
（那是 claude 的欄位）。所以可編輯模式下沒有任何證據能證明工具沒動過檔案。
"""

from pathlib import Path

import pytest

from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.契約.角色 import 呼叫選項, 權限
from nova.載體.模型 import 轉接
from nova.載體.模型.執行 import 執行結果
from nova.載體.模型.解析 import 解析agy


def _答(*, 終: 終局, 代碼: 失敗代碼, 文字: str = "隨便") -> 回應:
    return 回應(
        文字=文字,
        終局=終,
        失敗代碼=代碼,
        原始結束碼=0,
        對話識別碼=None,
        用量=用量(輸入token=1, 輸出token=0),
    )


class Test空輸出的失敗代碼要指名道姓:
    def test_agy空輸出收在空輸出代碼而不是未知(self) -> None:
        """`unknown` 什麼都可能是；帳本要數得出「這是空輸出」才有下一次量測。"""
        答 = 解析agy('{"status": "SUCCESS", "error": null, "response": ""}', 0)
        assert 答.終局 is 終局.結果未知
        assert 答.失敗代碼 is 失敗代碼.空輸出

    def test_有話說的成功不會被降級(self) -> None:
        答 = 解析agy('{"status": "SUCCESS", "error": null, "response": "做完了"}', 0)
        assert 答.終局 is 終局.成功
        assert 答.失敗代碼 is 失敗代碼.無


class Test該不該重試:
    def test_唯讀的空輸出要重試(self) -> None:
        """唯讀由權限本身保證沒有副作用，不必靠 CLI 自報輪次。"""
        assert 轉接.空輸出該重試(_答(終=終局.結果未知, 代碼=失敗代碼.空輸出), 權限.唯讀)

    def test_可編輯的空輸出不准重試(self) -> None:
        """沒有 `num_turns` 這種證據，重試就是把可能做過的副作用再做一次。"""
        assert not 轉接.空輸出該重試(_答(終=終局.結果未知, 代碼=失敗代碼.空輸出), 權限.可編輯)

    def test_逾時的空輸出不准重試(self) -> None:
        """逾時那條路明文寫著不准重跑——子程序被殺時可能已經做了一半。"""
        assert not 轉接.空輸出該重試(_答(終=終局.結果未知, 代碼=失敗代碼.逾時), 權限.唯讀)

    def test_成功不重試(self) -> None:
        assert not 轉接.空輸出該重試(_答(終=終局.成功, 代碼=失敗代碼.無), 權限.唯讀)

    def test_權限被擋不重試(self) -> None:
        """下一次撞的是同一堵牆。"""
        assert not 轉接.空輸出該重試(_答(終=終局.結果未知, 代碼=失敗代碼.權限被擋), 權限.唯讀)


class Test詢問真的會再問一次:
    @staticmethod
    def _建agy() -> 轉接.命令列模型:
        def 組參數(提示: str, 選項: 呼叫選項) -> list[str]:
            del 選項
            return [提示]

        return 轉接.命令列模型(
            名稱="agy",
            執行檔=Path("/bin/echo"),
            組參數=組參數,
            解析=解析agy,
        )

    def test_唯讀空輸出會再問一次而且吃到第二次的答案(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        回合: list[int] = []

        def 假跑(*位置: object, **具名: object) -> 執行結果:
            del 位置, 具名
            回合.append(1)
            文字 = "" if len(回合) == 1 else "第二次有話說"
            return 執行結果(
                標準輸出=f'{{"status":"SUCCESS","error":null,"response":"{文字}"}}',
                標準錯誤="",
                結束碼=0,
            )

        monkeypatch.setattr(轉接, "跑cli", 假跑)
        答 = self._建agy().詢問("題目", 選項=呼叫選項(權限=權限.唯讀))
        assert len(回合) == 2
        assert 答.終局 is 終局.成功
        assert 答.文字 == "第二次有話說"

    def test_重試有上限不會無限問(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """沒有停止規則的重試就是成本漏洞（§3.2）。"""
        回合: list[int] = []

        def 一直空(*位置: object, **具名: object) -> 執行結果:
            del 位置, 具名
            回合.append(1)
            return 執行結果(
                標準輸出='{"status":"SUCCESS","error":null,"response":""}',
                標準錯誤="",
                結束碼=0,
            )

        monkeypatch.setattr(轉接, "跑cli", 一直空)
        答 = self._建agy().詢問("題目", 選項=呼叫選項(權限=權限.唯讀))
        assert len(回合) == 1 + 轉接.空輸出最多重試
        assert 答.失敗代碼 is 失敗代碼.空輸出

    def test_可編輯的空輸出只問一次(self, monkeypatch: pytest.MonkeyPatch) -> None:
        回合: list[int] = []

        def 一直空(*位置: object, **具名: object) -> 執行結果:
            del 位置, 具名
            回合.append(1)
            return 執行結果(
                標準輸出='{"status":"SUCCESS","error":null,"response":""}',
                標準錯誤="",
                結束碼=0,
            )

        monkeypatch.setattr(轉接, "跑cli", 一直空)
        self._建agy().詢問("題目", 選項=呼叫選項(權限=權限.可編輯))
        assert len(回合) == 1

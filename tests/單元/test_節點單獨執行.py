from pathlib import Path
from typing import cast

import pytest

from nova.契約.工作流 import 任務
from nova.契約.模型回應 import 失敗代碼, 用量
from nova.契約.節點 import (
    停止政策,
    分支識別碼,
    執行識別碼,
    節點上下文,
    節點成功,
    節點結果,
    節點結果未知,
    節點識別碼,
    節點護欄,
    節點錯誤,
    結果代碼,
    結構識別碼,
    證據來源,
    護欄原因,
    邊包,
    邊識別碼,
)
from nova.迴圈.節點 import 單獨執行


def test_沒有工作流也有根上下文與停止政策() -> None:
    class 記錄節點:
        def __init__(self) -> None:
            self.收到輸入: 邊包[dict[str, str]] | None = None
            self.收到上下文: 節點上下文 | None = None
            self.收到依賴: str | None = None

        @property
        def 識別碼(self) -> 節點識別碼:
            return 節點識別碼("獨立測試節點")

        def 執行(
            self,
            輸入: 邊包[dict[str, str]],
            *,
            上下文: 節點上下文,
            依賴: str,
        ) -> 節點成功[dict[str, str]]:
            self.收到輸入 = 輸入
            self.收到上下文 = 上下文
            self.收到依賴 = 依賴
            return 節點成功(產出=輸入, 證據=(), 用量=None)

    停止 = 停止政策(最多呼叫=1, 最多token=100_000, 最多秒=600, 最多無進展=1)
    上下文 = 節點上下文(
        任務=任務(描述="驗證獨立節點", 工作目錄=Path("測試工作目錄")),
        執行=執行識別碼("獨立執行-001"),
        工作流=None,
        節點=節點識別碼("獨立測試節點"),
        分支=分支識別碼("root"),
        父邊=(),
        嘗試=1,
        停止=停止,
    )
    輸入 = 邊包(
        結構=結構識別碼("獨立輸入"),
        版本=1,
        內容={"題目": "獨立執行"},
        來源=證據來源(
            執行=執行識別碼("獨立執行-001"),
            工作流=None,
            分支=分支識別碼("root"),
            節點=節點識別碼("獨立測試節點"),
            嘗試=1,
            父邊=(邊識別碼("外部輸入-001"),),
        ),
    )
    節點 = 記錄節點()

    結果 = 單獨執行(節點, 輸入, 上下文=上下文, 依賴="測試依賴")

    assert isinstance(結果, 節點成功)
    assert 結果.結果 is 結果代碼.成功
    assert 結果.產出 is 輸入
    assert 節點.收到上下文 is 上下文
    assert 節點.收到上下文.工作流 is None
    assert 節點.收到上下文.分支 == 分支識別碼("root")
    assert 節點.收到上下文.父邊 == ()
    assert 節點.收到輸入 is 輸入
    assert 節點.收到輸入.來源.父邊 == (邊識別碼("外部輸入-001"),)
    assert 節點.收到上下文.停止 is 停止
    assert 節點.收到上下文.停止.最多呼叫 == 1
    assert 節點.收到上下文.停止.最多token == 100_000
    assert 節點.收到上下文.停止.最多秒 == 600
    assert 節點.收到上下文.停止.最多無進展 == 1
    assert 節點.收到上下文.停止.結果未知不重跑 is True
    assert 節點.收到依賴 == "測試依賴"


class 回傳結果節點:
    """記錄 runner 呼叫並回傳指定結果的最小節點。"""

    def __init__(self, 結果: object) -> None:
        """記錄要回傳的結果。"""
        self._結果 = 結果
        self.呼叫次數 = 0
        self.收到輸入: 邊包[dict[str, str]] | None = None
        self.收到上下文: 節點上下文 | None = None
        self.收到依賴: object | None = None

    @property
    def 識別碼(self) -> 節點識別碼:
        return 節點識別碼("回傳結果節點")

    def 執行(
        self,
        輸入: 邊包[dict[str, str]],
        *,
        上下文: 節點上下文,
        依賴: object,
    ) -> 節點結果[dict[str, str]]:
        self.呼叫次數 += 1
        self.收到輸入 = 輸入
        self.收到上下文 = 上下文
        self.收到依賴 = 依賴
        return cast(節點結果[dict[str, str]], self._結果)


def _上下文(停止: 停止政策) -> 節點上下文:
    return 節點上下文(
        任務=任務(描述="測試單獨節點", 工作目錄=Path("測試工作目錄")),
        執行=執行識別碼("單獨執行-測試"),
        工作流=None,
        節點=節點識別碼("回傳結果節點"),
        分支=分支識別碼("root"),
        父邊=(),
        嘗試=1,
        停止=停止,
    )


def _輸入() -> 邊包[dict[str, str]]:
    return 邊包(
        結構=結構識別碼("測試輸入"),
        版本=1,
        內容={"題目": "測試停止政策"},
        來源=證據來源(
            執行=執行識別碼("單獨執行-測試"),
            工作流=None,
            分支=分支識別碼("root"),
            節點=節點識別碼("回傳結果節點"),
            嘗試=1,
            父邊=(邊識別碼("輸入的父邊"),),
        ),
    )


def _成功(輸入: 邊包[dict[str, str]], 使用量: 用量 | None = None) -> 節點成功[dict[str, str]]:
    return 節點成功(產出=輸入, 證據=(), 用量=使用量)


def _跑(
    結果: object,
    停止: 停止政策,
    *,
    輸入: 邊包[dict[str, str]] | None = None,
) -> tuple[節點結果[dict[str, str]], 回傳結果節點]:
    節點 = 回傳結果節點(結果)
    實際輸入 = 輸入 if 輸入 is not None else _輸入()
    回傳 = 單獨執行(節點, 實際輸入, 上下文=_上下文(停止), 依賴="測試依賴")
    return 回傳, 節點


def test_最多呼叫小於一時回步數護欄且不呼叫節點() -> None:
    結果, 節點 = _跑(
        object(),
        停止政策(最多呼叫=0, 最多token=100, 最多秒=600, 最多無進展=1),
    )

    assert isinstance(結果, 節點護欄)
    assert 結果.結果 is 結果代碼.護欄
    assert 結果.原因 is 護欄原因.步數
    assert 節點.呼叫次數 == 0


def test_最多秒為零時回逾時護欄且不呼叫節點() -> None:
    結果, 節點 = _跑(
        object(),
        停止政策(最多呼叫=1, 最多token=100, 最多秒=0, 最多無進展=1),
    )

    assert isinstance(結果, 節點護欄)
    assert 結果.原因 is 護欄原因.逾時
    assert 節點.呼叫次數 == 0


def test_輸出來源不合上下文契約時回輸出不合約護欄() -> None:
    不同執行 = 證據來源(
        執行=執行識別碼("另一個執行"),
        工作流=None,
        分支=分支識別碼("root"),
        節點=節點識別碼("回傳結果節點"),
        嘗試=1,
        父邊=(),
    )
    不合約產出 = 邊包(
        結構=結構識別碼("不合約輸出"),
        版本=1,
        內容={"答案": "來源錯了"},
        來源=不同執行,
    )
    原結果 = 節點成功(產出=不合約產出, 證據=(), 用量=None)

    結果, 節點 = _跑(
        原結果,
        停止政策(最多呼叫=1, 最多token=100, 最多秒=600, 最多無進展=1),
    )

    assert isinstance(結果, 節點護欄)
    assert 結果.原因 is 護欄原因.輸出不合約
    assert 節點.呼叫次數 == 1


def test_結果未知不重跑時原樣回結果未知() -> None:
    錯誤 = 節點錯誤(
        代碼=失敗代碼.逾時,
        診斷="可能已經做過一部分",
        可能已產生副作用=True,
    )
    使用量 = 用量(輸入token=80, 輸出token=30)
    未知 = 節點結果未知(錯誤=錯誤, 已知證據=(), 用量=使用量)

    結果, 節點 = _跑(
        未知,
        停止政策(
            最多呼叫=1,
            最多token=100,
            最多秒=600,
            最多無進展=1,
            結果未知不重跑=True,
        ),
    )

    assert 結果 is 未知
    assert 結果.結果 is 結果代碼.結果未知
    assert 結果.錯誤 is 錯誤
    assert 節點.呼叫次數 == 1


def test_結果超過token上限時回預算護欄() -> None:
    輸入 = _輸入()
    使用量 = 用量(輸入token=80, 輸出token=30)
    原結果 = _成功(輸入, 使用量)

    結果, 節點 = _跑(
        原結果,
        停止政策(最多呼叫=1, 最多token=100, 最多秒=600, 最多無進展=1),
    )

    assert isinstance(結果, 節點護欄)
    assert 結果.原因 is 護欄原因.預算
    assert 結果.用量 is 使用量
    assert 節點.呼叫次數 == 1


def test_呼叫後超過秒數上限時回逾時護欄(monkeypatch: pytest.MonkeyPatch) -> None:
    時間 = iter((100.0, 102.0))

    def 假時間() -> float:
        return next(時間)

    monkeypatch.setattr("nova.迴圈.節點.monotonic", 假時間)
    輸入 = _輸入()
    原結果 = _成功(輸入)

    結果, 節點 = _跑(
        原結果,
        停止政策(最多呼叫=1, 最多token=100, 最多秒=1, 最多無進展=1),
    )

    assert isinstance(結果, 節點護欄)
    assert 結果.原因 is 護欄原因.逾時
    assert 節點.呼叫次數 == 1


def test_成功結果無進展且上限為零時回無進展護欄(monkeypatch: pytest.MonkeyPatch) -> None:
    時間 = iter((100.0, 100.0))

    def 假時間() -> float:
        return next(時間)

    monkeypatch.setattr("nova.迴圈.節點.monotonic", 假時間)
    輸入 = _輸入()
    原結果 = _成功(輸入)

    結果, 節點 = _跑(
        原結果,
        停止政策(最多呼叫=1, 最多token=100, 最多秒=1, 最多無進展=0),
        輸入=輸入,
    )

    assert isinstance(結果, 節點護欄)
    assert 結果.原因 is 護欄原因.無進展
    assert 節點.呼叫次數 == 1


def test_政策寬鬆時成功結果不誤判護欄() -> None:
    輸入 = _輸入()
    使用量 = 用量(輸入token=40, 輸出token=20)
    原結果 = _成功(輸入, 使用量)

    結果, 節點 = _跑(
        原結果,
        停止政策(最多呼叫=1, 最多token=60, 最多秒=600, 最多無進展=1),
    )

    assert 結果 is 原結果
    assert isinstance(結果, 節點成功)
    assert 結果.結果 is 結果代碼.成功
    assert 結果.用量 is 使用量
    assert 節點.呼叫次數 == 1

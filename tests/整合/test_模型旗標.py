"""`--模型` 要從命令列一路走到 `呼叫選項.模型`，不能只停在剖析器。

派工表決定的是**策略**（例行走 agy、推理走 sol），
`--模型` 是**這一次**的例外——例如 agy 的 gemini 那池用完了，
但它代跑的 claude／gpt 是另一個池，走得到就不必停工。
"""

from pathlib import Path

import pytest

from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.契約.角色 import 呼叫選項, 預設選項
from nova.載體 import 命令列


class 記錄腦:
    """讓測試直接看到角色交給呼叫端的完整選項。"""

    名稱 = "測試用假腦"

    def __init__(self) -> None:
        """初始化用來收集呼叫選項的清單。"""
        self.選項們: list[呼叫選項] = []

    def 詢問(self, 提示: str, *, 選項: 呼叫選項 = 預設選項) -> 回應:
        del 提示
        self.選項們.append(選項)
        return 回應(
            文字="已收到",
            終局=終局.成功,
            失敗代碼=失敗代碼.無,
            原始結束碼=0,
            對話識別碼=None,
            用量=用量(輸入token=1, 輸出token=1),
        )


def _跑一輪(參數們: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> 記錄腦:
    腦 = 記錄腦()
    工作區 = tmp_path / "工作區"
    工作區.mkdir(exist_ok=True)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "狀態"))
    monkeypatch.setattr(命令列, "_建腦", lambda *_args, **_kwargs: 腦)
    命令列.主程式(
        [
            "跑",
            "--用",
            "agy",
            "--審查用",
            "claude",
            *參數們,
            "--工作目錄",
            str(工作區),
            "--判準",
            "true",
            "--最多步數",
            "1",
            "--不記帳",
            "任務",
        ]
    )
    return 腦


def test_模型旗標真的傳到呼叫選項(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """只讓剖析器收下旗標不夠，最後一格必須是 `呼叫選項.模型`。"""
    腦 = _跑一輪(["--模型", "claude-sonnet-4-6"], tmp_path, monkeypatch)

    assert 腦.選項們, "工作流沒有真的叫到角色"
    assert 腦.選項們[0].模型 == "claude-sonnet-4-6"


def test_不給模型旗標就照派工表(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--模型` 是這一次的例外，**不給就不要動策略**。"""
    腦 = _跑一輪([], tmp_path, monkeypatch)

    assert 腦.選項們, "工作流沒有真的叫到角色"
    assert 腦.選項們[0].模型 is None

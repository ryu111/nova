"""工作流的逾時要能調整、看得出來，而且不能只停在命令列參數。"""

import re
import stat
import sys
from pathlib import Path

import pytest

from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.契約.角色 import 呼叫選項, 預設逾時秒, 預設選項
from nova.載體 import 命令列
from nova.載體.模型.轉接 import codex高階模型, 建立, 決定逾時秒
from nova.載體.派工表 import 怎麼派
from nova.迴圈.角色工廠 import 建TDD角色藍圖


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


@pytest.mark.parametrize("子命令", ["跑", "工作流"])
def test_跑與工作流的逾時真的傳到呼叫選項(
    子命令: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """只讓剖析器收下旗標不夠，最後一格必須是 `呼叫選項.逾時秒`。"""
    腦 = 記錄腦()
    工作區 = tmp_path / "工作區"
    工作區.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "狀態"))
    monkeypatch.setattr(命令列, "_建腦", lambda *_args, **_kwargs: 腦)

    命令列.主程式(
        [
            子命令,
            "--用",
            "claude",
            "--審查用",
            "codex",
            "--逾時",
            "7.5",
            "--工作目錄",
            str(工作區),
            "--判準",
            "true",
            "--最多步數",
            "1",
            "--帳本目錄",
            str(tmp_path / "帳本"),
            "--不記帳",
            "任務",
        ]
    )

    assert 腦.選項們, "工作流沒有真的叫到角色"
    assert 腦.選項們[0].逾時秒 == 7.5


def test_TDD階段的預設逾時比單次問話長() -> None:
    """工作流每一階的預設不能再和單次 `問` 共用 1800 秒。"""
    for 藍圖 in 建TDD角色藍圖(怎麼派):
        assert 藍圖.逾時秒 > 預設逾時秒, f"{藍圖.識別碼} 還在用單次問話的逾時"


def test_高階模型也要尊重呼叫端明確指定的逾時() -> None:
    """模型種類不能把人明確指定的短皮帶偷偷拉長。"""
    assert 決定逾時秒(呼叫選項(模型=codex高階模型, 逾時秒=60.0)) == 60.0


@pytest.mark.serial
def test_逾時訊息要帶實際秒數上限與不准重跑指示(tmp_path: Path) -> None:
    """逾時後要能判斷它跑了多久、上限多少，以及下一步不能重做。"""
    執行檔 = tmp_path / "工作流實作"
    執行檔.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(5)\n", encoding="utf-8")
    執行檔.chmod(執行檔.stat().st_mode | stat.S_IEXEC)
    工作區 = tmp_path / "工作區"
    工作區.mkdir()

    答 = 建立("claude", 執行檔=執行檔).詢問(
        "執行工作流階段", 選項=呼叫選項(工作目錄=工作區, 逾時秒=0.2)
    )

    assert 答.終局 is 終局.結果未知
    訊息 = 答.文字
    assert re.search(r"(?:耗時|跑了|經過)\s*[0-9]+(?:\.[0-9]+)?\s*秒", 訊息)
    assert re.search(r"上限\s*0\.2\s*秒", 訊息)
    assert "結果未知" in 訊息
    assert "不准重跑" in 訊息
    assert "去看工作區" in 訊息

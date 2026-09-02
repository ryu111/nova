"""守住正式判準的閘等待要流進工作流步驟結果與帳本。"""

import json
import subprocess
from collections.abc import Callable, Sequence
from io import StringIO
from pathlib import Path

import pytest

from nova.契約.工作流 import 任務, 階段代碼
from nova.契約.帳本 import 事件種類
from nova.契約.模型回應 import 回應, 終局
from nova.載體.判準 import 判準步驟, 可作指定pytest目標, 建預設判準
from nova.載體.帳本 import 建帳本
from nova.載體.閘 import 要幾個token型
from nova.載體.階段記帳 import 記帳執行器
from nova.迴圈.工作流 import 建TDD執行器
from nova.迴圈.狀態機 import 查階段


class _不會被叫的角色:
    @property
    def 名稱(self) -> str:
        return "不會被叫的角色"

    def 做(self, 提示: str, *, 工作目錄: Path | None = None) -> 回應:
        del 提示, 工作目錄
        訊息 = "這支測試只執行判準階段"
        raise AssertionError(訊息)


def test_正式判準的等待毫秒要流進工作流步驟結果(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """兩條正式判準各自排隊的時間，要彙總後交給同一個工作流步驟結果。"""
    等待們 = iter((700, 1_300))

    def 假跑判準指令(
        指令: Sequence[str],
        *,
        工作目錄: Path,
        逾時秒: float,
        要幾個token: 要幾個token型,
        記下等待: Callable[[int], None],
    ) -> subprocess.CompletedProcess[str]:
        del 工作目錄, 逾時秒, 要幾個token
        記下等待(next(等待們))
        return subprocess.CompletedProcess(
            args=tuple(指令), returncode=0, stdout="判準通過", stderr=""
        )

    def 假預設判準步驟們(_: Path) -> tuple[判準步驟, ...]:
        return (
            判準步驟(名稱="第一條", 指令=("第一條",)),
            判準步驟(名稱="第二條", 指令=("第二條",)),
        )

    monkeypatch.setattr("nova.載體.判準._佔住機器跑", 假跑判準指令)
    monkeypatch.setattr("nova.載體.判準.預設判準步驟們", 假預設判準步驟們)

    角色 = _不會被叫的角色()
    執行 = 建TDD執行器(
        角色表={
            階段代碼.測試: 角色,
            階段代碼.實作: 角色,
            階段代碼.重構: 角色,
            階段代碼.審查: 角色,
        },
        跑判準=建預設判準(),
        篩選指定測試=可作指定pytest目標,
    )

    步 = 執行(
        查階段(階段代碼.驗證綠),
        任務(描述="讓判準等待流過工作流", 工作目錄=tmp_path),
        (),
    )

    assert 步.終局 is 終局.成功, 步.證據
    assert 步.等待毫秒 == 2_000, f"兩條判準共排了 2,000 毫秒，步驟結果卻只承載 {步.等待毫秒} 毫秒"


def test_正式判準的等待毫秒要落進工作流階段帳本(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """正式判準產生的等待，經過階段記帳後仍要在 `stage_finished` 留下來。"""
    等待們 = iter((700, 1_300))

    def 假跑判準指令(
        指令: Sequence[str],
        *,
        工作目錄: Path,
        逾時秒: float,
        要幾個token: 要幾個token型,
        記下等待: Callable[[int], None],
    ) -> subprocess.CompletedProcess[str]:
        del 工作目錄, 逾時秒, 要幾個token
        記下等待(next(等待們))
        return subprocess.CompletedProcess(
            args=tuple(指令), returncode=0, stdout="判準通過", stderr=""
        )

    def 假預設判準步驟們(_: Path) -> tuple[判準步驟, ...]:
        return (
            判準步驟(名稱="第一條", 指令=("第一條",)),
            判準步驟(名稱="第二條", 指令=("第二條",)),
        )

    monkeypatch.setattr("nova.載體.判準._佔住機器跑", 假跑判準指令)
    monkeypatch.setattr("nova.載體.判準.預設判準步驟們", 假預設判準步驟們)

    角色 = _不會被叫的角色()
    執行 = 建TDD執行器(
        角色表={
            階段代碼.測試: 角色,
            階段代碼.實作: 角色,
            階段代碼.重構: 角色,
            階段代碼.審查: 角色,
        },
        跑判準=建預設判準(),
        篩選指定測試=可作指定pytest目標,
    )
    串流 = StringIO()
    帳 = 建帳本(串流, 執行識別碼="等待帳")

    步 = 記帳執行器(執行, 帳)(
        查階段(階段代碼.驗證綠),
        任務(描述="讓判準等待進階段帳本", 工作目錄=tmp_path),
        (),
    )

    assert 步.等待毫秒 == 2_000
    事件們 = [json.loads(行) for 行 in 串流.getvalue().splitlines()]
    結束 = next(事件 for 事件 in 事件們 if 事件["event"] == 事件種類.階段結束.value)
    assert 結束.get("lock_wait_ms") == 2_000, (
        f"正式判準排隊 2,000 毫秒，工作流階段結束事件卻沒有承載同一個等待值：{結束}"
    )

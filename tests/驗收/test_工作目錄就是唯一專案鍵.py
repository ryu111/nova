"""`--工作目錄` 是專案的唯一鍵，不是只有模型執行時才有效。"""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

做假CLI型 = Callable[..., tuple[Path, Path]]
nova執行檔 = Path(sys.executable).parent / "nova"


def _跑(*參數: str, 狀態: Path, 在: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_不同啟動目錄時所有專案狀態都歸到工作目錄(tmp_path: Path, 做假CLI: 做假CLI型) -> None:
    """收件、處理中、兩本帳與鎖都必須使用同一個目標專案鍵。"""
    執行檔, _ = 做假CLI("claude")
    狀態 = tmp_path / "state"
    控制目錄 = tmp_path / "控制目錄"
    工作目錄 = tmp_path / "目標工作樹"
    控制目錄.mkdir()
    工作目錄.mkdir()
    assert 控制目錄 != 工作目錄

    結果 = _跑(
        "跑",
        "只應在目標工作樹留下狀態",
        "--用",
        "claude",
        "--審查用",
        "codex",
        "--執行檔",
        str(執行檔),
        "--工作目錄",
        str(工作目錄),
        "--最多步數",
        "0",
        "--判準",
        "true",
        狀態=狀態,
        在=控制目錄,
    )

    assert 結果.returncode == 4, 結果.stdout + 結果.stderr

    專案根 = 狀態 / "nova" / "專案"
    目標狀態 = list(專案根.glob(f"{工作目錄.name}-*"))
    控制狀態 = list(專案根.glob(f"{控制目錄.name}-*"))
    assert len(目標狀態) == 1, f"找不到目標專案狀態：{目標狀態}"
    assert not 控制狀態, f"控制目錄不應有專案狀態：{控制狀態}"

    目標 = 目標狀態[0]
    for 路徑 in (
        目標 / "收件",
        目標 / "收件" / "處理中",
        目標 / "帳本",
        目標 / "已處理",
        目標 / "工作流.鎖",
    ):
        assert 路徑.exists(), f"專案狀態沒有歸到目標：{路徑}"
    assert list((目標 / "已處理").glob("*.收件")), "目標專案沒有留下原始收件"

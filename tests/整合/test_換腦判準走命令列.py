"""命令列那條路也要跟門面同一個判準——**兩個呼叫端只改一個等於沒改**。

`#140` 把門面（`nova.派工`）的家族名檢查放寬了，
但 `命令列.py` 還留著自己那一份，所以 `nova 跑 --用 agy --審查用 agy`
仍然被擋在門口。這支守的就是那條路。

**直接呼叫 `主程式` 不開子程序**：coverage 追不到子程序的行，
變異閘會判成 `WRONG_TEST`（實測踩過）。
"""

from pathlib import Path

import pytest

from nova.載體 import 命令列


def _跑(*參數: str, 在: Path) -> int:
    """跑一次命令列，回退出碼。`--最多步數 0` 讓它在叫模型之前就收場。"""
    return 命令列.主程式(
        [
            "跑",
            *參數,
            "--工作目錄",
            str(在),
            "--最多步數",
            "0",
            "--判準",
            "true",
            "--不記帳",
            "任務",
        ]
    )


def test_命令列也不再用家族名擋同一家(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """判準是對話不是家族名——命令列這條路也一樣。"""
    _跑("--用", "agy", "--審查用", "agy", 在=tmp_path)

    輸出 = capsys.readouterr()
    assert "換一顆腦" not in 輸出.out + 輸出.err, (
        f"命令列不該再用家族名擋同一家：\n{輸出.out}\n{輸出.err}"
    )


def test_命令列的本地腦資格檢查沒有被一起放寬(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """放寬的只有家族名那一條。9B 的實測邊界沒有因此改變。"""
    碼 = _跑("--用", "claude", "--審查用", "local", 在=tmp_path)

    輸出 = capsys.readouterr()
    合起來 = 輸出.out + 輸出.err
    assert 碼 != 0, f"本地腦當審查員應該被擋：\n{合起來}"
    assert "審查資格" in 合起來 or "local" in 合起來, 合起來

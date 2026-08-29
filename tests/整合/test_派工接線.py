"""`--工作` 真的會照派工表挑腦嗎。

派工表本身的內容由 `tests/單元/test_派工表.py` 釘住；這一層只驗
**正式路徑上有人查那張表**——表寫得再對，沒人查等於策略沒生效。
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from nova.載體.命令列 import 主程式

做假CLI型 = Callable[..., tuple[Path, Path]]


def 跑(參數: list[str], 目錄: Path) -> int:
    return 主程式([*參數, "--帳本目錄", str(目錄 / "帳")])


class Test照表挑腦:
    def test_例行工作會叫到agy(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """使用者的策略「多把工作交給 agy」在 CLI 上真的生效。"""
        假, 紀錄 = 做假CLI("agy")
        assert 跑(["問", "--工作", "routine", "--執行檔", str(假), "在嗎"], tmp_path) == 0
        assert 紀錄.exists(), "例行工作沒有派給 agy"

    def test_推理工作會帶上sol(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """不帶模型就會拿到 codex 的便宜預設，而且看起來完全正常。"""
        假, 紀錄 = 做假CLI("codex")
        跑(["問", "--工作", "reasoning", "--執行檔", str(假), "在嗎"], tmp_path)
        參數 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"]
        assert "gpt-5.6-sol" in 參數


class Test互斥:
    def test_工作跟用不准同時給(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """兩個都給就分不出誰說了算。fail-closed：當場講，不要挑一個猜。"""
        assert 跑(["問", "--工作", "routine", "--用", "claude", "在嗎"], tmp_path) != 0
        assert "不要同時" in capsys.readouterr().err

    def test_工作跟模型不准同時給(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """`--工作` 已經決定了模型。再給一個等於偷偷推翻策略。"""
        assert 跑(["問", "--工作", "reasoning", "--模型", "gpt-4", "在嗎"], tmp_path) != 0
        assert "不要同時" in capsys.readouterr().err

    def test_兩個都不給要當場說(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert 跑(["問", "在嗎"], tmp_path) != 0
        assert "--用" in capsys.readouterr().err

    def test_不認得的工作種類要當場說(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            跑(["問", "--工作", "隨便打的", "在嗎"], tmp_path)
        assert "routine" in capsys.readouterr().err

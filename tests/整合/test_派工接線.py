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


#: 指到一個一定不存在的執行檔。**防護退化時的保險絲**：
#: 檢查失效就會 `FileNotFoundError` 當場紅，而不是真的去叫模型。
_不出網路 = ["--執行檔", "/一定不存在/nova-測試用"]


#: 指到一個一定不存在的執行檔。**防護退化時的保險絲**：
#: 檢查失效就 `找不到執行檔` 當場紅，而不是真的去叫模型。
_不出網路 = ["--執行檔", "/一定不存在/nova-測試用"]


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

    def test_例行工作會帶上深度high(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """例行工作照派工表走 high 深度。"""
        假, 紀錄 = 做假CLI("agy")
        跑(["問", "--工作", "routine", "--執行檔", str(假), "在嗎"], tmp_path)
        參數 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"]
        assert "gemini-3.7-flash-high" in 參數

    def test_推理工作會帶上深度max(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """推理工作照派工表走 max 深度。"""
        假, 紀錄 = 做假CLI("codex")
        跑(["問", "--工作", "reasoning", "--執行檔", str(假), "在嗎"], tmp_path)
        參數 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"]
        assert 'model_reasoning_effort="max"' in 參數


class Test互斥:
    """每一支都要給 `--執行檔`，即使正常路徑根本走不到那裡。

    理由是**防護退化時的行為**：互斥檢查在 `_挑腦` 裡，它一旦失效，
    測試就會往下走到真的建腦——`reasoning` 那條會真的叫 sol，
    燒 token 又出網路。實測過：拿掉 guard 跑這兩支要 22.5 秒。

    指到一個不存在的路徑，退化時 0.06 秒就當場紅，網路完全沒碰；
    正常時 guard 先擋，那個路徑根本不會被讀。
    """

    def test_工作跟用不准同時給(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """兩個都給就分不出誰說了算。fail-closed：當場講，不要挑一個猜。"""
        assert 跑(["問", "--工作", "routine", "--用", "claude", *_不出網路, "在嗎"], tmp_path) != 0
        assert "不要同時" in capsys.readouterr().err

    def test_工作跟模型不准同時給(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """`--工作` 已經決定了模型。再給一個等於偷偷推翻策略。"""
        assert (
            跑(["問", "--工作", "reasoning", "--模型", "gpt-4", *_不出網路, "在嗎"], tmp_path) != 0
        )
        assert "不要同時" in capsys.readouterr().err

    def test_工作跟思考深度不准同時給(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--工作` 已經決定了思考深度。再給一個等於偷偷推翻策略。"""
        assert (
            跑(
                ["問", "--工作", "reasoning", "--思考深度", "low", *_不出網路, "在嗎"],
                tmp_path,
            )
            != 0
        )
        assert "不要同時" in capsys.readouterr().err

    def test_兩個都不給要當場說(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert 跑(["問", *_不出網路, "在嗎"], tmp_path) != 0
        assert "--用" in capsys.readouterr().err

    def test_不認得的工作種類要當場說(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            跑(["問", "--工作", "隨便打的", *_不出網路, "在嗎"], tmp_path)
        assert "routine" in capsys.readouterr().err

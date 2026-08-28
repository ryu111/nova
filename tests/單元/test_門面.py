"""門面：外部呼叫端只 import 一次就能用 nova。

一支測試守一件事——混在一起的話，紅了不知道是哪個保證壞掉。
全部用假 CLI，不燒 token。
"""

import json
import stat
from pathlib import Path

import pytest

import nova

實錄目錄 = Path(__file__).resolve().parents[1] / "整合" / "實錄"
#: 每家的 envelope 形狀不同，假 CLI 要吐對應那份——吐錯的話解析器會 fail-closed
#: 回「結果未知」，工作流當場停（那是對的行為，只是不該在這裡發生）。
成功實錄 = {
    "claude": "claude_ok.json",
    "codex": "codex_ok2.jsonl",
    "agy": "agy_ok.json",
}


def _假CLI(目錄: Path, 家: str = "claude", 名稱: str | None = None) -> tuple[Path, Path]:
    """做一支會記下自己被怎麼呼叫的假 CLI。回傳 (執行檔, 紀錄檔)。"""
    名 = 名稱 or f"假{家}"
    紀錄 = 目錄 / f"{名}.json"
    路徑 = 目錄 / 名
    實錄 = 實錄目錄 / 成功實錄[家]
    路徑.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(紀錄)!r}).write_text("
        "json.dumps({'argv': sys.argv[1:], 'who': sys.argv[0]}), encoding='utf-8')\n"
        f"sys.stdout.write(pathlib.Path({str(實錄)!r}).read_text(encoding='utf-8'))\n",
        encoding="utf-8",
    )
    路徑.chmod(路徑.stat().st_mode | stat.S_IEXEC)
    return 路徑, 紀錄


def _翻牌判準(目錄: Path) -> Path:
    """第一次紅、之後綠的判準。讓 驗證紅 與 驗證綠 都能走到。"""
    旗標 = 目錄 / "跑過了"
    腳本 = 目錄 / "判準.sh"
    腳本.write_text(f'#!/bin/sh\nif [ -f "{旗標}" ]; then exit 0; fi\ntouch "{旗標}"\nexit 1\n')
    腳本.chmod(腳本.stat().st_mode | stat.S_IEXEC)
    return 腳本


class Test問:
    def test_問得到答案(self, tmp_path: Path) -> None:
        假, _ = _假CLI(tmp_path)
        答 = nova.問("在嗎", 用="claude", 執行檔=假)
        assert 答.終局 is nova.終局.成功
        assert 答.文字 == "ok"

    def test_預設唯讀(self, tmp_path: Path) -> None:
        """忘了給 可編輯 不會變成放行。"""
        假, 紀錄 = _假CLI(tmp_path)
        nova.問("在嗎", 用="claude", 執行檔=假)
        參數 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"]
        assert 參數[參數.index("--tools") : 參數.index("--tools") + 2] == ["--tools", ""]

    def test_可編輯要明講(self, tmp_path: Path) -> None:
        假, 紀錄 = _假CLI(tmp_path)
        nova.問("在嗎", 用="claude", 執行檔=假, 可編輯=True)
        參數 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"]
        assert "--permission-mode" in 參數

    def test_不認得的家要當場炸(self, tmp_path: Path) -> None:
        假, _ = _假CLI(tmp_path)
        with pytest.raises(ValueError, match="不認得"):
            nova.問("在嗎", 用="不存在的家", 執行檔=假)


class Test派工:
    def test_自己審自己要擋(self) -> None:
        with pytest.raises(ValueError, match="換一顆腦"):
            nova.派工("做點事", 用="codex", 審查用="codex")

    def test_跑完一輪(self, tmp_path: Path) -> None:
        做事的, _ = _假CLI(tmp_path, "codex")
        審查的, _ = _假CLI(tmp_path, "agy")
        果 = nova.派工(
            "做點事",
            用="codex",
            審查用="agy",
            工作目錄=tmp_path,
            判準指令=[str(_翻牌判準(tmp_path))],
            執行檔=做事的,
            審查執行檔=審查的,
        )
        assert 果.結束.代碼.value == "done", 果.結束.原因
        assert [步.階段.value for 步 in 果.軌跡] == [
            "test",
            "verify-red",
            "impl",
            "verify-green",
            "review",
        ]

    def test_執行檔不准誤用到審查那家(self, tmp_path: Path) -> None:
        """`執行檔` 是給 `用` 那家的。拿它去跑 `審查用` 那家＝跑錯二進位。

        原本兩家共用同一個 `執行檔`，`派工(用="codex", 審查用="agy", 執行檔=codex路徑)`
        會讓 agy 跑 codex 的二進位——假 CLI 不會抱怨，真的跑才會爆。
        """
        做事的, 做事紀錄 = _假CLI(tmp_path, "codex")
        審查的, 審查紀錄 = _假CLI(tmp_path, "agy")
        nova.派工(
            "做點事",
            用="codex",
            審查用="agy",
            工作目錄=tmp_path,
            判準指令=[str(_翻牌判準(tmp_path))],
            執行檔=做事的,
            審查執行檔=審查的,
        )
        assert 審查紀錄.exists(), "審查那家根本沒被叫到"
        assert json.loads(審查紀錄.read_text(encoding="utf-8"))["who"] == str(審查的)
        assert json.loads(做事紀錄.read_text(encoding="utf-8"))["who"] == str(做事的)


def test_門面很小() -> None:
    """門面要小。多匯出一個名字就是多一份對外承諾。"""
    assert set(nova.__all__) == {
        "__version__",
        "問",
        "派工",
        "回應",
        "工作流結果",
        "終局",
        "失敗代碼",
        "權限",
    }

"""門面：外部呼叫端只 import 一次就能用 nova。

一支測試守一件事——混在一起的話，紅了不知道是哪個保證壞掉。
全部用假 CLI，不燒 token。
"""

import json
import stat
import sys
from collections.abc import Callable
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


#: 假 CLI 的內容。**行為靠環境變數切，不靠「每支測試重寫一份檔」**——
#: 實測（macOS、n=15 取中位數）新寫一份檔再第一次執行要 122 毫秒，
#: 同一支重複執行只要 14 毫秒。那 100 毫秒是 macOS 對「剛寫出來的新執行檔」
#: 的第一次執行檢查，每支測試白付一次。13 支就是 1.3 秒。
#:
#: shebang 走 `sys.executable` 不走 `/usr/bin/env python3`：後者在這台機器上
#: 指到系統的 3.9.6，不是專案釘的 3.13。
#:
#: 環境變數名走 ASCII（跨程序，CLAUDE.md 的例外條款），用執行檔自己的名字當
#: key——同一份內容擺三個檔名，才有辦法在同一支測試裡同時當 codex 與 agy。
假CLI內容 = f"""#!{sys.executable}
import json, os, pathlib, sys
名 = pathlib.Path(sys.argv[0]).name.replace("fake-", "").upper()
紀錄 = os.environ.get(f"NOVA_FAKE_{{名}}_RECORD")
if 紀錄:
    pathlib.Path(紀錄).write_text(
        json.dumps({{"argv": sys.argv[1:], "who": sys.argv[0]}}), encoding="utf-8")
sys.stdout.write(
    pathlib.Path(os.environ[f"NOVA_FAKE_{{名}}_TRANSCRIPT"]).read_text(encoding="utf-8"))
"""


@pytest.fixture(scope="session")
def 假CLI群(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """三家各一支，整個 session 共用。內容一樣，靠檔名分辨自己是誰。"""
    目錄 = tmp_path_factory.mktemp("假cli群")
    群: dict[str, Path] = {}
    for 家 in 成功實錄:
        路徑 = 目錄 / f"fake-{家}"
        路徑.write_text(假CLI內容, encoding="utf-8")
        路徑.chmod(路徑.stat().st_mode | stat.S_IEXEC)
        群[家] = 路徑
    return 群


#: `做假CLI` fixture 的形狀。寫成別名是因為每支測試都要標它。
做假CLI型 = Callable[..., tuple[Path, Path]]


@pytest.fixture
def 做假CLI(假CLI群: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> 做假CLI型:
    """回傳 (執行檔, 紀錄檔)。紀錄檔每支測試獨立，執行檔整個 session 共用。"""

    def 做(家: str = "claude") -> tuple[Path, Path]:
        紀錄 = tmp_path / f"{家}.json"
        鍵 = 家.upper()
        monkeypatch.setenv(f"NOVA_FAKE_{鍵}_TRANSCRIPT", str(實錄目錄 / 成功實錄[家]))
        monkeypatch.setenv(f"NOVA_FAKE_{鍵}_RECORD", str(紀錄))
        return 假CLI群[家], 紀錄

    return 做


def _翻牌判準(目錄: Path) -> Path:
    """第一次紅、之後綠的判準。讓 驗證紅 與 驗證綠 都能走到。"""
    旗標 = 目錄 / "跑過了"
    腳本 = 目錄 / "判準.sh"
    腳本.write_text(f'#!/bin/sh\nif [ -f "{旗標}" ]; then exit 0; fi\ntouch "{旗標}"\nexit 1\n')
    腳本.chmod(腳本.stat().st_mode | stat.S_IEXEC)
    return 腳本


class Test問:
    def test_問得到答案(self, 做假CLI: 做假CLI型) -> None:
        假, _ = 做假CLI()
        答 = nova.問("在嗎", 用="claude", 執行檔=假)
        assert 答.終局 is nova.終局.成功
        assert 答.文字 == "ok"

    def test_預設唯讀(self, 做假CLI: 做假CLI型) -> None:
        """忘了給 可編輯 不會變成放行。

        驗的是**白名單裡沒有會改東西的工具**，不是「工具清單剛好等於某個字串」——
        後者會在唯讀白名單從 `""` 改成 `Read,Grep,Glob` 這種正確的改動上假紅。
        """
        假, 紀錄 = 做假CLI()
        nova.問("在嗎", 用="claude", 執行檔=假)
        參數 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"]
        工具 = 參數[參數.index("--tools") + 1]
        assert not ({"Write", "Edit", "Bash"} & set(工具.split(","))), f"預設放行了：{工具}"
        assert "--permission-mode" not in 參數

    def test_可編輯要明講(self, 做假CLI: 做假CLI型) -> None:
        假, 紀錄 = 做假CLI()
        nova.問("在嗎", 用="claude", 執行檔=假, 可編輯=True)
        參數 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"]
        assert "--permission-mode" in 參數

    def test_不認得的家要當場炸(self, 做假CLI: 做假CLI型) -> None:
        假, _ = 做假CLI()
        with pytest.raises(ValueError, match="不認得"):
            nova.問("在嗎", 用="不存在的家", 執行檔=假)


class Test派工:
    def test_自己審自己要擋(self) -> None:
        with pytest.raises(ValueError, match="換一顆腦"):
            nova.派工("做點事", 用="codex", 審查用="codex")

    def test_跑完一輪(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        做事的, _ = 做假CLI("codex")
        審查的, _ = 做假CLI("agy")
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

    def test_執行檔不准誤用到審查那家(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """`執行檔` 是給 `用` 那家的。拿它去跑 `審查用` 那家＝跑錯二進位。

        原本兩家共用同一個 `執行檔`，`派工(用="codex", 審查用="agy", 執行檔=codex路徑)`
        會讓 agy 跑 codex 的二進位——假 CLI 不會抱怨，真的跑才會爆。
        """
        做事的, 做事紀錄 = 做假CLI("codex")
        審查的, 審查紀錄 = 做假CLI("agy")
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


class Test接力:
    """`用` 給一串就是接力：前一顆失敗換下一顆。"""

    def test_一串裡第一顆掛了換第二顆(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        壞的 = tmp_path / "壞的"
        壞的.write_text("#!/bin/sh\nexit 2\n")  # 結束碼 2 = 用法錯誤 = 確定失敗
        壞的.chmod(壞的.stat().st_mode | stat.S_IEXEC)
        好的, _ = 做假CLI("agy")
        答 = nova.問("在嗎", 用=["codex", "agy"], 執行檔={"codex": 壞的, "agy": 好的})
        assert 答.終局 is nova.終局.成功
        assert 答.文字 == "ok\n"

    def test_逗號分隔也算一串(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """從命令列傳進來的形狀。"""
        壞的 = tmp_path / "壞的"
        壞的.write_text("#!/bin/sh\nexit 2\n")
        壞的.chmod(壞的.stat().st_mode | stat.S_IEXEC)
        好的, _ = 做假CLI("agy")
        答 = nova.問("在嗎", 用="codex,agy", 執行檔={"codex": 壞的, "agy": 好的})
        assert 答.終局 is nova.終局.成功

    def test_全掛了要留下試過誰(self, tmp_path: Path) -> None:
        壞的 = tmp_path / "壞的"
        壞的.write_text("#!/bin/sh\nexit 2\n")
        壞的.chmod(壞的.stat().st_mode | stat.S_IEXEC)
        答 = nova.問("在嗎", 用="codex,agy", 執行檔=壞的)
        assert 答.終局 is nova.終局.確定失敗
        assert "codex:usage" in 答.文字 and "agy:usage" in 答.文字

    def test_做事與審查的鏈不准重疊(self) -> None:
        """`codex,agy` 對上 `agy` ——agy 同時做事又審自己。"""
        with pytest.raises(ValueError, match="換一顆腦"):
            nova.派工("做點事", 用="codex,agy", 審查用="agy")

    def test_空的鏈要當場炸(self) -> None:
        with pytest.raises(ValueError, match="至少要指定一家"):
            nova.問("在嗎", 用="")

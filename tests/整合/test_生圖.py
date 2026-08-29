"""生圖：把「只有 agy 有、而且非全開會靜默假成功」這兩件事寫進殼裡。

`tests/驗收/test_真cli契約.py::test_agy生圖要全開權限檔案才進得了工作目錄`
是真的燒 token 量到的**行為契約**（50,694 → 1,607 token）。這一層把那份契約
變成**擋得住的規則**——契約只記錄「事實是這樣」，這裡才讓人違反不了。

契約裡最危險的一條：可編輯權限下 `generate_image` 會成功，但圖留在
`~/.gemini/antigravity-cli/brain/<sid>/`，搬進工作目錄的那道 shell 被權限擋掉，
**而 CLI 仍然回 `status: SUCCESS`**。也就是說「照做但沒東西」長得跟成功一模一樣。
"""

import inspect
import json
import stat
import sys
from pathlib import Path

import pytest

from nova.契約.模型回應 import 終局
from nova.載體.命令列 import 主程式
from nova.載體.生圖 import 生圖

實錄 = Path(__file__).resolve().parent / "實錄" / "agy_ok.json"

#: 假 agy：把 argv 記下來，可以順便在工作目錄生一個假的「圖」。
#: 行為靠環境變數切（05 的做法 B），不要每支測試重寫一份檔。
假agy = f"""#!{sys.executable}
import json, os, pathlib, sys
pathlib.Path(os.environ["生圖測試_紀錄"]).write_text(
    json.dumps({{"argv": sys.argv[1:]}}), encoding="utf-8")
圖 = os.environ.get("生圖測試_產出")
if 圖:
    pathlib.Path(圖).write_bytes(b"\\x89PNG" + b"0" * 2000)
sys.stdout.write(pathlib.Path({str(實錄)!r}).read_text(encoding="utf-8"))
"""


@pytest.fixture(scope="module")
def 假CLI(tmp_path_factory: pytest.TempPathFactory) -> Path:
    路徑 = tmp_path_factory.mktemp("生圖") / "fake-agy"
    路徑.write_text(假agy, encoding="utf-8")
    路徑.chmod(路徑.stat().st_mode | stat.S_IEXEC)
    return 路徑


@pytest.fixture
def 會生圖(假CLI: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("生圖測試_紀錄", str(tmp_path / "argv.json"))
    monkeypatch.setenv("生圖測試_產出", str(tmp_path / "星星.png"))
    return 假CLI


@pytest.fixture
def 不生圖(假CLI: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """CLI 回成功，但工作目錄什麼都沒有——契約裡那條假成功。"""
    monkeypatch.setenv("生圖測試_紀錄", str(tmp_path / "argv.json"))
    monkeypatch.delenv("生圖測試_產出", raising=False)
    return 假CLI


class Test驗收看檔案不看模型:
    def test_圖真的出現才算成功(self, tmp_path: Path, 會生圖: Path) -> None:
        果 = 生圖("一顆星星", 工作目錄=tmp_path, 執行檔=會生圖)
        assert 果.答.終局 is 終局.成功
        assert [檔.name for 檔 in 果.圖檔] == ["星星.png"]

    def test_模型說成功但沒圖要降成結果未知(self, tmp_path: Path, 不生圖: Path) -> None:
        """硬規則 5：不得以「模型說完成了」當停止條件。

        **降成結果未知不是確定失敗**：圖可能已經生出來了，只是留在
        agy 的 brain 目錄搬不過來。當成確定失敗會讓上層重跑，
        而重跑是再生一張圖、再花一次錢。
        """
        果 = 生圖("一顆星星", 工作目錄=tmp_path, 執行檔=不生圖)
        assert 果.答.終局 is 終局.結果未知
        assert 果.圖檔 == ()
        assert "沒有" in 果.答.文字 or "沒有" in 果.答.失敗代碼.value or 果.答.文字

    def test_沒圖的時候原因要留在證據裡(self, tmp_path: Path, 不生圖: Path) -> None:
        """只回「結果未知」的話，查的人得自己重建為什麼。"""
        果 = 生圖("一顆星星", 工作目錄=tmp_path, 執行檔=不生圖)
        assert "工作目錄" in 果.答.文字

    def test_本來就有的圖不算數(self, tmp_path: Path, 不生圖: Path) -> None:
        """只看「跑完之後多了什麼」。

        看目錄裡有沒有圖的話，第二次呼叫會被第一次的產物騙過去。
        """
        (tmp_path / "舊的.png").write_bytes(b"\x89PNG" + b"0" * 2000)
        果 = 生圖("一顆星星", 工作目錄=tmp_path, 執行檔=不生圖)
        assert 果.答.終局 is 終局.結果未知
        assert 果.圖檔 == ()


class Test權限:
    def test_一定走全開(self, tmp_path: Path, 會生圖: Path) -> None:
        """可編輯下圖進不了工作目錄，而 CLI 假回報成功。**這條不給呼叫端選。**"""
        生圖("一顆星星", 工作目錄=tmp_path, 執行檔=會生圖)
        參數 = json.loads((tmp_path / "argv.json").read_text(encoding="utf-8"))["argv"]
        assert "--dangerously-skip-permissions" in 參數

    def test_呼叫端不能指定權限(self) -> None:
        """簽章裡沒有權限這個參數——能傳就代表能傳錯。"""
        assert "權限" not in inspect.signature(生圖).parameters


class Test只有agy有:
    def test_提示會叫它搬進工作目錄(self, tmp_path: Path, 會生圖: Path) -> None:
        """圖預設落在 agy 的 brain 目錄，不講就不會過來。

        只看**提示那個參數**，不看整串 argv——`--add-dir` 本來就會帶上工作目錄，
        掃整串的話，把提示裡那句拿掉這支照樣綠。第一版就是這樣，靠負控才發現。
        """
        生圖("一顆星星", 工作目錄=tmp_path, 執行檔=會生圖)
        參數 = json.loads((tmp_path / "argv.json").read_text(encoding="utf-8"))["argv"]
        提示們 = [孤 for 孤 in 參數 if "generate_image" in 孤]
        assert 提示們, f"argv 裡找不到提示：{參數}"
        assert str(tmp_path) in 提示們[0]


class TestCLI:
    def test_生圖子命令(
        self, tmp_path: Path, 會生圖: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        碼 = 主程式(
            ["生圖", "一顆星星", "--工作目錄", str(tmp_path), "--執行檔", str(會生圖), "--不記帳"]
        )
        assert 碼 == 0
        assert "星星.png" in capsys.readouterr().out

    def test_沒生出來要用結果未知的退出碼(
        self, tmp_path: Path, 不生圖: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """退出碼 3 ＝ 不知道做了沒，**腳本不准重跑**。"""
        碼 = 主程式(
            ["生圖", "一顆星星", "--工作目錄", str(tmp_path), "--執行檔", str(不生圖), "--不記帳"]
        )
        assert 碼 == 3
        assert "沒有" in capsys.readouterr().err

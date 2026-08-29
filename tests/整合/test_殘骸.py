"""逾時不該等於全損：讓被委派的 CLI 邊做邊寫檔，死了還有屍體可以驗。

這是被 sol 那兩次逼出來的。實測 `gpt-5.6-sol` 跑同一個大題目，
25 分鐘一次、60 分鐘一次，**兩次都是 0→0 token**——nova 判結果未知（正確），
但我們對「它做到哪了」一無所知。輸出只有一條路（stdout，而且要跑完才有），
那條路被砍斷就什麼都不剩。

給它一個檔案邊做邊寫，逾時之後那個檔案就是**證據**。
終局不變（它確實沒跑完），但證據不再是空的。
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.載體.命令列 import 主程式
from nova.載體.殘骸 import 加上寫檔指示, 撿回殘骸

做假CLI型 = Callable[..., tuple[Path, Path]]


def 做回應(文字: str = "", 終: 終局 = 終局.結果未知, 代碼: 失敗代碼 = 失敗代碼.逾時) -> 回應:
    return 回應(
        文字=文字,
        終局=終,
        失敗代碼=代碼,
        原始結束碼=-1,
        對話識別碼=None,
        用量=用量(輸入token=0, 輸出token=0),
    )


class Test撿回殘骸:
    def test_逾時但檔案有東西就撿回來(self, tmp_path: Path) -> None:
        屍 = tmp_path / "答案.md"
        屍.write_text("我查到第一點是……", encoding="utf-8")
        答 = 撿回殘骸(做回應(), 屍)
        assert "我查到第一點是" in 答.文字

    def test_撿回來不准改終局(self, tmp_path: Path) -> None:
        """**有屍體不等於做完了。** 改成成功就是拿半成品當成品。"""
        屍 = tmp_path / "答案.md"
        屍.write_text("寫到一半", encoding="utf-8")
        答 = 撿回殘骸(做回應(), 屍)
        assert 答.終局 is 終局.結果未知
        assert 答.失敗代碼 is 失敗代碼.逾時

    def test_檔案不存在要明講(self, tmp_path: Path) -> None:
        """空輸出會讓人以為是 nova 壞了。要說清楚是「它什麼都沒寫」。"""
        答 = 撿回殘骸(做回應(), tmp_path / "沒這個檔")
        assert "沒有" in 答.文字

    def test_空檔案跟沒檔案一樣要明講(self, tmp_path: Path) -> None:
        屍 = tmp_path / "答案.md"
        屍.write_text("   \n", encoding="utf-8")
        assert "沒有" in 撿回殘骸(做回應(), 屍).文字

    def test_確定失敗也要撿(self, tmp_path: Path) -> None:
        """上游 5xx 之前可能已經寫了一半。只撿逾時那一種會漏掉。"""
        屍 = tmp_path / "答案.md"
        屍.write_text("寫到一半", encoding="utf-8")
        答 = 撿回殘骸(做回應(終=終局.確定失敗, 代碼=失敗代碼.上游), 屍)
        assert "寫到一半" in 答.文字

    def test_成功的時候不要動它(self, tmp_path: Path) -> None:
        """它已經正常回答了。再把檔案接上去只會讓同一段話出現兩次。"""
        屍 = tmp_path / "答案.md"
        屍.write_text("完整答案", encoding="utf-8")
        答 = 撿回殘骸(做回應("完整答案", 終局.成功, 失敗代碼.無), 屍)
        assert 答.文字 == "完整答案"

    def test_原本的診斷要留著(self, tmp_path: Path) -> None:
        """殘骸是補充不是取代。原本的失敗訊息才說得出「為什麼死的」。"""
        屍 = tmp_path / "答案.md"
        屍.write_text("寫到一半", encoding="utf-8")
        答 = 撿回殘骸(做回應("逾時被殺"), 屍)
        assert "逾時被殺" in 答.文字 and "寫到一半" in 答.文字

    def test_太大的殘骸要截斷(self, tmp_path: Path) -> None:
        """屍體可能是一個 50 MB 的 log。整個塞進回應會把終端機洗掉。"""
        屍 = tmp_path / "答案.md"
        屍.write_text("字" * 100_000, encoding="utf-8")
        答 = 撿回殘骸(做回應(), 屍)
        assert len(答.文字) < 20_000
        assert "截斷" in 答.文字


class Test寫檔指示:
    def test_提示會給出檔案路徑(self, tmp_path: Path) -> None:
        提示 = 加上寫檔指示("查三件事", tmp_path / "答案.md")
        assert str(tmp_path / "答案.md") in 提示

    def test_要它邊做邊寫(self, tmp_path: Path) -> None:
        """**最後才寫的話，逾時一樣什麼都沒有。**這一句是整個機制的關鍵。"""
        提示 = 加上寫檔指示("查三件事", tmp_path / "答案.md")
        assert "邊" in 提示 or "隨時" in 提示 or "先寫" in 提示

    def test_原本的提示留在最前面(self, tmp_path: Path) -> None:
        """指示塞在前面會讓模型把它當成主要任務。"""
        提示 = 加上寫檔指示("查三件事", tmp_path / "答案.md")
        assert 提示.startswith("查三件事")


class TestCLI:
    """`nova 問 --輸出檔`。這一層才證明**正式路徑上有人用**這個機制。"""

    def test_唯讀給輸出檔要當場擋(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """要它寫檔卻不給寫的權限——那是矛盾，不是「幫你自動開權限」。

        自動升權會讓 `--輸出檔` 變成一個**看不出來的權限開關**，
        而這個 repo 的預設是「忘了設不會變成放行」。
        """
        碼 = 主程式(
            [
                *["問", "--用", "agy", "--輸出檔", str(tmp_path / "答案.md")],
                *["--執行檔", "/一定不存在/nova-測試用", "--不記帳", "在嗎"],
            ]
        )
        assert 碼 != 0
        assert "可編輯" in capsys.readouterr().err

    def test_可編輯就放行而且提示帶了路徑(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        假, 紀錄 = 做假CLI("agy")
        屍 = tmp_path / "答案.md"
        主程式(
            [
                *["問", "--用", "agy", "--可編輯", "--輸出檔", str(屍)],
                *["--執行檔", str(假), "--不記帳", "在嗎"],
            ]
        )
        參數 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"]
        提示們 = [孤 for 孤 in 參數 if "在嗎" in 孤]
        assert 提示們, f"argv 裡找不到提示：{參數}"
        assert str(屍) in 提示們[0]

    def test_掛掉之後殘骸會出現在輸出裡(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """這就是「檢查屍體」——CLI 死了，但它寫下的東西還在。"""
        壞的 = tmp_path / "壞的"
        壞的.write_text("#!/bin/sh\nexit 2\n")
        壞的.chmod(0o755)
        屍 = tmp_path / "答案.md"
        屍.write_text("我查到第一點是……", encoding="utf-8")
        主程式(
            [
                *["問", "--用", "agy", "--可編輯", "--輸出檔", str(屍)],
                *["--執行檔", str(壞的), "--不記帳", "在嗎"],
            ]
        )
        assert "我查到第一點是" in capsys.readouterr().out

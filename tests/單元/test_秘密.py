"""載入秘密：**出生前就把憑證交到子程序手上。**

排程做完之後這一格才有意義：launchd 的 job 拿到的是一份很乾淨的環境，
使用者的 shell profile 一個字都不會被讀。所以無人看管的那條路徑上，
憑證只有一個來源——載體自己遞過去。

## 為什麼不是「叫使用者 export 就好」

那在人坐在終端機前面的時候成立，在時鐘自己跑的時候不成立。而**兩條路徑
行為不一樣是最貴的那種 bug**：你手動跑得動，排程永遠拿到 401，
然後你會去查模型、查網路、查 CLI，就是不會想到環境。

## fail-closed 的方向

祕密檔看不懂就**不要出生**。半載入的祕密會讓子程序帶著缺一半的憑證跑起來，
拿到的錯誤是 401 而不是「你的祕密檔第 3 行打錯了」——診斷順序整個被帶歪。

純解析，不碰硬碟，所以住單元層。權限與落點在 `tests/整合/test_秘密落盤.py`。
"""

import pytest

from nova.載體.秘密 import 看不懂的祕密檔, 讀祕密


def test_一行一個() -> None:
    讀到 = 讀祕密("ANTHROPIC_API_KEY=abc123\nOPENAI_API_KEY=def456\n")

    assert 讀到 == {"ANTHROPIC_API_KEY": "abc123", "OPENAI_API_KEY": "def456"}


def test_空行與註解跳過() -> None:
    讀到 = 讀祕密("# 這是註解\n\nA=1\n   # 縮排的註解\n")

    assert 讀到 == {"A": "1"}


def test_值裡面有等號不會被切斷() -> None:
    """base64 與 JWT 常常以 `=` 結尾。切斷的話憑證會靜默失效。"""
    讀到 = 讀祕密("TOKEN=aGVsbG8=\n")

    assert 讀到 == {"TOKEN": "aGVsbG8="}


def test_外圍的引號拿掉() -> None:
    """`A="x"` 是 shell 的寫法。留著引號的話送出去的憑證會多兩個字元。"""
    assert 讀祕密("A=\"x\"\nB='y'\n") == {"A": "x", "B": "y"}


def test_鍵兩側的空白拿掉() -> None:
    assert 讀祕密("  A = x  \n") == {"A": "x"}


def test_export前綴吃得掉() -> None:
    """使用者多半是從自己的 shell profile 抄過來的。"""
    assert 讀祕密("export A=x\n") == {"A": "x"}


class Test看不懂就不要出生:
    """**半載入比沒載入更糟。**

    缺一半憑證的子程序會跑起來、會拿到 401，而那個錯誤指向模型或網路，
    不指向「你的祕密檔第 3 行打錯了」。
    """

    def test_沒有等號的行當場報錯(self) -> None:
        with pytest.raises(看不懂的祕密檔, match="第 2 行"):
            讀祕密("A=1\n這行沒有等號\n")

    @pytest.mark.parametrize(
        "壞行",
        [
            "沒有等號超級機密的值",  # 整行都看不懂
            "1不合法的鍵=超級機密的值",  # 鍵壞了，值是真的
            "A B=超級機密的值",  # 鍵裡有空白
        ],
    )
    def test_錯誤訊息不准把值印出來(self, 壞行: str) -> None:
        """**錯誤訊息也會進 log。** 印出來的話，祕密檔的意義就沒了。

        **祕密要放在出錯的那一行上。** 放在別行的話它根本走不到，
        這支測試就永遠綠——第一版就是這樣寫的，負控（把訊息改成 `f"...{行}"`）
        完全沒有變紅。
        """
        with pytest.raises(看不懂的祕密檔) as 抓到:
            讀祕密(f"{壞行}\n")

        assert "超級機密的值" not in str(抓到.value), str(抓到.value)

    @pytest.mark.parametrize("鍵", ["1A", "A-B", "A B", "金鑰", ""])
    def test_不是合法shell變數名的鍵要拒絕(self, 鍵: str) -> None:
        """**鍵名一律 ASCII**（CLAUDE.md 的 shell 變數名例外）。

        `金鑰=x` 傳得進 `os.environ`，但子程序那邊多半讀不到，
        而失敗方式是「憑證好像沒設」——查起來一樣貴。
        """
        with pytest.raises(看不懂的祕密檔):
            讀祕密(f"{鍵}=x\n")

    def test_空的值不算祕密(self) -> None:
        """`A=` 多半是「我等一下再填」。當成祕密的話會用一個空字串蓋掉真的環境變數。"""
        with pytest.raises(看不懂的祕密檔, match="第 1 行"):
            讀祕密("A=\n")


def test_空檔案是空的不是錯的() -> None:
    """**預設關閉**：沒有祕密要載入是正常狀態，不是使用者做錯什麼。"""
    assert 讀祕密("") == {}
    assert 讀祕密("\n# 只有註解\n") == {}

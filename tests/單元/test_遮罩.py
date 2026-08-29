"""遮罩：把祕密從要落盤的文字裡蓋掉。

**為什麼需要它**：帳本現在刻意不記模型全文（見 `契約.帳本.事件` 的 docstring），
所以 nova 答得出「花多少、怎麼收場」，答不出「它說了什麼」。而模型的輸出裡
可能夾著它剛剛讀到的金鑰——那些帳會被貼進 PR、issue、commit 訊息。

**這一層的方向跟成本那一層相反。** 成本是「不確定就不給數字」（低報比沒有更危險）；
遮罩是「不確定就遮掉」（漏遮比多遮危險得多）。多遮的代價是除錯時少看到幾個字，
漏遮的代價是永久外洩——GitHub 的快取與別人的 clone 收不回來。

特徵清單的來源是 2026-08-30 派 agy 查的業界規則庫（gitleaks 的 `gitleaks.toml`、
trufflehog 的 `pkg/detectors`），只收**有明確固定前綴或結構**的，
不收「任何 32 位十六進位」那種會大量誤判的。

純函式，不碰硬碟，所以住單元層。
"""

import pytest

from nova.載體.遮罩 import 遮罩

#: 拼樣本用的填充字串。**每一個假樣本都是在執行期拼出來的，
#: 原始碼裡不准出現連續的完整 token。**
#:
#: 這不是潔癖：第一次推這個檔的時候 **GitHub 的 push protection 直接擋下來**
#: （`GH013 … Slack API Token … tests/單元/test_遮罩.py:30`）。
#: 測試需要格式逼真的樣本，而格式逼真就會被掃描器當成真的。
#: 拆開拼接之後掃描器看到的是片段，而測試拿到的仍然是完整字串。
#:
#: **加新樣本時照這個寫法**，否則整條分支會推不上去。
_填 = "a1B2c3D4e5F6g7H8"


def _拼(前綴: str, 尾: str) -> str:
    """把前綴跟尾巴接起來。存在的理由只有一個：讓原始碼裡沒有完整的 token。"""
    return 前綴 + 尾


#: （這是什麼、假的樣本）。樣本全部是憑空捏的，格式對、值是假的。
_假祕密 = [
    ("aws", _拼("AKIA", "IOSFODNN7EXAMPLE")),
    ("github-pat", _拼("ghp_", _填 * 2 + "1Ab2Cd3Ef4")),
    ("github-oauth", _拼("gho_", _填 * 2 + "1Ab2Cd3Ef4")),
    ("openai-proj", _拼("sk-proj-", _填 * 3)),
    ("anthropic", _拼("sk-ant-api03-", _填 * 6)),
    ("google", _拼("AIza", "SyA1b2C3d4E5f6G7h8I9j0K1L2M3N4O5P6Q")),
    ("slack-bot", _拼("xoxb-", "123456789012-123456789012-abcdefghijklmnopqrstuvwx")),
    ("stripe", _拼("sk_live_", "51AbCdEfGhIjKlMnOpQrStUvWxYz1234567890")),
    ("gitlab", _拼("glpat-", "5xAbCdEfGhIjKlMnOpQr")),
    # npm 的規則是**剛好** 36 個字，不是「至少」——16×2＋4。
    ("npm", _拼("npm_", _填 * 2 + "1Ab2")),
    ("huggingface", _拼("hf_", "AbCdEfGhIjKlMnOpQrStUvWxYz1234567890")),
    (
        "jwt",
        _拼(
            "eyJ",
            "hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ"
            ".dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        ),
    ),
]


@pytest.mark.parametrize(("是什麼", "假的"), _假祕密, ids=[名 for 名, _ in _假祕密])
def test_每一種特徵都遮得掉(是什麼: str, 假的: str) -> None:
    """**斷言看的是「原文一個字都不剩」**，不是「有出現遮罩標記」。

    只檢查標記的話，一個把標記接在原文後面的實作也會綠——祕密照樣在裡面。
    """
    del 是什麼
    果 = 遮罩(f"我剛剛看到 {假的} 這串東西")

    assert 假的 not in 果.文字, 果.文字
    assert 果.遮掉幾處 >= 1


@pytest.mark.parametrize(("是什麼", "假的"), _假祕密, ids=[名 for 名, _ in _假祕密])
def test_祕密緊貼中文也要遮掉(是什麼: str, 假的: str) -> None:
    r"""**`\b` 在這個專案裡是壞的。**

    Python 的 `\w` 把中文也算成單字字元，所以 `\bAKIA…\b` 在
    「我讀到AKIAIOSFODNN7EXAMPLE這串」完全不會命中——而模型講中文時
    祕密後面接的常常就是中文，不是空格。實測：有空格 True、貼中文 False。

    這一支是被 `test_遮罩要在截斷之前` 意外抓出來的真 bug。
    """
    del 是什麼
    果 = 遮罩(f"我讀到{假的}這串東西")

    assert 假的 not in 果.文字, 果.文字


def test_沒有祕密的文字原封不動() -> None:
    """**這支防的是遮過頭。** 全部遮掉也能讓上面那些測試綠。"""
    原文 = "測試全綠，跑了 12 支，花了 0.3 秒。git commit -m '修好了'"

    果 = 遮罩(原文)

    assert 果.文字 == 原文
    assert 果.遮掉幾處 == 0


def test_遮掉幾處數得對() -> None:
    """`遮掉幾處` 是誠實欄位：看帳的人要知道自己看到的是不是完整的原文。"""
    果 = 遮罩("第一個 AKIAIOSFODNN7EXAMPLE 第二個 AKIAIOSFODNN7EXAMPLZ")

    assert 果.遮掉幾處 == 2


class Test私鑰整塊:
    def test_PEM私鑰整塊遮掉(self) -> None:
        """私鑰是跨行的，一行一行遮會留下中間的內容。"""
        原文 = (
            "他印出來了：\n"
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQ\n"
            "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMN\n"
            "-----END RSA PRIVATE KEY-----\n"
            "然後就結束了"
        )

        果 = 遮罩(原文)

        assert "MIIEvgIBADAN" not in 果.文字
        assert "abcdefghijklmnop" not in 果.文字
        assert "然後就結束了" in 果.文字, "遮過頭了，後面的正常文字也被吃掉"


class Test網址裡的帳密:
    def test_只遮密碼留下主機(self) -> None:
        """**主機名要留著**，不然看不出是哪台機器出的事——那正是要查的東西。"""
        果 = 遮罩("連到 https://admin:hunter2SuperSecret@db.internal.corp/v1 之後就掛了")

        assert "hunter2SuperSecret" not in 果.文字
        assert "db.internal.corp" in 果.文字, 果.文字

    def test_範本佔位符不遮(self) -> None:
        """`${DB_PASS}` 這種是範本不是祕密，遮掉只會讓範例看不懂。"""
        原文 = "設定長這樣：postgres://${DB_USER}:${DB_PASS}@localhost:5432/app"

        果 = 遮罩(原文)

        assert 果.文字 == 原文, 果.文字


class Test環境變數:
    """**這條規則的精準度最高，而且它抓得到沒有任何特徵的祕密。**

    nova 知道自己的環境。任何從 `os.environ` 來的祕密值，
    不管它長得像不像已知的 token，只要出現在文字裡就該遮掉。
    """

    def test_環境變數的值會被遮掉(self) -> None:
        果 = 遮罩(
            "他把 MY_HOUSE_KEY 印出來了：詹姆士龐德不會開這道門",
            環境={"MY_HOUSE_KEY": "詹姆士龐德不會開這道門"},
        )

        assert "詹姆士龐德不會開這道門" not in 果.文字
        assert 果.遮掉幾處 == 1

    def test_看起來不像祕密的環境變數不遮(self) -> None:
        """`PATH`、`HOME`、`LANG` 的值遮掉的話整份紀錄都不能看了。"""
        原文 = "工作目錄是 /Users/sbu/nova，語言是 zh_TW.UTF-8"

        果 = 遮罩(原文, 環境={"PWD": "/Users/sbu/nova", "LANG": "zh_TW.UTF-8"})

        assert 果.文字 == 原文

    def test_太短的值不遮(self) -> None:
        """短值會在正常文字裡到處撞到——遮掉它等於把文字打成馬賽克。"""
        原文 = "重試了 3 次，最後成功"

        果 = 遮罩(原文, 環境={"RETRY_TOKEN": "3"})

        assert 果.文字 == 原文


def test_空字串不會炸() -> None:
    果 = 遮罩("")

    assert 果.文字 == ""
    assert 果.遮掉幾處 == 0

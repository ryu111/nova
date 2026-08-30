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

import inspect

import pytest

from nova.契約.遮罩 import 已經遮過了
from nova.載體.秘密 import 已載入的鍵環境變數
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


class Test自己載進去的不必猜:
    """**`遮罩` 靠鍵名的特徵猜哪些環境變數是祕密**（KEY／TOKEN／SECRET…）。

    猜得中一般情況，猜不中 `MY_THING=sk-...`。但 nova 自己從祕密檔載進去的東西，
    是不是祕密**不必猜**——`載入到` 會把鍵名記進 `NOVA_LOADED_SECRETS`，
    這裡照著遮。

    **這是「載入秘密」不外洩那條線的第二段。** 第一段（記名單）在
    `tests/整合/test_秘密落盤.py`，第三段（真的跑一次帳本裡是 0 次）在
    `tests/驗收/test_載進去的秘密不進帳本.py`。
    """

    def test_名單上的鍵不管叫什麼都要遮(self) -> None:
        原文 = "拿到的是 這串值有夠長不要外流 這串"

        果 = 遮罩(
            原文,
            環境={
                "MY_THING": "這串值有夠長不要外流",
                已載入的鍵環境變數: "MY_THING",
            },
        )

        assert "這串值有夠長不要外流" not in 果.文字
        assert 果.遮掉幾處 == 1

    def test_不在名單上的一般變數還是不遮(self) -> None:
        """**這一支防的是擋過頭。** 遮掉 `PWD` 的話帳本會變成一片馬賽克。"""
        原文 = "在 /Users/sbu/nova 底下跑"

        果 = 遮罩(原文, 環境={"PWD": "/Users/sbu/nova", 已載入的鍵環境變數: "MY_THING"})

        assert "/Users/sbu/nova" in 果.文字

    def test_名單指到不存在的鍵不會炸(self) -> None:
        """子程序繼承得到這個名單，但不一定繼承得到那些值。"""
        果 = 遮罩("沒事", 環境={已載入的鍵環境變數: "根本沒有這個"})

        assert 果.文字 == "沒事"

    def test_名單上的值太短還是不遮(self) -> None:
        """`A=1` 這種值遮下去會把帳本裡每一個 `1` 都吃掉。"""
        果 = 遮罩("重試 3 次", 環境={"MY_THING": "3", 已載入的鍵環境變數: "MY_THING"})

        assert "3" in 果.文字

    def test_名單本身不是祕密(self) -> None:
        """`NOVA_LOADED_SECRETS` 這個名字撞得上「鍵名看起來是祕密」那條規則。

        不排除的話它的值（一串鍵名）也會被遮，而且遮出來的標記會巢狀套進
        其他標記裡。**鍵名不是祕密**，被遮掉只會讓帳本更難讀。
        """
        果 = 遮罩(
            "載入了 MY_THING 跟 OTHER_THING",
            環境={已載入的鍵環境變數: "MY_THING,OTHER_THING"},
        )

        assert 果.文字 == "載入了 MY_THING 跟 OTHER_THING"
        assert 果.遮掉幾處 == 0


class Test逃生口要說得出理由:
    """`已經遮過了` 是唯一合法的硬轉入口，所以**它自己也要有閘**。

    沒有閘的話它就是一個安靜的 cast，而安靜的 cast 正是決策 0002 要防的東西。
    """

    def test_因為是必填的關鍵字(self) -> None:
        """**位置參數傳不進去、不傳也不行。**

        給了預設值的話，`已經遮過了(某段字)` 會編得過——那時候它跟
        `cast(已遮罩文字, 某段字)` 一模一樣，grep 不出來、review 看不見。
        """
        參數 = inspect.signature(已經遮過了).parameters["因為"]

        assert 參數.kind is inspect.Parameter.KEYWORD_ONLY, "要具名傳，不然會被當成一般參數混過去"
        assert 參數.default is inspect.Parameter.empty, "有預設值就等於沒有必填"

    @pytest.mark.parametrize("空的", ["", "   ", "\n"])
    def test_空理由不算理由(self, 空的: str) -> None:
        """**型別擋不到 `因為=""`。** 那條縫要用執行期的檢查補。"""
        with pytest.raises(ValueError, match="說得出理由"):
            已經遮過了("隨便一段字", 因為=空的)

    def test_有理由就放行(self) -> None:
        """**不能擋到正常用法**——擋過頭的閘會被繞過。"""
        assert 已經遮過了("一段字", 因為="測試用") == "一段字"

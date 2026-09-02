"""`轉接.可達嗎` 的四格行為表：什麼時候答得出來、什麼時候算不出來。

擋開跑的那道檢查（`命令列._工作流開跑前`）拿的就是這支的回傳值，
可是三支既有的整合測試都把 `命令列.可達嗎` monkeypatch 掉了——驗的是
`命令列` 那一側的擋／不擋邏輯，`轉接.可達嗎` 本體**零測試背書**。
於是這張表只活在文件與 docstring 裡：那是「宣稱」，不是保證。

表本身（負控紀錄那張）：

| 情況                              | 該回什麼 | 為什麼                       |
|-----------------------------------|----------|------------------------------|
| 跑得到執行檔、`--version` 結束碼 0 | `True`   | 環境說得出「在」             |
| 跑得到執行檔、`--version` 非 0     | `False`  | 環境真的說了不               |
| `找執行檔` 拋 `FileNotFoundError`  | `None`   | **算不出來**                 |
| 逾時／`OSError`                    | `None`   | 算不出來                     |
| `local`（不是 CLI）                | `None`   | 這一格不適用                 |

第三格是重點：`FileNotFoundError` **分不出**「codex 掛了」跟「這個 process 的
PATH 上沒有 codex」。後者是算不出來——`tests/conftest.py` 的 autouse fixture
與收件匣 daemon（launchd 的 PATH ≠ shell 的 PATH）都會落進這一格，
把它當成 `False` 就會在還沒開跑時擋掉整條線，而且沒人知道為什麼。
照 `載體/線.py` 的慣例：算不出來留空（`None`），不拿 `False` 頂替。
"""

from pathlib import Path

import pytest

from nova.載體.模型 import 轉接
from nova.載體.模型.執行 import 執行結果, 執行逾時

#: 假的執行檔路徑。這一份**不碰真的 CLI**：`找執行檔` 與子程序那一層都被換掉，
#: 真的去探一次是 `@pytest.mark.真cli` 那一層的事。
#: 相對路徑、而且不在 `/tmp` 底下：這條路徑從頭到尾沒有人會去開它。
假執行檔目錄 = Path("不存在的目錄/nova-測試用")


def _裝找得到(monkeypatch: pytest.MonkeyPatch) -> None:
    """讓 `找執行檔` 找得到東西——蓋掉 conftest 那個一律 raise 的 autouse fixture。"""

    def 假找(家: str, **_: object) -> Path:
        return 假執行檔目錄 / 家

    monkeypatch.setattr(轉接, "找執行檔", 假找)


def _裝假版本查詢(monkeypatch: pytest.MonkeyPatch, 結果: object) -> list[list[str]]:
    """把子程序那一層換成假的；`結果` 是例外就丟出去。回傳收到的參數，好驗它有多便宜。"""
    收到: list[list[str]] = []

    def 假跑(執行檔: Path, 參數: list[str], **_: object) -> 執行結果:
        assert 執行檔.name, "沒有執行檔就不該發版本查詢"
        收到.append(list(參數))
        if isinstance(結果, BaseException):
            raise 結果
        assert isinstance(結果, 執行結果)
        return 結果

    monkeypatch.setattr(轉接, "跑cli", 假跑)
    return 收到


class Test可達嗎的四格:
    """一格一支，格與格之間不准互相頂替。"""

    def test_版本查詢結束碼0是可達(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """環境說得出「在」：`True`。順帶釘住它**只發版本查詢**，不問真的一題。"""
        _裝找得到(monkeypatch)
        收到 = _裝假版本查詢(
            monkeypatch, 執行結果(標準輸出="claude 2.1.258", 標準錯誤="", 結束碼=0)
        )

        assert 轉接.可達嗎("claude") is True
        # 便宜到什麼程度算便宜：零 token 的版本查詢。真的問一題等於為了防燒
        # token 而燒 token——這一行就是那條線。
        assert 收到 == [["--version"]]

    def test_版本查詢結束碼非0是不可達(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """跑得到二進位、它自己回非 0：這是環境真的說了不，`False` 只給這一格。"""
        _裝找得到(monkeypatch)
        _裝假版本查詢(monkeypatch, 執行結果(標準輸出="", 標準錯誤="not logged in", 結束碼=1))

        assert 轉接.可達嗎("claude") is False

    def test_找不到執行檔是算不出來(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """**這一格是紅的那一格。**

        `找執行檔` 拋 `FileNotFoundError` 只證明「這個 process 的 PATH 上沒有」，
        證明不了「這家掛了」。兩者分不出來就是算不出來 → `None`，往放行倒。
        現況回 `False`，於是 conftest 的 autouse fixture 一生效，
        整合層 11 支測試就在還沒開跑時被擋下來。
        """

        def 擋(家: str, **_: object) -> Path:
            訊息 = f"找不到 {家} 的執行檔"
            raise FileNotFoundError(訊息)

        monkeypatch.setattr(轉接, "找執行檔", 擋)

        assert 轉接.可達嗎("codex") is None

    def test_逾時是算不出來(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """一道便宜的檢查自己卡住，不代表對面不在。"""
        _裝找得到(monkeypatch)
        _裝假版本查詢(monkeypatch, 執行逾時("版本查詢逾時"))

        assert 轉接.可達嗎("claude") is None

    def test_系統錯誤是算不出來(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`OSError`（權限、fd 用完、網路檔案系統抖一下）同理：沒問出結果。"""
        _裝找得到(monkeypatch)
        _裝假版本查詢(monkeypatch, OSError("Too many open files"))

        assert 轉接.可達嗎("claude") is None

    def test_local跳過這道檢查(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`local` 走 HTTP 沒有 CLI，就沒有零成本的版本查詢可用。

        不為了三家對稱而對它發一次真問答——直接回 `None`，而且**一次子程序都不起**。
        """
        收到 = _裝假版本查詢(monkeypatch, 執行結果(標準輸出="", 標準錯誤="", 結束碼=0))

        assert 轉接.可達嗎("local") is None
        assert 收到 == []

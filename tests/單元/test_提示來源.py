"""提示從哪來：**argv 是危險通道，長提示不准走它。**

## 為什麼偵測不可能

2026-08-30 派研究時，提示直接寫在雙引號字串裡，而裡面有反引號：

```
uv run nova 問 --用 codex "…請看 `docs/設計/` 底下…"
                                  ^^^^^^^^^^^ zsh 把它當命令替換
```

替換失敗之後那段字**完全消失**，nova 收到的是一份看起來正常的短提示。
它無從分辨「本來就沒有那段」跟「那段被吃掉了」——**沒有任何殘跡**。
程序照樣啟動、照樣燒完整的 token，然後交出一份對著殘缺題目寫的答案。

（同一批裡有一份是當場 parse error，那反而便宜——**無聲的那種才貴**。）

## 所以只能改通道

`--提示檔` 與 stdin 都不經過 shell 的解析：nova 自己開檔、自己讀管線。
argv 則是唯一會被展開的那條路。**長提示一律禁走 argv**——
判準是「換行或太長」，因為那兩件事都代表「這是組出來的，不是人打的」。

這條規則本身不精確（`"$(cat 檔)"` 是安全的卻也被擋），
**但那是刻意的**：nova 站在邊界上分不出安全的組法與危險的組法，
而被擋下來的那個用法有一個嚴格更好的替代（`--提示檔`）。
"""

import pytest

from nova.載體.提示來源 import argv太危險, 最長的argv提示


class Test人打得出來的照過:
    @pytest.mark.parametrize("提示", ["在嗎", "把某件事做完", "a" * 最長的argv提示])
    def test_短的單行安全(self, 提示: str) -> None:
        assert argv太危險(提示) is None


class Test組出來的一律擋:
    def test_含換行就擋(self) -> None:
        """**換行進得了 argv，一定是 shell 組的**——人不會在命令列打換行。"""
        assert argv太危險("第一行\n第二行") is not None

    def test_太長就擋(self) -> None:
        assert argv太危險("a" * (最長的argv提示 + 1)) is not None

    def test_邊界剛好不擋(self) -> None:
        """門檻要有測試釘住，不然調來調去沒人知道現在是多少。"""
        assert argv太危險("a" * 最長的argv提示) is None
        assert argv太危險("a" * (最長的argv提示 + 1)) is not None


class Test訊息要能照做:
    @pytest.mark.parametrize("危險的", ["有\n換行", "b" * (最長的argv提示 + 1)])
    def test_兩條安全的路都要講(self, 危險的: str) -> None:
        """**擋下來要能照做**，不然它只是個路障。"""
        訊息 = argv太危險(危險的)

        assert 訊息 is not None
        assert "--提示檔" in 訊息, 訊息
        assert "stdin" in 訊息, 訊息

    def test_要說得出為什麼(self) -> None:
        """不講原因的話，下一個人會以為這是任意的限制然後想辦法繞過。"""
        訊息 = argv太危險("有\n換行")

        assert 訊息 is not None
        assert "反引號" in 訊息 or "shell" in 訊息, 訊息

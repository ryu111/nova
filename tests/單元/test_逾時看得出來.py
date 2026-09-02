"""agy 自己收掉的逾時，要判成 `失敗代碼.逾時`，不是 `未知`。

## 為什麼信封看不出來

agy 的 print mode 逾時之後，回的是一份**解得開的失敗信封**：`status != "SUCCESS"`、
`response` 空、但 `usage` 有值（實錄上的量級是 input 134,241／output 14,942）。
`_解析agy` 於是走 `_分類`，而 `_樣式表` 只有 model／auth／quota／permission 四組，
**沒有 timeout**，所以落到 `失敗代碼.未知`。帳本上 32 筆 `unknown` 就是這樣來的。

## 為什麼用時間判、不用錯誤字串

我們手上**沒有** agy 逾時那份信封的 `error` 原文（帳本沒存這一格，事後無法回推）。
猜一個關鍵詞塞進 `_樣式表` 會產生一條看起來查證過、其實沒有的規則，比留白更貴。
所以判準是執行層的事實：**`response` 空、usage 非零、而且實際耗時 ≥ 我們請求的
print-timeout** ——這三件事都不需要讀對面的錯誤訊息。

## 判成逾時換到的是什麼

**不是「這次能繼續跑」。** `失敗代碼.逾時` 在 `_終局表` 一樣對到 `終局.結果未知`，
可編輯下一樣不換腦、一樣護欄——那是 at-most-once 的地基，不動。
換到的是誠實：下一次五分鐘就能從帳本查出根因，而不是靠排除法回推一整晚。
"""

import json

from nova.契約.模型回應 import 失敗代碼, 終局
from nova.載體.模型.解析 import 解析agy
from nova.載體.模型.轉接 import 逾時看得出來

#: 照 `tests/整合/實錄/agy_bad.txt` 的欄位形狀手寫，usage 的數字取自帳本上的一筆
#: `call_finished`（`duration_ms=303510`、`text_len=0`）。**error 原文我們沒有**，
#: 所以刻意留一句不可能命中任何樣式的字——真的抓到原文之前不准假裝知道。
逾時信封 = json.dumps(
    {
        "conversation_id": "",
        "status": "ERROR",
        "response": "",
        "error": "<原文未知>",
        "duration_seconds": 303,
        "num_turns": 0,
        "usage": {
            "input_tokens": 134241,
            "output_tokens": 14942,
            "thinking_tokens": 0,
            "cache_read_tokens": 0,
            "total_tokens": 149183,
        },
    }
)


class Test逾時看得出來:
    def test_耗時到了請求的上限就判成逾時(self) -> None:
        答 = 解析agy(逾時信封, 1)
        assert 答.失敗代碼 is 失敗代碼.未知, "前提：光看信封確實分不出來，分得出來就不需要這支函式"

        改寫 = 逾時看得出來(答, 實際耗時秒=302.0, 請求逾時秒=300.0)
        assert 改寫.失敗代碼 is 失敗代碼.逾時

    def test_改寫不准把usage洗掉(self) -> None:
        """usage 掉光正是 SIGKILL 那條路（`逾時的回應` 寫死 0/0）的壞處，別在這裡重演。"""
        改寫 = 逾時看得出來(解析agy(逾時信封, 1), 實際耗時秒=302.0, 請求逾時秒=300.0)
        assert 改寫.用量.輸入token == 134241
        assert 改寫.用量.輸出token == 14942
        assert 改寫.原始結束碼 == 1

    def test_沒到時間就回來的不准被誤判成逾時(self) -> None:
        """12 秒就吐 ERROR 的是別的病（模型名打錯之類）。誤判會讓帳本上的逾時失去意義。"""
        改寫 = 逾時看得出來(解析agy(逾時信封, 1), 實際耗時秒=12.0, 請求逾時秒=300.0)
        assert 改寫.失敗代碼 is 失敗代碼.未知

    def test_判成逾時之後終局還是結果未知(self) -> None:
        """agy 的 log 寫著 `printed=43`——它中止前真的做了 43 步，工作區可能已經被改。

        所以這支函式改的是**誠實度**不是重試權：`終局` 不准因為改寫而變得比較樂觀。
        """
        改寫 = 逾時看得出來(解析agy(逾時信封, 1), 實際耗時秒=302.0, 請求逾時秒=300.0)
        assert 改寫.終局 is 終局.結果未知

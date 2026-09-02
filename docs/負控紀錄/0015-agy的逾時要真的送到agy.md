# nova 決定的逾時要真的送到 CLI 那一側，而且 nova 的鐘要比 CLI 的鐘晚響

## 現場

`agy` 的 print mode 有自己的 5 分鐘上限，nova 從來沒對它說過話：

```
$ ~/.local/bin/agy --help | grep -in timeout
20:  --print-timeout                 Timeout for print mode wait (default 5m0s)
```

`TDD階段預設逾時秒 = 3600.0`（`迴圈/角色工廠.py:19`）寫在 nova 自己的殼裡，
讀 code 的人會以為那是保證。**真正生效的上限一直是 300 秒，差 12 倍。**

出血量（2026-09-02 掃 `~/.local/state/nova/專案/*/帳本/*.jsonl`）：
agy 的 `unknown` 32 筆、`input+output = 9,740,511` token、`text_len=0` 有 26 筆、
`duration_ms` 中位數 304,008。agy 自己的 log 寫著
`Print mode: timed out after 1494 polls (printed=43)`——**它中止前真的做了 43 步**。

`attempt=1` 就有 17 筆，所以病因不在接力傳過去的提示，也不在額度。

## 改法

| 保證 | 落點 |
|---|---|
| 旗標真的送出去 | `_agy組參數` 加 `--print-timeout`，值由 `決定逾時秒(選項)` 算 |
| 順序：agy 先響 | `agy逾時餘裕秒 = 30.0`，`_agy那側的上限秒 = nova逾時秒 - min(餘裕, nova逾時秒/2)` |
| 逾時看得出來 | `轉接.逾時看得出來(答, 實際耗時秒, 請求逾時秒)`，純函式，在 `_問一次` 解析後改寫 |
| **那個純函式真的被叫到** | `_問一次` 解析後那一行 `self._認出CLI自己收的逾時(...)`（`轉接.py:464`） |

**第四條是後補的，而且它一度沒有任何刀砍得到。** 前三條的測試全是純函式直呼
（`tests/單元/test_逾時看得出來.py`），接線那一行整行拔掉，2074 支照樣全綠——
判得對不等於會被叫到。這正是 CLAUDE.md 判準 3：**墊片證明的是轉遞形狀，不是可達性**。
補的是 `tests/整合/test_模型轉接.py::Test全鏈路::test_agy自己收的逾時走完整鏈路要判成逾時`，
它走 `詢問 → _問一次 → 解析 → 改寫` 的真實路徑，時間由子程序**真的睡出來**。

**餘裕不能是 0。** 兩邊同時到的話 nova 的 SIGKILL 先落地，走 `逾時的回應`——
那條路 **usage 被寫死 0/0**，連燒了多少都不知道。agy 自己收的話信封還在、usage 還在。
短逾時（60 秒）不能被餘裕吃光，所以餘裕最多吃一半。

**判逾時用時間，不用錯誤字串。** 這張票開的時候手上沒有 agy 逾時信封的 `error` 原文，
猜一個關鍵詞塞進 `解析.py` 的 `_樣式表` 會產生一條看起來查證過、其實沒有的規則。
規則是執行層的三個事實：`response` 空、usage 非零、實際耗時 ≥ 我們請求的 print-timeout。

**判成逾時換到的不是重試權。** `失敗代碼.逾時` 在 `_終局表` 一樣對到 `終局.結果未知`
（`printed=43` 就是理由：工作區可能已經被改過），換到的是誠實：
下次五分鐘就能從帳本查出根因，不必靠排除法回推一整晚。

## 手動驗證（人在 shell 裡跑一次，不進測試套件）

```
$ agy --output-format json --mode plan --print-timeout 1s --model gemini-3.7-flash-high --print "說一個字"
{"conversation_id":"47b23957-...","status":"ERROR","response":"",
 "error":"timeout waiting for response","duration_seconds":0,"num_turns":1,
 "usage":{"input_tokens":0,"output_tokens":0,...}}
結束碼=0
```

三件事當場落地：

1. **agy 真的遵守傳進去的值**——1 秒就收，不是 5 分鐘。
2. **Go duration string 吃得下**（`"1s"`）。所以 `_agy上限旗標值` 印成 `"1770s"` 這個形狀是安全的。
3. **逾時的 `error` 原文是 `timeout waiting for response`，而結束碼是 0。**
   這一格先記在這裡當證據；`_樣式表` 要不要加這條關鍵詞是**另一張票**，
   這張票不順手做（而且時間判準本來就不依賴它）。

## 四刀負控（各做一次、看它紅、`cp` 還原）

| # | 破壞什麼 | 結果 |
|---|---|---|
| 1 | 刪掉 `_agy組參數` 裡 `--print-timeout` 那一行 | `test_agy的argv要帶print_timeout而且值跟著逾時秒走` 紅（`test_模型轉接.py:443`） |
| 2 | `agy逾時餘裕秒` 改成 `0.0`（agy 的鐘＝nova 的鐘） | `test_agy的鐘要比nova的鐘早響` 紅（`test_模型轉接.py:460`） |
| 3 | `逾時看得出來` 改成第一行就 `return 答` | `test_耗時到了請求的上限就判成逾時` 紅（`test_逾時看得出來.py:58`） |
| 4 | **把 `轉接.py:464` 那一行接線整行拔掉**（實作三個函式一個字都不動） | `test_agy自己收的逾時走完整鏈路要判成逾時` 紅（`test_模型轉接.py:123`），**其餘 62 支全綠** |

第 4 刀的實跑輸出（2026-09-02，`cp` 備份／還原，沒有用 `git checkout --`）：

```
E  AssertionError: agy 自己收掉的逾時被收成 unknown：帳本上那 32 筆查不出根因，就是這一格漏的
E  assert <失敗代碼.未知: 'unknown'> is <失敗代碼.逾時: 'timeout'>
1 failed, 62 passed in 1.31s
```

**「其餘 62 支全綠」才是這一刀的重點**——包含 `tests/單元/test_逾時看得出來.py` 那 5 支。
接線斷掉的時候，純函式測試一支都不會叫；能叫的只有走真實路徑那一支。

四刀都已還原（還原後 `tests/整合/test_模型轉接.py` 59 passed）。

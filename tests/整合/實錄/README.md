# 實錄：三家 CLI 的真實輸出

這些是 `claude` 2.1.251、`codex` 0.149.0、`agy` 1.1.22 在本機**真的跑出來**的輸出，
錄於 2026-08-29。用途是讓整合測試不必燒 token 就能驗解析邏輯。

| 檔案 | 情境 | 結束碼 |
|---|---|---|
| `claude_ok.json` / `claude_ok2.json` | `claude -p --output-format json` 成功 | 0 |
| `claude_bad.txt` | 指定不存在的模型 | 1 |
| `claude_quota.txt` | 跑到一半撞到 session limit（**半合成**，見下） | 假 CLI 一律 0 |
| `codex_ok.jsonl` / `codex_ok2.jsonl` | `codex exec --json` 成功 | 0 |
| `codex_bad.txt` | 指定不存在的模型 | 1 |
| `agy_ok.json` | `agy -p --output-format json` 成功 | 0 |
| `agy_stream.jsonl` | `agy --output-format stream-json` | 0 |
| `agy_bad.txt` | 指定不存在的模型 | 1 |
| `agy_timeout.json` | agy 自己的 `--print-timeout` 響了（**合成**，見下） | 0 |

**`agy_timeout.json` 是半合成的。** `status`／`response`／`error`／`num_turns` 與
**結束碼 0** 來自 `agy --print-timeout 1s` 的手動實跑（記在
`docs/負控紀錄/0015-agy的逾時要真的送到agy.md`）；`usage` 那三個數字是**填上去的**，
取自帳本 2026-09-02 那 32 筆之一（`input=134241 output=14942 duration_ms=303510`）——
因為真跑那次 1 秒就收，usage 全 0，測不出「usage 不准在改寫時掉光」。

**`claude_quota.txt` 是半合成的。** `result` 那句（session limit 用完、
`resets 4:40pm (Asia/Taipei)`；**原文逐字只放在檔案裡，這份 README 不准抄**——
`test_委派給其他llm.py::test_結果未知的退出碼是3而不是1` 拿這份 README 當假 CLI
的輸出，抄一次額度原文就會被 `_額度樣式` 命中，整支分類測試變紅）與 `usage`
四個數字、`total_cost_usd`、`duration_ms` 逐字抄自帳本
`20260902T071651Z-63dc3e` 的第 5 次呼叫（`input=22 output=15711
cache_read=367252 cache_creation=51719 cost=1.106949 duration=218s`）：
那次跑了 218 秒、`permission=write`，**不是「請求沒出門」**。
`api_error_status: 429` 是**填上去的**——帳本只記了 `failure_code=quota-exhausted`
與原文，沒有留 HTTP 狀態；`num_turns`／`session_id`／`uuid` 同樣是填的。

**結束碼那一欄對它沒有意義**：假 CLI 一律 0（`conftest.py:125-135` 的
`假CLI內容` 只做 `sys.stdout.write`），分類靠信封裡的 `is_error`
（`解析.py:168-169`），不靠結束碼。真 claude 那次的結束碼沒被記下來，
所以**不准有任何測試去比對它**。

吃它的測試一律用**時間**判逾時，**不准有任何規則去比對 `error` 那句話**：
`解析.py` 的 `_樣式表` 要不要加 timeout 關鍵詞是另一張票。

**唯一的改動**：session／conversation／thread id 換成固定的假 UUID，
讓 fixture 可重現，也不把本機 session 識別碼放進 public repo。其餘一個位元組都沒動。

`codex_ok.jsonl` 開頭那兩條 `--dangerously-bypass-hook-trust` 事件是 cmux shim 加的雜訊，
**故意留著**——解析器必須能忽略它認不得的事件，這是真實世界的樣子。

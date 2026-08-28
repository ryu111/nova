# 實錄：三家 CLI 的真實輸出

這些是 `claude` 2.1.251、`codex` 0.149.0、`agy` 1.1.22 在本機**真的跑出來**的輸出，
錄於 2026-08-29。用途是讓整合測試不必燒 token 就能驗解析邏輯。

| 檔案 | 情境 | 結束碼 |
|---|---|---|
| `claude_ok.json` / `claude_ok2.json` | `claude -p --output-format json` 成功 | 0 |
| `claude_bad.txt` | 指定不存在的模型 | 1 |
| `codex_ok.jsonl` / `codex_ok2.jsonl` | `codex exec --json` 成功 | 0 |
| `codex_bad.txt` | 指定不存在的模型 | 1 |
| `agy_ok.json` | `agy -p --output-format json` 成功 | 0 |
| `agy_stream.jsonl` | `agy --output-format stream-json` | 0 |
| `agy_bad.txt` | 指定不存在的模型 | 1 |

**唯一的改動**：session／conversation／thread id 換成固定的假 UUID，
讓 fixture 可重現，也不把本機 session 識別碼放進 public repo。其餘一個位元組都沒動。

`codex_ok.jsonl` 開頭那兩條 `--dangerously-bypass-hook-trust` 事件是 cmux shim 加的雜訊，
**故意留著**——解析器必須能忽略它認不得的事件，這是真實世界的樣子。

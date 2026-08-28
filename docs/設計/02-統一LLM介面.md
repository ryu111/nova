# 02 · 統一 LLM CLI 介面：把「哪一家」變成可抽換的細節

> 依 `AGENT_ARCHITECTURE.md` §12：先產出契約，再寫實作。§4.3：跨層傳遞一律 schema 化。

## 為什麼

**立即目的：委派。** `codex` 與 `agy` 現在就裝好了，能馬上接手一部分工作，
分擔 Claude 的壓力與使用額度。所以建置順序是 **codex／agy 先、claude 後**——
先做能減負的那兩家，而不是先做要被減負的那一家。


nova 的公式是 `harness[loop[llm]]`。要讓「換一個模型、行為流程不變」成立，
上層就不能知道底下是 `claude`、`codex` 還是 `agy`。現在每家的輸出長這樣：

```
claude  {"type":"result","is_error":false,"subtype":"success","total_cost_usd":0.034,...}
codex   JSONL 事件流：thread.started → item.completed → turn.completed{usage}
agy     {"conversation_id":...,"status":"SUCCESS","response":"...","usage":{...}}
```

三種形狀、三套欄位名、三種錯誤表達。不正規化，歧義會一路累積到停止判斷（§4.3）。

## 抽象切在哪：切證據，不切設定

| 切法 | 判斷 |
|---|---|
| 統一 options（模型名、權限模式…） | ❌ 會做出漏水的抽象。實測：同一個產品的 claude **CLI** 權限選項是 `manual`，**SDK** 是 `default`，自己就對不齊 |
| 統一**證據 schema** | ✅ 「跑幾輪、花多少、為什麼停」每家都有對應物，而且這正是 §4.3 要求 schema 化的東西 |

所以：

```
介面吸收（transport：各家怎麼講同一件事）
  ├ 啟動形狀：claude/agy 是旗標 -p，codex 是子指令 exec
  ├ 輸出解析：type=result ／ JSONL 事件 ／ event=result  →  同一個 回應
  └ 錯誤分類：結束碼 + envelope 欄位  →  同一組 ASCII 失敗代碼
介面漏出（policy：呼叫端必須自己決定，藏起來就是幫使用者做風險決策）
  ├ 模型字串（各家命名空間不交集，硬翻譯只會翻錯）
  ├ 權限／沙箱等級
  └ 工作目錄
```

## 最關鍵的一條：結束碼不是任務成敗

**三家實測結果一致**：CLI 的結束碼只分「跑完 vs 基礎設施壞掉」。

| 情境 | claude | codex | agy |
|---|---|---|---|
| 成功 | 0 | 0 | 0 |
| 模型不存在 | 1（但 `subtype` 仍是 `"success"`） | 1 | 1 |
| **模型拒答／答錯** | **0** | **0** | **0** |

所以契約裡的欄位叫 `執行成功`，**不叫 `成功`**。任務成敗必須由 nova 的迴圈用證據判定
（§3.2 evidence + stop rule）。介面若提供一個 `成功: bool`，上層就會拿它當停止條件——
那正是 CLAUDE.md 硬規則第 4 條與 §8 反模式二禁止的「模型說完成了」。

`claude_bad.txt` 這份實錄專門釘死這件事：`is_error:true`、`api_error_status:404`，
但 `subtype` 還是 `"success"`。**不准看 subtype。**

## 基準形狀是本地模型，不是 Claude

`nova[llm]` 的 llm 是**換腦，不是換身體**。換上本地模型時，行為流程必須一模一樣。

這條決定了介面該對齊誰：

```
本地模型（llama.cpp／ollama）  只有腦：提示進去、字出來、token 數
        ↑ 介面對齊這個形狀
claude / codex / agy           腦 + 一整套自帶載體（工具、session、權限、壓縮）
        ↑ 這些額外的東西一律關掉
```

**對齊最低的那個，不對齊最豐富的那個。** 理由不是節儉，是正確性：

- 只要 nova 依賴 Claude 的 context 壓縮，換上本地模型行為就變了——
  「換腦但行為一樣」當場破功。
- 每家自帶的載體**互不相同**，依賴它們等於讓「nova 的行為」變成
  「這次剛好用了哪一家的行為」。那正是 §2.3 說的「靠提示詞不靠載體」的變形版：
  **靠廠商不靠自己**。
- 廠商的載體也不見得什麼都包。缺的那塊還是要 nova 自己補，
  結果變成「一半靠自己、一半靠廠商」，最難維護的那種。

所以每個轉接器的職責是**把該家的載體關到最小**，讓它退回成一顆腦：

| 要關掉 | claude | codex | agy |
|---|---|---|---|
| 工具 | `--allowedTools`／`--tools` 清空 | `--sandbox read-only` + `-a never` | `--mode plan` |
| 家目錄設定 | 疑似 `--bare`（**語意未驗證**，見缺口 2） | `CODEX_HOME` 換掉 | `~/.gemini` 設定隔離未查 |
| 自帶 system prompt | `--system-prompt ""` | 查不到 | 查不到 |

**這張表每一格都要有測試背書**，不然「有沒有真的關掉」只能靠讀 code——
依最高原則第一條，那等於沒有保證。目前只有 claude 那欄查證過部分，其餘是待辦。

### 那 `claude-agent-sdk` 呢？

SDK 底層就是 `claude --output-format stream-json`（實測 `subprocess_cli.py:566`），
它提供的 hooks／session／interrupt 都是**Claude 專屬的載體能力**。
依上面的理由，nova 的載體**不建在它上面**。

它的正當用途只有一個：當 Claude 是**使用者介面**（人坐在終端機前面）時，
`.claude/settings.json` 的 hook 一行呼叫 nova——那和 `.pre-commit-config.yaml`、
`gates.yml` 同構，是**又一個薄轉接**，不是 nova 的地基。

依 01 文件的保證／加速器表：**廠商載體能力一律歸在加速器欄，永遠不能是保證。**

## 不對稱能力怎麼處理（三選一，不是三取一）

| 差異性質 | 處理 | 例子 |
|---|---|---|
| 能用最小公倍數抹平 | **介面吸收** | cwd 一律走 `subprocess(cwd=)`；context 一律併進提示字串（agy 1.1.22 實測不讀 stdin） |
| 有值 vs 沒值 | **降級成 Optional** | 成本只有 claude 有 → `用量.成本美金: float \| None`。**不要估算**，猜出來的成本比沒有更危險 |
| 整組方法有或沒有 | 拆小 Protocol | 逐工具白名單只有 claude 有 → 等真的有呼叫端再拆（現在不寫） |

**不做能力查詢表**（`supports("cost") -> bool`）。那會讓呼叫端到處寫 `if`，
打掉開放封閉原則，而且布林表 mypy 檢查不到。

## 執行檔路徑是參數，不信 PATH

本機實測：`which claude codex` 指到 cmux 的 shim，走 shim 跑 `codex exec --json`
會多吐兩條 `--dangerously-bypass-hook-trust` 的雜訊事件，直接跑真二進位就沒有。
所以執行檔路徑當參數收進來（和 `規則表._外部指令` 的理由同源：PATH 會讓本地與 CI 跑到不同版本）。

同理，解析器**必須容忍認不得的行與事件**（`codex_ok.jsonl` 第一行是純文字
`Reading additional input from stdin...`，根本不是 JSON）。但**整份都解不動時要
fail-closed 回 `unknown`**，不是靜默成功。

## 建置順序

1. `契約/模型回應` —— 三家共用的證據 schema
2. `載體/模型/解析` —— 三支純函式，餵實錄就能測
3. `載體/模型/執行` —— 一支 subprocess 執行器（路徑、cwd、逾時、env 全當參數收）
4. **codex 與 agy 轉接器**（先做這兩家：現在就能拿來委派、分擔額度）
5. `nova 問 --用 <家> <提示>` —— 第一個真實呼叫端
6. claude 轉接器
7. 迴圈層才接 SDK（如果那時真的需要 hook 與 interrupt）

## 怎麼驗證而不燒 token

| 層 | 做法 | 速度 |
|---|---|---|
| 單元 | 純函式解析器直接餵 `tests/整合/實錄/` 的真實 envelope | 毫秒 |
| 整合 | 假 CLI 腳本 + 明確二進位路徑，測 cwd／逾時／結束碼／env 全鏈路 | 秒 |
| 驗收（真 CLI） | 打真實 CLI，只斷言 envelope 形狀不斷言模型講什麼 | **不進 CI，見下** |

實錄是 record/replay 的 record 階段，錄於 2026-08-29，來源見 `tests/整合/實錄/README.md`。

## 已知缺口

1. **真 CLI 的 contract test 不接進 CI。** agy 的 CI 認證環境變數查不到（用 Google OAuth，
   token 在 `~/.gemini/antigravity-oauth-token`），claude 要塞 repo secret。
   掛 pytest marker、排除在兩個閘之外，本地手動跑。
   **這代表「外部 CLI 換版本改了輸出格式」目前沒有自動防護**——
   agy issue #76（1.0.0 在 non-TTY 下 stdout 全空但結束碼 0）就是這種失敗的實例。
2. **「把各家載體關到最小」那張表只查證了一部分。** claude 的 `--bare` 到底丟掉什麼、
   codex 與 agy 怎麼隔離家目錄設定與自帶 system prompt，都還沒查。
   在補齊之前，「換腦但行為一樣」**沒有測試背書**——只是設計意圖。
3. **成本只有 claude 給。** codex 與 agy 只有 token 數。要成本得自己接價目表，現在不做。
4. **各家的自帶 system prompt 還沒關掉。** 實測「只回覆兩個字：可以」這句十來個字的提示：

   | 家 | 輸入 token | 說明 |
   |---|---|---|
   | codex | 17341 | `--ignore-user-config --ignore-rules` 只擋掉**使用者的**設定，擋不掉內建 system prompt |
   | agy | 14515 | 同上，而且 agy 連工具清單都還在（`init` 事件列了 50 幾個工具） |

   也就是說 `--mode plan`／`--sandbox read-only` 擋住的是**工具會不會被執行**，
   不是**模型腦裡有什麼**。「換腦但行為一樣」目前只在「工具不會亂動檔案」這一層成立，
   在「模型收到什麼指令」這一層還沒成立。
   查證方向：codex 的 `-c/--config` 能不能覆寫 instructions、agy 有沒有對應開關。
   **在補齊之前不要宣稱三家行為一致。**

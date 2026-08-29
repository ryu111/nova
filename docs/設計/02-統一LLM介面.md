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

### 權限與設定隔離：兩個刻意漏出的 policy

| 選項 | 預設 | 為什麼漏出 |
|---|---|---|
| `權限`（唯讀／可編輯／全開） | **唯讀** | 藏起來就是幫使用者做風險決策。預設最嚴——忘了設不會變成放行 |
| `隔離設定`（要不要擋家目錄設定） | **True** | 讀了 `~/.claude/CLAUDE.md`，nova[claude] 就跟 nova[codex] 行為不同 |

各家的落地（全部對著 `--help` 查證，而且 `-m 真cli` 真跑過）：

| | claude | codex | agy |
|---|---|---|---|
| 唯讀 | `--restricted --add-dir <工作目錄> --tools Read,Grep,Glob` | `--sandbox read-only` | `--mode plan --add-dir <工作目錄>`（**擋不住寫，見下**） |
| 可編輯 | `--restricted --add-dir <工作目錄> --tools <清單> --allowedTools <同一份> --permission-mode acceptEdits` | `--sandbox workspace-write` | `--mode accept-edits --add-dir <工作目錄>` |
| 全開（跳權限＋關沙箱） | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` | `--dangerously-skip-permissions` |
| 生圖 | ❌ 沒有 | ❌ 沒有 | `generate_image` **可用**，但只有**全開**權限下檔案才進得了工作目錄；可編輯下圖留在 `~/.gemini/.../brain/` 而 CLI 假回報成功（見下節） |
| 隔離設定 | `--setting-sources ""` | `--ignore-user-config --ignore-rules` | ❌ 查不到 |
| 續接對話 | `--resume <id>` | `exec resume <id>`（**子指令**，不吃 `--sandbox`） | `--conversation <id>` |
| 對話落地 | 一律留 | 預設 `--ephemeral` 不留，**要續接得先關掉** | 一律留 |
| 預設型號 | 不設 | `gpt-5.6-luna`（高階 `gpt-5.6-sol`） | `gemini-3.7-flash-high` |
| 推理強度 | 有 `--effort`，目前不用 | **沒有旗標**，走 `-c model_reasoning_effort="max"` | **包在型號裡** |
| 不隔離 | `--restricted`（設定檔照樣隔離，CLAUDE.md 仍被讀） | 只留 `--ephemeral` | — |

**原本以為的 claude 取捨已經解除。** 一度認為 `--bare` 是唯一能關掉 CLAUDE.md
自動探索的旗標，而它會連 keychain 與 OAuth 一起關掉（訂閱登入變成「Not logged in」）。

實測後找到 `--setting-sources ""`：**設定檔與 CLAUDE.md 都讀不到，而且訂閱登入照樣能用**。
所以 `隔離設定=True` 走這一條，**不要換回 `--bare`**。
`test_claude隔離設定之後拿不到自動注入的指引` 同時守兩件事：
自動注入的指引真的拿不到、而且認證沒被弄壞。

**「自動注入」與「主動讀取」是兩件事。** 唯讀的工具白名單從 `""` 改成
`Read,Grep,Glob` 之後，模型會自己用 Read 去讀工作目錄裡的 CLAUDE.md——
那不是隔離破了，那正是唯讀該有的行為。所以那支測試改成在一個乾淨的 tmp 目錄裡
問「有沒有收到自動注入的指引」：那裡沒有任何 CLAUDE.md 可讀，答案只可能來自注入。

教訓：一個限制寫進文件之後，要標清楚它是**查證過的事實**還是**當下沒找到更好的做法**。
這一條是後者，而它撐了不到一天。

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
| 驗收（真 CLI） | `pytest -m 真cli`：打真實 CLI，只斷言 envelope 形狀 | **不進 CI，手動跑** |

**真 CLI 那層不能省，實測抓到三個假 CLI 抓不到的 bug：**

| bug | 為什麼假 CLI 抓不到 |
|---|---|
| codex 的 `--sandbox` 與 `--approve-for-me` **互斥**，一起給 exit 2 | 墊片不會抱怨旗標組合 |
| claude 的 `--tools <tools...>` 是**變長參數**，會把後面的提示吞掉 | 墊片不解析參數 |
| claude 的 `--bare` 連 **keychain 與 OAuth 都不讀**，訂閱登入會死 | 墊片不需要認證 |
| `codex exec resume` **不吃** `--sandbox` 與 `--approve-for-me`，給了 exit 2 | 墊片不檢查子指令的旗標集合 |
| agy 的 JSON 偶爾夾**未跳脫的控制字元**，嚴格解析當場失敗 | 錄下來的樣本剛好沒有 |

**墊片證明的是轉遞形狀，不是可達性。** 這句話在這裡有三個實例。

實錄是 record/replay 的 record 階段，錄於 2026-08-29，來源見 `tests/整合/實錄/README.md`。

## 持久對話：記住 sid ＋ 下一輪帶回去

```bash
uv run nova 問 --用 codex --保留對話 "記住：暗號是芭樂"
# → [codex] 完成 · … · sid 01a04aa2-…
uv run nova 問 --用 codex --續接 01a04aa2-… "暗號是什麼"
```

三家各有各的講法，介面吸收成一個 `續接` 欄位：

| | claude | codex | agy |
|---|---|---|---|
| 續接 | `--resume <id>` | `exec resume <id>`（**子指令**） | `--conversation <id>` |
| 落地 | 一律留 | 預設 `--ephemeral` 不留 | 一律留 |

**codex 有兩個坑，都是真跑才會知道的**：

1. `exec resume` **不吃** `--sandbox` 與 `--approve-for-me`（給了 exit 2）——權限沿用原 session。
2. `--ephemeral` 不落地，續接完就再也接不下去。所以續接時一律不加。

`保留對話` 預設 `False`（省磁碟）；`續接` 有值時自動視為要留。

## 解析要容忍未跳脫的控制字元

JSON 規格說字串裡的控制字元必須跳脫，但真實工具會直接吐原始字元——
實測 agy 的 `response` 欄位偶爾夾了未跳脫的控制字元，`json.loads` 嚴格模式當場解不動。

解不動的下場是 fail-closed 回**結果未知**，而結果未知在可編輯模式下**不准重試**——
一個顯示層的小瑕疵會變成整條工作流停擺。所以解析器改用
`json.JSONDecoder(strict=False)`：寬鬆解析的風險遠小於誤判成結果未知。

## 可編輯與唯讀：三家的強度差很多，而且都不是我原本以為的那樣

這一節整段都是**實測**，每一行都真的跑過。起因是加了一支
`test_可編輯真的寫得出檔案`——只看檔案系統、不看模型怎麼說——三家立刻紅了兩家。

### 實測矩陣

| 問題 | claude | codex | agy |
|---|---|---|---|
| 唯讀擋得住寫檔嗎 | ✅ 白名單裡沒有 Write／Edit／Bash | ✅ `--sandbox read-only` | ❌ **`--mode plan` 擋不住**（見下） |
| 唯讀看得到工作目錄嗎 | 要白名單有 Read（見下） | ✅ | 要 `--add-dir`，不給就連讀都被 auto-deny |
| 可編輯寫得進工作目錄嗎 | 要三條旗標湊齊（見下） | ✅ | 要 `--add-dir`（見下） |
| 可編輯擋得住寫**工作目錄外面**嗎 | ❌ 檔案工具擋得住，**Bash 繞得過** | ✅ **OS 層拒絕**（operation not permitted） | 走 shell 的工具被 headless 權限系統 auto-deny |

**三家裡只有 codex 有真的邊界。** 這一格決定了「可編輯」在各家的意思不一樣，
而介面沒辦法抹平它——所以寫成文件與測試，不寫成 `supports()` 布林表。

### claude 的唯讀：`--tools ""` 不是唯讀，是小黑屋

help 原文「Use "" to disable all tools」的 all 是**真的 all**——連 Read 都沒了。
實測叫它讀工作目錄裡的一個檔案：

```
I can't do this one — I don't have any file access tools available in this session.
My only tools here are Context7 documentation lookups...
```

唯讀的意思是**看得到但不准改**，所以走白名單 `--tools Read,Grep,Glob`：
實測讀得到檔案內容，而叫它寫檔會回「我只有唯讀類的工具，沒有 Write、Edit、Bash」——
**擋在工具層，不是靠模型自律**。唯讀也帶 `--restricted --add-dir`，
把 Read 一起關在工作目錄裡。

順帶看到一件事：那次回應說它還有 **Context7 可用**——`--tools` 管不到 MCP 工具。
要一起關掉得再加 `--strict-mcp-config`，還沒做（見已知缺口）。

### claude 的可編輯要三條旗標，缺一不可

| 旗標 | 少了它會怎樣 |
|---|---|
| `--tools Read,Write,Edit,Bash,Grep,Glob` | 沒有 Write／Edit 可用 |
| `--allowedTools <同一份清單>` | **隔離設定之下卡在「pending approval」，一個字都寫不出來** |
| `--restricted --add-dir <工作目錄>` | 自己猜路徑——實測寫進了 **nova 的 repo 根目錄**，還順手在 `/tmp/claude-workdir/` 另建一份 |

第二條的原文回應是：
「I need permission to create the file — the write request is pending approval on your end.」
拿掉 `--setting-sources ""`（不隔離）就寫得出來——推測 `acceptEdits` 要靠
「這個目錄已被信任」那份使用者設定，隔離之後那份讀不到。

第三條的 `--restricted` 是**加速器不是保證**：它的 help 原文說會
「confine the file tools to the working directories」，實測也真的擋下 Write 越界。
但同一次實測裡改叫它用 Bash 重導向，檔案就寫出去了。
claude CLI **沒有任何 OS 層沙箱旗標**（`--help` 查證過，只有說明文字提到
「recommended only for sandboxes」——也就是預期由外面的人提供沙箱）。

`test_claude的可編輯沒有真的邊界這是已知事實` 釘住這一條：它斷言的是**擋不住**。
哪天 claude 補了沙箱，那支會紅，逼我們回來改這份文件。

### codex：`--approve-for-me` 的邊界是假的，`--sandbox workspace-write` 才是真的

`--approve-for-me` 的 help 原文：
「Route approval requests through automatic review using the workspace-write sandbox」——
**自動審核**，不是不准。實測叫它 `printf '芒果乾' > ~/x.txt`：

```
agent_message     這個目標路徑位於目前工作區外，需要額外權限才能寫入。
command_execution /bin/zsh -lc "printf '芒果乾' > /Users/sbu/nova-越界測試.txt"
                  exit_code: 0
agent_message     成功，已寫入。
```

模型自己說了「在工作區外」，然後自動審核把它核准了。

換成 `--sandbox workspace-write`，同一條指令：

```
agent_message  失敗：系統拒絕寫入 `/Users/sbu/nova-越界測試.txt`（operation not permitted）
```

而寫 cwd 照樣成功。所以**可編輯改用 `--sandbox workspace-write`**。
代價要講清楚：這個沙箱同時關掉網路與工作區外的寫入，所以可編輯這一級**裝不了套件**。
要那個就用全開。

（測試越界時**不能拿 `/tmp` 當「工作目錄外」**——codex 的 workspace-write
把它也算成可寫的，實測寫得進去。`test_codex的可編輯有真的邊界` 因此寫家目錄。）

### agy：沒有唯讀這一級，而 `--add-dir` 決定檔案落到哪

三件實測，一件比一件反直覺：

1. **不給 `--add-dir`**：檔案工具寫到 `~/.gemini/antigravity-cli/scratch/`，
   而且照樣回報 `SUCCESS`。追 `--output-format stream-json` 才看到
   `write_to_file` 的 `TargetFile` 指到那裡——**模型沒說謊，它真的寫了，只是寫到別的地方**。
2. **不給 `--add-dir` 而叫它讀 cwd 的檔案**：工具被 headless 的權限系統 auto-deny
   （`a tool required the "command" permission that headless mode cannot prompt for`），
   回一個空的 `response`。`_成功但沒話說算未知` 會把它降成結果未知。
3. **給 `--add-dir` 而且 `--mode plan`**：檔案**照樣寫進 cwd**。模型嘴上說
   「我已建立執行計畫，請確認後我將開始建立檔案」——而檔案當下已經建好了。
   `--sandbox`、`--mode plan --sandbox` 都試過，一樣擋不住。

#### 這一格改過一次，過程比結論值錢

第一版的判斷是：既然 plan 擋不住寫，那唯讀就**不給 `--add-dir`**，換一條真的成立的
保證——「唯讀的 agy 動不到工作目錄」（由 1 與 2 背書）。形狀很漂亮，而且測得出來。

**它把唯讀的用途一起換掉了。** 唯讀的 agy 連讀都讀不到，而 nova 唯一的唯讀呼叫端是
**工作流的審查員**——一個被要求「指出具體的檔案與行號」卻看不到檔案的審查員，
只會回一個空 response，被降成結果未知，把整條工作流卡住。

保證的形狀對了、用途沒了，**那不是保證，是把功能關掉**。所以換回來：

- 三種權限都給 `--add-dir`（`test_agy三種權限都要給add_dir`）
- **agy 的唯讀明確標成加速器不是保證**（`test_agy的唯讀擋不住寫檔這是已知事實`
  斷言的就是「擋不住」）
- 唯讀看得到工作目錄變成三家共同的契約（`test_唯讀看得到工作目錄裡的檔案`）

誠實標示比假保證好，也比一個看不見東西的審查員好。

**升級路徑（尚未做）**：唯讀模式下由 nova 自己在跑完之後比對工作目錄有沒有被改動，
有的話把終局降成結果未知。那是**偵測型**保證不是預防型——檔案已經被改了才發現——
但它是 nova 自己拿得出來的東西，不必等 agy。

第 3 點特別值得記：那是**假成功裡最難抓的一種**——`status: SUCCESS`、`response` 也有話說、
內容還說得頭頭是道。`_成功但沒話說算未知` 攔不到它。
**只有真的去看檔案系統才會紅。**

## 權限的第三級：全開

原本只有唯讀／可編輯兩級，而三家 CLI 都各有一條「跳過權限檢查並關掉沙箱」的路。
一律禁掉看起來安全，實際上會逼人繞過介面自己拼指令——那更糟，因為繞過去的那條路
沒有任何測試背書。所以把它收進介面，但**收成一個不可能誤觸的等級**：

| | claude | codex | agy |
|---|---|---|---|
| 全開 | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` | `--dangerously-skip-permissions` |

三條防線，各有一支測試守著：

| 保證 | 測試 |
|---|---|
| 唯讀與可編輯**絕對不會**冒出危險旗標 | `test_危險旗標只准出現在全開` |
| 三家都真的有一條全開的路（不是假的） | `test_全開才有危險旗標` |
| 忘了設不會變成全開 | `test_全開不是預設` |
| codex `exec resume` 不吃這條（權限沿用原 session） | `test_codex續接時不准出現危險旗標` |

`呼叫選項.權限` 預設值是 `權限.唯讀`，門面與 CLI 各自的 `_挑權限()` 在
`全開` 與 `可編輯` 都沒給時回唯讀——**最嚴的那一邊當預設**，這一條在三處都成立。

## 成功但沒話說＝結果未知

實測 agy 生圖（headless、`--print` 模式，可編輯權限）：

```
tool  generate_image  ACTIVE
tool  generate_image  ERROR        ← 這一行的歸屬後來證明是誤讀，見下一節
RESULT  status= SUCCESS | response= '' | error= None
--- 工作目錄 --- （空的）
```

envelope 是 `status: SUCCESS`、`error: null`、`response: ""`，工作目錄卻什麼都沒有。
**診斷被整個吞掉，只剩一個空字串。** 照原本的解析器，這會回 `終局.成功`，
上游於是以為圖生好了。

`_成功但沒話說算未知` 把這種回應降成**結果未知**：

- 當成功 → 上游以為事情辦完了（實際什麼都沒發生，或發生了一半）。
- 當確定失敗 → 接力會去換下一顆重做，而副作用可能已經產生。
- 結果未知 → 停下來讓人看。三值就是為了這一格。

三支解析器 `解析claude`／`解析codex`／`解析agy` 都是
`_成功但沒話說算未知(_解析X(...))` 的薄包裝——**同一條規則寫一次**，
不必在三個地方各記一次。負控：把 `_成功但沒話說算未知` 改成直接 `return 答`，
`Test成功但沒話說` 的四支立刻紅（已跑過）。

## 生圖：原本的結論是錯的，而且錯在哪很值得記

上一節第一版的結論是「**agy 的生圖在 headless 模式不可用**」，而且寫了
「find 全機也找不到任何新圖檔」。**兩句都是錯的。**

2026-08-29 拿 `--output-format stream-json` 把原始串流整段撈出來看，真相是：

```
generate_image  → 成功。圖產在 ~/.gemini/antigravity-cli/brain/<sid>/star_<ts>.jpg
run_command     → 被擋。模型接著想用 sips 把 jpg 轉成 png 搬進工作目錄：
                  {"error":{"type":"TOOL_ERROR",
                   "message":"permission check failed for command \"sips ...\": user denied"}}
envelope        → status: SUCCESS、error: null、response: ""
```

錯的是**後面那道 shell**，不是生圖。第一版看到 `ERROR` 就記到 `generate_image` 頭上，
又只在工作目錄裡找檔案（圖在家目錄的隱藏目錄底下，`find` 的範圍根本沒涵蓋），
兩個誤讀疊起來就變成一句斬釘截鐵的假結論。

### 三種權限下的實測矩陣

| 權限 | `generate_image` | 檔案落到哪 | nova 回什麼 |
|---|---|---|---|
| 唯讀（`--mode plan`） | **沒試**（見下方開放問題） | — | — |
| 可編輯（`--mode accept-edits`） | ✅ 成功 | `~/.gemini/antigravity-cli/brain/<sid>/*.jpg`——**`--add-dir` 管不到它** | `結果未知`（空回應降級擋下） |
| 全開（`--dangerously-skip-permissions`） | ✅ 成功 | ✅ **工作目錄**（實測 `star.png`、1,070,181 位元組、1024×1024） | `成功`，文字帶檔案路徑與大小 |

用量參考：全開那次 50,694 → 1,607 token（含 12,188 快取讀取、903 思考）。
生圖比純文字貴一個量級，**要不要開這條路是成本決定不是能力決定**。

### 這件事真正的教訓

不是「生圖能不能用」，是**空回應降級這條保證救了一次**。

可編輯那次，CLI 說 `SUCCESS`、圖也真的產出來了，但工作目錄空空如也——
如果解析器照 envelope 回「成功」，上游會以為圖在手上。降級成 `結果未知` 之後，
呼叫端拿到的是「不知道發生什麼事」，於是有人去看原始串流，才挖出真相。

**這條保證的正當性沒有因為誤記而動搖，反而被這次驗證了。** 改的只是註解裡
錯誤的歸屬——誤記會讓下一個人去修錯的地方。

### 開放問題（今晚沒驗）

唯讀（`plan` 模式）擋不擋得住生圖？**傾向擋不住**：圖是寫到
`~/.gemini/antigravity-cli/brain/` 而不是 workspace，唯讀的白名單管的是
workspace 內的檔案工具。如果真的擋不住，那就是**唯讀權限的第四個破口**，
要進 `docs/設計/02` 的權限表而不是這一節。下次驗。

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
3.5 **`--tools` 管不到 MCP 工具。** 實測 claude 唯讀（白名單只有 `Read,Grep,Glob`）時，
   模型自己說它還有 Context7 的 `resolve-library-id` 與 `query-docs` 可用。
   也就是說「把載體關到最小」目前漏了 MCP 這一層——`--strict-mcp-config` 應該能補，
   還沒查證也還沒實測。在補齊之前，**隔離設定不涵蓋 MCP**。
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
（原本的缺口 5「終態是二值」已修，見下節。）


## 終局三值（已修）

`回應.終局` 取代了原本的 `執行成功: bool`。布林會把「結果未知」壓成「確定失敗」，
而那兩者的重試政策**相反**。

| 終局 | 意思 | 可以重試嗎 | 哪些失敗代碼 |
|---|---|---|---|
| `success` | 做完了 | 不必 | `none` |
| `failed` | **確定沒做**——請求根本沒出門 | 可以 | `auth`、`model-not-found`、`usage` |
| `unknown` | **不知道做了沒**——可能已經產生副作用 | **不可以** | `upstream`、`timeout`、`interrupted`、`unknown` |

分界線是**「請求出門了沒」**，不是「錯得嚴不嚴重」。

對應關係寫成**表**（`_終局表`）不是 `if` 鏈：加一個失敗代碼＝加一列。
`test_每個失敗代碼都要有明確的終局` 驗的是**表裡有沒有那一列**，不是「回傳值合不合法」——
`終局判定` 有 fail-closed 的預設值，所以回傳值永遠合法，那樣驗等於沒驗。
（這個弱點是負控抓出來的：新增一個失敗代碼卻不進表，原本的測試不會紅。）

`nova 問` 的退出碼跟著分開：**0 成功、1 確定失敗、3 結果未知**。
腳本看到 3 就知道不准重跑。

從簡：`upstream` 把 429（確定沒做）和 5xx（可能做了）壓在一起，所以連 429 都不准重試。
要放寬就把 `upstream` 拆成兩個代碼——等真的有重試迴圈嫌它太保守再拆。
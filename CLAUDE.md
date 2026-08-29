# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## nova 是什麼

**宿主反轉架構**：`nova = harness engineering[loop engineering[llm]]`

一般的看法是「LLM 是主角，外面包一層工具」。nova 反過來：**模型是被載體包住的元件**，
系統的行為由外層決定，不由模型自己決定。中括號是包含關係——最外層是載體，
載體裡面是迴圈，迴圈裡面才是模型呼叫。

第一份規格是 [`docs/AGENT_ARCHITECTURE.md`](docs/AGENT_ARCHITECTURE.md)（Harness / Loop / Graph
三層架構規範）。動手前先讀它；本檔只寫「在這個 repo 怎麼落地」，不重複它的內容。

## 常用指令

```bash
uv sync                          # 建 .venv、裝好開發相依（第一次或改了相依之後）
uv run pytest                    # 全部測試
uv run pytest tests/單元         # 只跑單元層
uv run pytest tests/驗收/test_專案骨架.py::test_測試分三層   # 單一測試
uv run pytest -k 骨架 -x         # 關鍵字篩選，第一個紅就停
uv run pytest --lf               # 只重跑上次紅的
uv run ruff check . && uv run ruff format .   # lint 與格式
uv run mypy                      # 型別（strict）

uv run nova 閘 提交               # commit 前的閘（7 條，約 1.2 秒，第一個紅就停）
uv run nova 閘 ci --全部跑完      # CI 跑的那一組（8 條，約 6.5 秒，一次看到所有紅的）
uv run nova 檢查指令 "<指令>"     # 這條 shell 指令是不是在繞過閘門

python -c 'import nova; print(nova.問("提示", 用="codex").文字)'   # 門面：一次 import 就能用
uv run nova 問 --用 codex "提示"                       # 委派一件事，分擔額度
uv run nova 問 --用 codex,agy "提示"                   # 接力：前一顆失敗換下一顆
uv run nova 問 --用 codex --模型 gpt-5.6-sol "提示"     # 高階推理（預設是 gpt-5.6-luna）
uv run nova 問 --用 codex --保留對話 "提示"             # 留下 sid
uv run nova 問 --用 codex --續接 <sid> "接下去問"       # 持久對話
uv run nova 工作流 --用 codex --審查用 agy "任務"       # 跑一輪完整 TDD
uv run pytest -m 真cli                                 # 真的打三家 CLI（燒 token，兩個閘都排除）
```

一律走 `uv run`，不要先 activate venv——忘了 activate 會靜默跑到系統 Python 3.9。

## 開發模式：TDD，每個階段跑的量不同

先寫會紅的測試 → 看到它紅 → 最少的程式碼讓它綠 → 全綠下重構。
通則在 `~/.claude/rules/測試.md`，這裡只寫 nova 的接線：

| 階段 | 跑什麼 | 怎麼跑 | 實測 |
|---|---|---|---|
| 內圈（寫 code 時） | 手上那幾支 | `uv run pytest -k <關鍵字> -x` | < 1 秒 |
| 工具呼叫前 | 禁令指令攔截 | `.claude/settings.json` 的 PreToolUse hook | 30 毫秒 |
| commit 前 | `nova 閘 提交`（7 條） | pre-commit hook 自動 | 約 1.2 秒 |
| commit 訊息 | 繁體中文檢查 | commit-msg hook 自動 | 毫秒 |
| PR / push main | `nova 閘 ci --全部跑完`（8 條） | GitHub Actions，check 名 `gates` | 約 20 秒 |

**分層是時間預算不是分類學**：`tests/單元/` 只放純函式，會 fork 子程序的一律進
`tests/整合/`。`pytest tests/單元` 是提交閘唯一的測試規則，混進 fork 的測試等於
每次 commit 都付一次那個錢——實測混著的時候提交閘 7.1 秒，分乾淨之後 1.2 秒。
由 `tests/驗收/test_專案骨架.py::test_單元層不准fork子程序` 機械擋下。

**規則只寫一份**：全部登記在 `src/nova/載體/規則表.py`，pre-commit／CI／agent hook
三個地方各只有一行呼叫 nova。想加規則就加在規則表，**不要往 YAML／JSON 裡塞邏輯**——
設定檔裡的程式碼沒辦法測試，等於沒有保證。

**階段就是資源排程**：規則依階段（靜態 → 型別 → 測試）由小到大、一次一條序列跑。
快的先給回饋，重的後跑，而且不同時吃滿 CPU——資源互搶造成的紅燈是雜訊不是訊號。
平行只發生在 pytest 內部（`-n <3/4 核心> --dist worksteal`），且 `serial` 標記的測試單獨序列跑。
**不吃滿核心**：實測 16 核這台，worker 越多越慢（4 個 3.44 秒、12 個 4.02 秒、16 個 4.25 秒），
因為這套測試不是 CPU-bound，瓶頸是子程序啟動。3/4 是留餘裕的通則，調整點是 `規則表.平行成數`。

`test-count` 的基準由環境變數 `NOVA_TEST_COUNT_BASE` 決定：本地比 `HEAD`，
CI 比 `origin/main`（CI checkout 之後工作區就是 HEAD，不換基準會整條空轉）。
抓不到基準時 fail-closed 當場紅。

**還沒補的缺口**：squash 合併的 commit 訊息繞過 commit-msg hook（訊息由 GitHub 從 PR
標題組出來），**只有本地加速器、沒有伺服器端保證**。

- **`gates` 這個 job 名稱是 main 保護規則的 required check context，不准改。**
- **不准 `git commit --no-verify`**，**不准 `gh pr merge --admin`**——
  現在由 `nova 檢查指令` 機械攔截，不再只是提示詞。要繞過閘門，先修閘門。

## 程式風格與嚴謹性

通則在 `~/.claude/rules/軟體工程.md`（YAGNI 決定何時抽象、SOLID 決定抽象長什麼樣、
三次法則、組合優先於繼承、多型用 Protocol）。這裡只寫 nova 的機械化部分：

| 判準 | 由誰擋 | 門檻 |
|---|---|---|
| 分支複雜度（KISS） | ruff `C901` | `max-complexity = 8` |
| 參數／分支／語句過多（SRP） | ruff `PLR0913` / `PLR0912` / `PLR0915` | 預設 |
| 死程式碼、註解掉的程式碼、未用參數 | ruff `F` / `ARG` / `ERA` | 一律紅 |
| 布林參數陷阱 | ruff `FBT` | 布林要具名傳 |
| 里氏替換、介面隔離 | `mypy strict` | 簽章不相容當場紅 |
| 例外訊息、docstring、路徑用法 | ruff `EM` / `D` / `PTH` | 一律紅 |

**`pyproject.toml` 裡停用 `N`、`PLC2401`、`RUF001-003`、`D400/D415/D403` 的註解不要刪。**
那幾組內建「識別字只能是英文、標點只能是半形」的假設，和本專案的繁體中文命名衝突——
開著會產生 266 條噪音把 8 條真問題淹掉。這是實測數字，不是猜的。

## 機密

repo 是 **public**——洩漏一次就是永久的，GitHub 的快取與別人的 clone 收不回來。
`.env`、`*.key`、`*.pem`、`credentials.json`、`secrets/` 已在 `.gitignore`，
而且由 `tests/驗收/test_機密不進版控.py` 背書：它直接問 `git check-ignore`，
並掃過 `git ls-files` 確認沒有機密檔案「已經被追蹤」（已追蹤的檔案寫進 `.gitignore` 也擋不住）。
這支測試同時掛在 pre-commit，所以 commit 當下就會擋。

## 三層在這個 repo 的落點

```
Harness  載體：context + 工具 + 狀態 + 權限 + 可觀測性      → src/nova/載體/
  └── Loop  迴圈：行動 → 觀察 → 驗證 → 停止                → src/nova/迴圈/
        └── 模型呼叫與工具結果
邊上流動的結構化證據                                        → src/nova/契約/
```

- **`src/nova/載體/`** — 判別法：把模型從圖上刪掉，還站著的全部都住這裡。
  六大組成見規格 §2.1。
- **`src/nova/迴圈/`** — 一個迴圈要湊齊七欄位才算成立（§3.2）：
  trigger、goal、memory、action policy、evidence、feedback、**stop rule**。
  缺 stop rule 的不是迴圈，是成本漏洞。
- **`src/nova/契約/`** — 跨層傳遞一律 schema 化。自由段落會逼下游重建上游語意，
  多階段後歧義累積會改變結論（§4.3）。

### Graph 層現在故意不存在

公式 `harness[loop[llm]]` 少了規格裡的 Graph，這不是漏掉，是照 §10 的建置順序：
graph 是第 4 階，**看過真實 trace、隱式控制流程真的難測了才畫**。
在那之前新增 `src/nova/圖/`、節點註冊表、編排 DSL 都算違規——
§8 反模式一就是「還不理解工作就先畫圖」。要開這一層，先拿出 trace 說明哪條路徑分歧到
線性寫不動了。

## 宿主反轉的判準：保證住在哪

判準**不是「誰呼叫誰」**，是**保證住在哪**：

```
工具模式  規則寫在 prompt 裡 → 虛線的懇求，可以被忽略，漏了沒人發現
          → 再補一條 rule → 縫縫補補

宿主模式  規則寫在包住執行者的程式碼裡 → 實線的包圍環
          → 執行者「不用知道、不用記得、也違反不了」
```

「執行者」泛指任何不可靠的執行者，LLM 只是目前最常見的一種。
所以**驗收權不在執行者手上**：它自認完成不算完成，判準綠了才算。

由此推出四條判準（比「有測試背書」更鋒利，違反時會產生**假的安全感**）：

1. **只以文件或 skill 形式存在的規範等於不存在。**
2. **文件若宣稱某件事「會被自動擋下」，把關器就必須存在且有測試背書。**
   宣稱有卻沒有，**比沒有規範更糟**——讀的人會以為不用自己檢查。
3. **墊片證明的是轉遞形狀，不是可達性。** 假 CLI／mock 測得出「參數有沒有傳對」，
   測不出「那個執行檔到底存不存在」。要補一格用真 PATH 跑的端到端。
4. **用規避換來的綠是假綠。** 執法只掃模組層的 import，把 import 搬進函式就能變綠。

### 現在哪些是殼、哪些還不是

| | 對誰而言是殼 | 狀態 |
|---|---|---|
| 8 條閘 + GitHub ruleset | 對「寫 code 的 agent」 | ✅ 已經是殼 |
| `nova 問` | 對「被委派的 LLM」 | ❌ **還是工具模式**——它是對話偶爾呼叫的 CLI，不是對話誕生的地方 |

`nova 問` 不是走錯路：它是「執行核」第 ② 步（`for 訊息 in 詢問(任務)` 那一行）的雛形，
缺的是包住它的 ①③④——**出生前就擋**（秘密、預算鎖、熔斷）、
**它說的話唯一的出路是 journal**、**終態分類**。那是迴圈層的工作。

## 這個 repo 的硬規則

1. **測試是唯一的驗收介面。** 任何行為保證都要有會 fail 的測試背書。
   新增保證時先寫紅的那支，再寫實作。改完保證要附**固定負控**：
   故意破壞一次，證明測試真的會紅（例：`mkdir nova && uv run pytest tests/驗收`
   必須紅在 `test_採用_src_layout_而非_flat_layout`）。
2. **`docs/AGENT_ARCHITECTURE.md` 是外部規格原文，一個字都不准改。**
   ruff 已用 `extend-exclude = ["docs"]` 擋掉格式化工具。要修正理解寫在別的檔案裡。
3. **文件宣稱存在的東西必須真的存在。** `tests/驗收/test_文件即事實.py` 會掃 CLAUDE.md
   與 `docs/設計/*.md`，反引號裡的測試函式名與檔案路徑都要對得上。
   這是被一次真實失誤逼出來的：一組測試因為寫檔的錨點沒對上而**靜默沒寫進去**，
   pytest 照樣綠，而 PR 說明已經在宣稱它們存在了。`test-count` 抓不到——
   它只擋「測試變少」，擋不了「我以為我加了」。
4. **`pyproject.toml` 是唯一設定來源。** 不開 `pytest.ini`、`setup.py`、`setup.cfg`、
   `.ruff.toml`——`tests/驗收/test_專案骨架.py` 會抓。
5. **不得以「模型說完成了」當停止條件**，不得建議「換更強的模型」當第一修復，
   不得讓同一個模型自寫自評（§8 反模式二、§12）。
6. **診斷順序：環境 → 回饋 → 流程。** 拿不到檔案／跨 session 掉狀態 → 載體；
   有動作但沒證據就停 → 迴圈；該跑的節點沒跑 → 圖。錯誤紀錄要寫「發生什麼、在哪、
   哪一層擁有修復」，「agent 表現不好」不是可行動的診斷。

## 目前狀態

`載體/` 有兩段實作：

1. **機械化閘**（設計見 [`docs/設計/01-機械化閘.md`](docs/設計/01-機械化閘.md)）
2. **統一 LLM CLI 介面**（設計見 [`docs/設計/02-統一LLM介面.md`](docs/設計/02-統一LLM介面.md)）——
   `nova 問 --用 codex|agy|claude "提示"`，三家同形。立即用途是**委派工作、分擔 Claude 額度**。

```bash
uv run nova 問 --用 codex "幫我看 X"        # stdout 只有模型講的話，可以直接 pipe
uv run nova 問 --用 agy --json "幫我看 X"   # 結構化證據（終局、失敗代碼、token、成本）
```

退出碼分三種：**0 成功、1 確定失敗、3 結果未知**。3 代表「不知道工作做了沒」
（逾時被殺、輸出解析不出來），**腳本不准重跑**——重跑會把可能已經做過的事再做一次。

介面的設計基準是**本地模型**（只有腦），不是 Claude（腦 + 一整套自帶載體）。
各家自帶的工具、session、家目錄設定一律關掉——依賴它們會讓 nova 的行為變成
「這次剛好用了哪一家的行為」。哪幾條旗標做這件事由
`tests/整合/test_模型轉接.py::Test把各家載體關到最小` 背書。
**已知只做到一半**：工具擋住了，各家內建的 system prompt 還沒（實測十來字的提示，
codex 吃 17341 input token、agy 吃 14515）。

**各家的預設型號**（都經 `--help` 與實跑查證）：

| 家 | 預設 | 高階 | 推理強度怎麼給 |
|---|---|---|---|
| codex | `gpt-5.6-luna` | `gpt-5.6-sol` | **沒有 `--effort`**，走 `-c model_reasoning_effort="max"` |
| agy | `gemini-3.7-flash-high` | — | **包在型號裡**（`agy models` 實測） |
| claude | 不設 | — | 有 `--effort` 但目前不用 |

**設定隔離走 `--setting-sources ""`**（實測：CLAUDE.md 讀不到，而且訂閱登入照樣能用）。
**不要換回 `--bare`**——那條連 keychain 與 OAuth 都不讀，訂閱使用者會直接掛掉。

**持久對話**：`--保留對話` 記下 sid，下一輪 `--續接 <sid>` 就接得回去。
codex 有兩個真跑才知道的坑：`exec resume` 不吃 `--sandbox`／`--approve-for-me`（exit 2），
而且 `--ephemeral` 不落地就續接不到。

**真 CLI 測試不能省**（`pytest -m 真cli`）。它抓到三個假 CLI 抓不到的 bug：
codex 的 `--sandbox` 與 `--approve-for-me` 互斥、claude 的 `--tools` 是變長參數會吞掉提示、
claude 的 `--bare` 不讀 keychain。**墊片證明的是轉遞形狀，不是可達性。**

3. **角色與工作流骨架**（設計見 [`docs/設計/03-角色與工作流.md`](docs/設計/03-角色與工作流.md)）——
   `迴圈/` 開工了，這是 §10 建置順序的第 2 階。

```
語言模型（腦）  詢問(提示) → 回應        可換：claude／codex／agy／本地
角色（身分）    固定系統提示 ＋ 一顆腦    換腦不換身分
工作流（流程）  狀態機決定下一步          回頭邊由轉移表表達
```

TDD 五階段：`測試(模型) → 驗證紅(機械) → 實作(模型) → 驗證綠(機械) → 審查(模型，換一顆腦)`。
**驗證是機械判準不是角色**——硬規則 4 禁止自寫自評；而且它出現兩次。

狀態機是**純函式轉移表**，所以測試零 LLM、零 token。**這不是圖層**：
單一路徑加兩條回頭邊，屬迴圈七欄位的 action policy 與 stop rule。

已做過的固定負控（證明防護真的會紅，不必重推）：

| 破壞什麼 | 結果 |
|---|---|
| `mkdir nova`（破壞 src layout） | `test_採用_src_layout_而非_flat_layout` 紅 |
| 從 `.gitignore` 拿掉 `.env` | `test_git_本人確認會忽略[.env]` 紅 |
| 直接 `git push origin main` | 被 ruleset 擋下（`Changes must be made through a pull request`） |
| 測試檔留了簡體字 | `nova 閘` 的 `lang-traditional` 紅，指到檔名行號 |
| `規則表.py` import 沒排序 | `nova 閘` 的 `ruff-check` 紅，commit 被擋 |
| 寫一個分支複雜度 9 的函式 | `ruff-check` 紅在 `C901 too complex (9 > 8)` |
| 新增失敗代碼卻不進 `_終局表` | `test_每個失敗代碼都要有明確的終局` 紅（原本那支不會紅，靠負控才發現） |
| `_成功但沒話說算未知` 改成直接 `return 答` | `Test成功但沒話說` 四支紅（空回應又被當成功） |
| codex 可編輯換回 `--approve-for-me` | `test_codex的可編輯有真的邊界` 紅（真跑 CLI，檔案寫進家目錄） |
| `git rm` 掉整支測試檔 | `test_整支測試檔被git_rm掉要擋` 紅（基準改走 ls-tree 之前會**放行**） |
| gates.yml 拿掉 `NOVA_TEST_COUNT_BASE` | `test_CI把測試數基準指到base_branch` 紅 |
| gates.yml 拿掉 `git fetch` 那步 | `test_CI有先把基準抓下來` 紅 |
| 把 `test_repo檢查.py` 搬回 `tests/單元/` | `test_單元層不准fork子程序` 紅，指到檔名與痕跡 |
| 解析 claude 時改看 `subtype` 而非 `is_error` | `test_模型不存在_不准看subtype` 紅（實錄裡失敗案例的 `subtype` 也是 `"success"`） |
| 把 `timeout` 的終局改成 `failed` | `test_可能已經做了一半的是結果未知[timeout]` 紅 |
| 新增失敗代碼但不進 `_終局表` | `test_每個失敗代碼都要有明確的終局` 紅 |
| 把 `驗證紅` 的期望改成綠 | 狀態機與工作流共 9 支紅 |
| 把 `跑工作流` 的步數上限拿掉 | `test_來回不停會撞到步數上限` **掛住跑不完**（證明沒有 stop rule 就是成本漏洞） |
| 讓驗證階段改由角色做（自寫自評） | `test_判準階段的步驟結果帶紅綠模型階段不帶` 等 4 支紅 |
| 某條閘忘了排除 `真cli` 標記 | `test_兩個閘都排除真cli` 紅 |
| 讓 `--審查用` 可以跟 `--用` 同一家 | `test_審查用不能跟用同一家` 紅 |
| `派工` 讓兩家共用同一個 `執行檔` | `test_執行檔不准誤用到審查那家` 紅 |
| 門面多匯出一個名字 | `test_門面很小` 紅 |
| 平行度改回 `-n auto` | `test_規則表用的是算出來的數字不是auto` 紅 |
| `平行成數` 改成 1.0（吃滿） | `test_不會吃滿` 等 5 支紅 |
| 接力在可編輯下遇到結果未知也換腦 | `test_結果未知在可編輯時不准換` 等 2 支紅 |
| 接力全掛時不留「試過誰」的證據 | `test_全部失敗要留下試過誰的證據` 等 2 支紅 |
| 逾時預設調回 300 秒 | `test_預設夠寬` 紅 |
| 文件提到一支不存在的測試 | `test_文件提到的測試都真的存在` 紅 |
| codex 的 `-c` 值沒包引號（TOML 解析不出來） | `test_codex的推理強度值是合法TOML` 紅 |
| claude 的隔離換回 `--bare` | `test_claude用setting_sources隔離而不是bare` 紅 |
| codex 續接時仍給 `--sandbox` | `test_codex續接時不准給sandbox或核准旗標` 紅 |
| 解析器改回嚴格 JSON | `test_response裡有原始換行也解得動` 紅 |
| 禁令改回「拆不開一律擋」 | `test_拆不開但沒有禁令要放行` 紅 |

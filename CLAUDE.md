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

uv run nova 閘 提交               # commit 前的閘（7 條，約 2 秒，第一個紅就停）
uv run nova 閘 ci --全部跑完      # CI 跑的那一組（8 條，約 3 秒，一次看到所有紅的）
uv run nova 檢查指令 "<指令>"     # 這條 shell 指令是不是在繞過閘門
```

一律走 `uv run`，不要先 activate venv——忘了 activate 會靜默跑到系統 Python 3.9。

## 開發模式：TDD，每個階段跑的量不同

先寫會紅的測試 → 看到它紅 → 最少的程式碼讓它綠 → 全綠下重構。
通則在 `~/.claude/rules/測試.md`，這裡只寫 nova 的接線：

| 階段 | 跑什麼 | 怎麼跑 | 實測 |
|---|---|---|---|
| 內圈（寫 code 時） | 手上那幾支 | `uv run pytest -k <關鍵字> -x` | < 1 秒 |
| 工具呼叫前 | 禁令指令攔截 | `.claude/settings.json` 的 PreToolUse hook | 30 毫秒 |
| commit 前 | `nova 閘 提交`（7 條） | pre-commit hook 自動 | 約 2 秒 |
| commit 訊息 | 繁體中文檢查 | commit-msg hook 自動 | 毫秒 |
| PR / push main | `nova 閘 ci --全部跑完`（8 條） | GitHub Actions，check 名 `gates` | 約 15 秒 |

**規則只寫一份**：全部登記在 `src/nova/載體/規則表.py`，pre-commit／CI／agent hook
三個地方各只有一行呼叫 nova。想加規則就加在規則表，**不要往 YAML／JSON 裡塞邏輯**——
設定檔裡的程式碼沒辦法測試，等於沒有保證。

**階段就是資源排程**：規則依階段（靜態 → 型別 → 測試）由小到大、一次一條序列跑。
快的先給回饋，重的後跑，而且不同時吃滿 CPU——資源互搶造成的紅燈是雜訊不是訊號。
平行只發生在 pytest 內部（`-n auto --dist worksteal`），且 `serial` 標記的測試單獨序列跑。

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

## 這個 repo 的硬規則

1. **測試是唯一的驗收介面。** 任何行為保證都要有會 fail 的測試背書。
   新增保證時先寫紅的那支，再寫實作。改完保證要附**固定負控**：
   故意破壞一次，證明測試真的會紅（例：`mkdir nova && uv run pytest tests/驗收`
   必須紅在 `test_採用_src_layout_而非_flat_layout`）。
2. **`docs/AGENT_ARCHITECTURE.md` 是外部規格原文，一個字都不准改。**
   ruff 已用 `extend-exclude = ["docs"]` 擋掉格式化工具。要修正理解寫在別的檔案裡。
3. **`pyproject.toml` 是唯一設定來源。** 不開 `pytest.ini`、`setup.py`、`setup.cfg`、
   `.ruff.toml`——`tests/驗收/test_專案骨架.py` 會抓。
4. **不得以「模型說完成了」當停止條件**，不得建議「換更強的模型」當第一修復，
   不得讓同一個模型自寫自評（§8 反模式二、§12）。
5. **診斷順序：環境 → 回饋 → 流程。** 拿不到檔案／跨 session 掉狀態 → 載體；
   有動作但沒證據就停 → 迴圈；該跑的節點沒跑 → 圖。錯誤紀錄要寫「發生什麼、在哪、
   哪一層擁有修復」，「agent 表現不好」不是可行動的診斷。

## 目前狀態

`載體/` 有第一段實作：機械化閘（設計見 [`docs/設計/01-機械化閘.md`](docs/設計/01-機械化閘.md)）。
`迴圈/` 與 `契約/` 除了 `檢查結果` 之外仍是空的——迴圈是 §10 建置順序的下一階。

已做過的固定負控（證明防護真的會紅，不必重推）：

| 破壞什麼 | 結果 |
|---|---|
| `mkdir nova`（破壞 src layout） | `test_採用_src_layout_而非_flat_layout` 紅 |
| 從 `.gitignore` 拿掉 `.env` | `test_git_本人確認會忽略[.env]` 紅 |
| 直接 `git push origin main` | 被 ruleset 擋下（`Changes must be made through a pull request`） |
| 測試檔留了簡體字 | `nova 閘` 的 `lang-traditional` 紅，指到檔名行號 |
| `規則表.py` import 沒排序 | `nova 閘` 的 `ruff-check` 紅，commit 被擋 |
| 寫一個分支複雜度 9 的函式 | `ruff-check` 紅在 `C901 too complex (9 > 8)` |

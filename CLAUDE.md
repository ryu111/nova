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
uv run ruff check . && uv run ruff format .   # lint 與格式
uv run mypy                      # 型別（strict）
```

四道閘全綠才算完成：`pytest` / `ruff check` / `ruff format --check` / `mypy`。
一律走 `uv run`，不要先 activate venv——忘了 activate 會靜默跑到系統 Python 3.9。

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

骨架階段：三個子套件只有說明用的 `__init__.py`，還沒有實作。
測試 11 支，全部在驗證骨架本身（src layout、三層子套件、三層測試目錄、設定不散落、
規格文件在位）。尚未 `git init`。

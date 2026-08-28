# nova

[![gates](https://github.com/ryu111/nova/actions/workflows/gates.yml/badge.svg)](https://github.com/ryu111/nova/actions/workflows/gates.yml)

**宿主反轉架構**：`nova = harness engineering[loop engineering[llm]]`

模型不是系統的主人，是被載體（harness）包住的元件。載體決定模型看得到什麼、
能做什麼；迴圈（loop）決定什麼觸發下一次嘗試、何時停止。

- 架構規範（nova 的第一份規格）：[docs/AGENT_ARCHITECTURE.md](docs/AGENT_ARCHITECTURE.md)
- 給 AI 的工作守則：[CLAUDE.md](CLAUDE.md)

## 開始

```bash
uv sync                 # 建 .venv 並裝好開發相依
uv run pytest           # 跑全部測試
```

## 四道閘

`ruff check` / `ruff format --check` / `mypy` / `pytest`，全綠才准進 `main`。

```bash
uv run pre-commit run --all-files   # commit 前的快閘
uv run mypy && uv run pytest        # 其餘兩道
```

`main` 由 ruleset `main-gates` 保護：必經 PR、`gates` 必須綠、擋 force push 與刪除。

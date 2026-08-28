# nova

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

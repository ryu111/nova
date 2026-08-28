"""迴圈（loop）：什麼觸發下一次嘗試、何時停止。

一個迴圈必須湊齊七個欄位才算成立（AGENT_ARCHITECTURE.md §3.2）：
trigger、goal、memory、action policy、evidence、feedback、stop rule。
缺 stop rule 的迴圈不是策略，是成本漏洞。
"""

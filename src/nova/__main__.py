"""`python -m nova` 的進入點。

**排程走這一條，不走 console script。** 理由是程序名稱：console script
（`.venv/bin/nova`）是一個 shebang 文字檔，kernel 執行的是**直譯器**，
所以活動監視器顯示 `python3.13`。排程改成用硬連結出來的專用直譯器
（`.venv/bin/nova-inbox`）跑 `-m nova`，kernel 就依那個名字命名。

細節與實測見 `載體/排程.py` 的 `確保啟動器在`。
"""

import sys

from nova.載體.命令列 import 主程式

if __name__ == "__main__":
    sys.exit(主程式())

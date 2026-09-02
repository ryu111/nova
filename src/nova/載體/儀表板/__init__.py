"""派工儀表板：讀取器 → `契約.儀表板` 一份 frozen dataclass。

門面只 re-export 組裝、落點、命令這三支，呼叫端不必知道它們各住哪個檔。
"""

from nova.載體.儀表板.命令 import 儀表板路徑, 執行儀表板
from nova.載體.儀表板.資料 import 組儀表板

__all__ = ["儀表板路徑", "執行儀表板", "組儀表板"]

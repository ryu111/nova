"""`nova 儀表板`：組 → 呈現 → 寫到狀態目錄（或 `--json` 只吐資料）。

**唯讀**：不拿閘鎖、不 `git fetch`、不 fork 任何 LLM CLI。

落點固定在狀態目錄底下的專案鍵，**不寫進工作目錄**——
會被餵回模型的東西執行者不准碰。沒有 `--輸出` 之類的旗標：
落點多一個可以蓋掉的入口，就多一條「這份是哪來的」答不出來的路。
"""

import argparse
import json
import sys
from pathlib import Path

from nova.契約.儀表板 import 儀表板轉字典
from nova.契約.退出碼 import 放行
from nova.載體.儀表板.呈現 import 渲染
from nova.載體.儀表板.資料 import 組儀表板
from nova.載體.專案脈絡 import 專案執行脈絡, 建專案執行脈絡
from nova.載體.帳本 import 專案識別
from nova.載體.狀態 import 狀態根目錄


def 儀表板路徑(專案: Path) -> Path:
    """這份儀表板落在哪。歸屬用專案當鍵、檔案存在專案外面（同 `已處理目錄`）。"""
    return 狀態根目錄() / "專案" / 專案識別(專案) / "儀表板.html"


def _專案根(參數: argparse.Namespace) -> Path:
    """工作目錄只有一個來源：這次執行已經建好的 `專案脈絡.根目錄`。

    自己再 `Path(參數.根目錄)` 一次的話，敲預設的 `.` 或相對路徑時
    儀表板會說自己在 `.`，而同一次執行的收件匣／帳本／已處理用的是 resolve 過的那份——
    **同一份儀表板上兩個「這是哪個專案」的答案，看的人無從分辨哪個是真的。**
    """
    脈絡 = getattr(參數, "專案脈絡", None)
    if not isinstance(脈絡, 專案執行脈絡):
        脈絡 = 建專案執行脈絡(getattr(參數, "根目錄", None))
    return 脈絡.根目錄


def 執行儀表板(參數: argparse.Namespace) -> int:
    """把派工現況生成一頁 HTML；`--json` 只把那份契約印到 stdout。"""
    專案 = _專案根(參數)
    一份 = 組儀表板(專案)
    if getattr(參數, "json", False):
        sys.stdout.write(json.dumps(儀表板轉字典(一份), ensure_ascii=False) + "\n")
        return 放行
    落點 = 儀表板路徑(專案)
    落點.parent.mkdir(parents=True, exist_ok=True)
    落點.write_text(渲染(一份), encoding="utf-8")
    sys.stdout.write(f"寫好了：{落點}\n")
    return 放行

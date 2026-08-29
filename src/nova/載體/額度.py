"""額度查詢與快取：查詢 codex 與 agy 的訂閱限額並寫入狀態快取。

跨程序 schema 欄位名使用 ASCII（CLAUDE.md 例外）。
"""

import contextlib
import json
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, TypedDict

from nova.契約.額度 import 家族額度, 快取轉快照, 視窗, 額度快照
from nova.載體.模型 import 轉接
from nova.載體.模型.執行 import 跑cli
from nova.載體.狀態 import 狀態根目錄
from nova.載體.程序 import 收割整棵

_一天幾分 = 1440
_一小時幾分 = 60
#: codex 的 app-server 要起程序、要連網，實測熱機 4 秒。給 15 秒是留冷啟動的餘裕。
#: **這個上限不是裝飾**：沒有它，app-server 起得來但不回話時 readline 會永遠卡住。
_codex截止秒 = 15.0
#: agy 的 /usage 實測熱機 3.6 秒。10 秒對冷啟動太緊，會把「慢」誤判成「失敗」。
_agy逾時秒 = 30.0
_agy欄位數 = 4
_codex查詢id = 2


class 視窗型(TypedDict):
    """限額視窗型別（ASCII 欄位名）。"""

    label: str
    used_percent: int
    resets_at: int


class 家族型(TypedDict):
    """家族限額型別（ASCII 欄位名）。"""

    family: str
    windows: list[視窗型]


class 快取資料型(TypedDict):
    """額度快取資料型別（ASCII 欄位名）。"""

    ts: int
    families: list[家族型]


_codex初始化與查詢訊息們: tuple[dict[str, Any], ...] = (
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"clientInfo": {"name": "nova", "version": "0.1.0"}},
    },
    {"jsonrpc": "2.0", "method": "initialized"},
    {
        "jsonrpc": "2.0",
        "id": _codex查詢id,
        "method": "account/rateLimits/read",
        "params": {},
    },
)


def 額度快取路徑() -> Path:
    """額度快取檔的路徑。"""
    return 狀態根目錄() / "額度" / "快取.json"


def 分鐘轉標籤(分鐘: int) -> str:
    """把分鐘換算為標籤，如 10080 分鐘 -> 7d，300 分鐘 -> 5h。"""
    if 分鐘 > 0 and 分鐘 % _一天幾分 == 0:
        return f"{分鐘 // _一天幾分}d"
    if 分鐘 > 0 and 分鐘 % _一小時幾分 == 0:
        return f"{分鐘 // _一小時幾分}h"
    return f"{分鐘}m"


def _解析codex單一視窗(視窗: object) -> 視窗型 | None:
    """解析 codex 單一視窗字典（如 primary 或 secondary）。若為 None 或格式不合回 None。"""
    if not isinstance(視窗, dict):
        return None
    try:
        分鐘 = int(視窗["windowDurationMins"])
        已用 = int(視窗["usedPercent"])
        重置 = int(視窗["resetsAt"])
    except (KeyError, ValueError, TypeError):
        return None
    return {
        "label": 分鐘轉標籤(分鐘),
        "used_percent": 已用,
        "resets_at": 重置,
    }


def 解析codex額度(回應: Mapping[str, Any]) -> list[視窗型]:
    """從 codex 的 account/rateLimits/read 回應解析限額視窗。"""
    if not isinstance(回應, Mapping):
        return []
    結果 = 回應.get("result")
    if not isinstance(結果, dict):
        return []
    限額 = 結果.get("rateLimits")
    if not isinstance(限額, dict):
        return []

    視窗清單: list[視窗型] = []
    for 鍵 in ("primary", "secondary"):
        單個視窗 = _解析codex單一視窗(限額.get(鍵))
        if 單個視窗 is not None:
            視窗清單.append(單個視窗)
    return 視窗清單


def _解析agy重置秒(時間字串: str) -> int:
    """解析 agy ISO 時間字串為 unix timestamp 秒數。"""
    重置時間 = datetime.fromisoformat(時間字串)
    if 重置時間.tzinfo is None:
        重置時間 = 重置時間.replace(tzinfo=UTC)
    return int(重置時間.timestamp())


def _解析agy一列(欄位: list[str]) -> 視窗型 | None:
    """解析 agy 輸出的單一列。非 Gemini 或格式不合回 None。"""
    if len(欄位) < _agy欄位數 or 欄位[0].strip() != "Gemini Models":
        return None

    名稱 = 欄位[1].strip()
    if "Weekly" in 名稱:
        標籤 = "7d"
    elif "Five Hour" in 名稱:
        標籤 = "5h"
    else:
        return None

    try:
        剩餘 = int(欄位[2].replace("%", "").strip())
        已用 = 100 - 剩餘
        重置秒 = _解析agy重置秒(欄位[3].strip())
    except (ValueError, TypeError):
        return None

    return {
        "label": 標籤,
        "used_percent": 已用,
        "resets_at": 重置秒,
    }


def 解析agy額度(文字: str) -> list[視窗型]:
    """從 agy -p /usage 的輸出解析限額視窗。"""
    if not 文字 or not isinstance(文字, str):
        return []

    視窗清單: list[視窗型] = []
    for 行 in 文字.splitlines():
        欄位 = 行.strip().split("\t")
        單列 = _解析agy一列(欄位)
        if 單列 is not None:
            視窗清單.append(單列)
    return 視窗清單


def _收行(輸出: IO[str], 佇: queue.Queue[str | None]) -> None:
    """把子程序的每一行丟進佇列。讀完（管線關了）就丟一個 None 當結束記號。"""
    for 行 in 輸出:
        佇.put(行)
    佇.put(None)


def _送握手(程序: subprocess.Popen[str]) -> str | None:
    """把 initialize、initialized、rateLimits/read 三則送出去。有問題回錯誤訊息。"""
    if 程序.stdin is None or 程序.stdout is None:
        return "無法建立 stdin/stdout 管道"
    try:
        for 訊息 in _codex初始化與查詢訊息們:
            程序.stdin.write(json.dumps(訊息) + "\n")
            程序.stdin.flush()
    except Exception as 錯:
        return f"與 codex 通訊失敗：{錯}"
    return None


def _等到那一則(
    佇: queue.Queue[str | None], 截止秒: float
) -> tuple[dict[str, Any] | None, str | None]:
    """在截止時間內等 id=2 那一則。中間夾雜的通知一律略過。"""
    截止 = time.monotonic() + 截止秒
    逾時了 = f"等 codex 回應超過 {截止秒:g} 秒"
    while True:
        剩下 = 截止 - time.monotonic()
        if 剩下 <= 0:
            return None, 逾時了
        try:
            行 = 佇.get(timeout=剩下)
        except queue.Empty:
            return None, 逾時了
        if 行 is None:
            return None, f"未收到 id={_codex查詢id} 之回應"
        with contextlib.suppress(Exception):
            收到 = json.loads(行)
            if isinstance(收到, dict) and 收到.get("id") == _codex查詢id:
                return 收到, None


def _向codex通訊(
    程序: subprocess.Popen[str], 截止秒: float
) -> tuple[dict[str, Any] | None, str | None]:
    """向 codex app-server 送出請求並等 id=2 回應。

    **讀那一邊一定要另外開執行緒**：`readline` 卡住的時候沒有人叫得動它——
    子程序還活著、管線也沒關，它就不會回來。主執行緒只等佇列，時間到就放棄。
    """
    錯誤 = _送握手(程序)
    if 錯誤 is not None or 程序.stdout is None:
        return None, 錯誤 or "無法建立 stdout 管道"

    佇: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_收行, args=(程序.stdout, 佇), daemon=True).start()
    return _等到那一則(佇, 截止秒)


def _終止程序(程序: subprocess.Popen[str]) -> None:
    """收掉 app-server 連同它開出來的整棵樹。

    app-server 自己會再開子程序，只 terminate 它一個會留孤兒——
    2026-08-30 實測撈到一隻 `fake-mute-codex app-server` 活了 24 小時。
    """
    收割整棵(程序)


def 查詢codex額度(*, 截止秒: float = _codex截止秒) -> tuple[list[視窗型], str | None]:
    """向 codex app-server 查詢限額。回傳 (視窗清單, 錯誤訊息)。"""
    try:
        執行檔 = 轉接.找執行檔("codex")
        程序 = subprocess.Popen(  # noqa: S603
            [str(執行檔), "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # stderr 沒有人讀。開成管線的話，app-server 吐滿緩衝區就換它卡住——
            # 補了 stdout 的逾時卻在這裡留一條同樣的路，等於沒補。
            stderr=subprocess.DEVNULL,
            text=True,
            # 自成一組，_終止程序 才殺得到 app-server 底下的後代。
            start_new_session=True,
        )
    except Exception as 錯:
        return [], f"啟動 codex app-server 失敗：{錯}"

    try:
        回應字典, 錯誤 = _向codex通訊(程序, 截止秒)
    finally:
        _終止程序(程序)

    if 錯誤 or 回應字典 is None:
        return [], 錯誤 or "未收到回應"

    視窗清單 = 解析codex額度(回應字典)
    if not 視窗清單:
        return [], "解析 codex 額度為空"
    return 視窗清單, None


def 查詢agy額度() -> tuple[list[視窗型], str | None]:
    """向 agy -p /usage 查詢限額。回傳 (視窗清單, 錯誤訊息)。"""
    try:
        執行檔 = 轉接.找執行檔("agy")
    except Exception as 錯:
        return [], f"找不到 agy 執行檔：{錯}"

    try:
        # 走 跑cli 不走 subprocess.run：逾時要連 agy 開出來的後代一起收掉。
        結果 = 跑cli(執行檔, ["-p", "/usage"], 逾時秒=_agy逾時秒)
    except Exception as 錯:
        return [], f"執行 agy /usage 失敗：{錯}"

    if 結果.結束碼 != 0:
        return [], f"agy 回傳非 0 結束碼 {結果.結束碼}：{結果.標準錯誤.strip()}"

    視窗清單 = 解析agy額度(結果.標準輸出)
    if not 視窗清單:
        return [], "解析 agy 額度為空"
    return 視窗清單, None


def _標籤分鐘(標籤: str) -> int:
    """把 `分鐘轉標籤` 產出的標籤換回分鐘。用來排序，不對外。"""
    單位 = {"d": _一天幾分, "h": _一小時幾分, "m": 1}
    return int(標籤[:-1]) * 單位[標籤[-1]]


def 短窗排前面(視窗清單: list[視窗型]) -> list[視窗型]:
    """照視窗長度由短到長排。

    來源順序不能信：agy 吐的是 Weekly 在前，照抄會顯示成「7d 5h」，讀起來是反的。
    """
    return sorted(視窗清單, key=lambda 視窗: _標籤分鐘(視窗["label"]))


def 該重抓嗎(快取年紀秒: float | None, 最舊秒: float) -> bool:
    """快取有多舊、超過多舊就重抓。`快取年紀秒` 是 None 代表快取不在。

    **邊界往「抓」那邊倒**：多抓一次只花幾秒，少抓一次是拿舊數字騙人。
    `最舊秒` 是 0 就一律重抓——直接叫 `nova 額度` 的人要的是現在的數字。
    """
    if 快取年紀秒 is None:
        return True
    return 快取年紀秒 >= 最舊秒


def _快取年紀(檔: Path, 現在: float) -> float | None:
    """快取檔幾秒前寫的。不在或讀不到都回 None——讀不到就當沒有，不要猜。"""
    try:
        return 現在 - 檔.stat().st_mtime
    except OSError:
        return None


def _寫入快取檔(家族清單: list[家族型], ts: int | None = None) -> None:
    """將查詢到的家族額度資料寫入狀態快取檔。"""
    快取檔 = 額度快取路徑()
    快取檔.parent.mkdir(parents=True, exist_ok=True)
    快取資料: 快取資料型 = {
        "ts": int(datetime.now(UTC).timestamp()) if ts is None else ts,
        "families": 家族清單,
    }
    快取檔.write_text(json.dumps(快取資料, ensure_ascii=False, indent=2), encoding="utf-8")


def _從快取讀(快取檔: Path, 每家: Callable[[家族額度], None] | None) -> 額度快照 | None:
    """嘗試從快取檔讀取額度快照。讀取失敗回傳 None。"""
    with contextlib.suppress(Exception):
        快取資料 = json.loads(快取檔.read_text(encoding="utf-8"))
        快照 = 快取轉快照(快取資料)
        if 每家 is not None:
            for 家 in 快照.家族們:
                with contextlib.suppress(Exception):
                    每家(家)
        return 快照
    return None


def _查一家(
    名稱: str, 家族代碼: str, 查詢函式: Callable[[], tuple[list[視窗型], str | None]]
) -> tuple[家族額度, 家族型 | None]:
    """查詢單一模型家族之額度。"""
    視窗清單, 錯誤 = 查詢函式()
    if 錯誤:
        return 家族額度(家=名稱, 視窗們=(), 失敗原因=錯誤), None
    短窗 = 短窗排前面(視窗清單)
    視窗元組 = tuple(
        視窗(
            標籤=窗["label"],
            用掉百分比=窗["used_percent"],
            重置於=窗["resets_at"],
        )
        for 窗 in 短窗
    )
    return 家族額度(家=名稱, 視窗們=視窗元組, 失敗原因=None), {"family": 家族代碼, "windows": 短窗}


def 查詢額度(
    *,
    最舊秒: float = 0.0,
    每家: Callable[[家族額度], None] | None = None,
) -> 額度快照:
    """查詢 codex 與 agy 額度並寫入快取。

    `最舊秒` 是節流：快取比它新就直接讀回快取。
    `每家` 每拿到一家的結果就立刻呼叫一次。
    """
    快取檔 = 額度快取路徑()
    if not 該重抓嗎(_快取年紀(快取檔, time.time()), 最舊秒):
        快照 = _從快取讀(快取檔, 每家)
        if 快照 is not None:
            return 快照

    現在秒 = int(datetime.now(UTC).timestamp())
    成功家族清單: list[家族型] = []
    所有家族: list[家族額度] = []

    查詢清單: tuple[tuple[str, str, Callable[[], tuple[list[視窗型], str | None]]], ...] = (
        ("codex", "cx", 查詢codex額度),
        ("agy", "ay", 查詢agy額度),
    )

    for 名稱, 家族代碼, 查詢函式 in 查詢清單:
        家, 成功資料 = _查一家(名稱, 家族代碼, 查詢函式)
        if 成功資料 is not None:
            成功家族清單.append(成功資料)
        所有家族.append(家)
        if 每家 is not None:
            with contextlib.suppress(Exception):
                每家(家)

    if 成功家族清單:
        _寫入快取檔(成功家族清單, ts=現在秒)

    return 額度快照(時間=現在秒, 家族們=tuple(所有家族))

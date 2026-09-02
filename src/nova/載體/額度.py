"""額度查詢與快取：查詢 codex 與 agy 的訂閱限額並寫入狀態快取。

跨程序 schema 欄位名使用 ASCII（CLAUDE.md 例外）。
"""

import contextlib
import fcntl
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, NotRequired, TypedDict

from nova.契約.額度 import 家族額度, 快取轉快照, 視窗, 額度快照
from nova.載體.模型 import 轉接
from nova.載體.模型.執行 import 跑cli
from nova.載體.狀態 import 狀態根目錄
from nova.載體.程序 import 具名啟動, 收割整棵

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
    #: **這一家自己的**時戳（epoch 秒）。選填：舊快取沒有這一格，讀的時候退回全域 `ts`。
    #: 只有一個全域 `ts` 的話，只寫得到一家的那條路（`--從狀態列` 只寫 claude）
    #: 會把其他家也一起刷成新鮮的——那是安靜地拿舊數字當新數字用。
    ts: NotRequired[int]


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
        啟動列, 角色標記 = 具名啟動(執行檔, ["app-server"])
        程序 = subprocess.Popen(  # noqa: S603
            啟動列,
            env={**os.environ, "APP_ROLE": 角色標記},
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


def _讀得回來的快取() -> Mapping[str, Any]:
    """快取檔現在的樣子；沒檔、壞檔都是空的一份。

    合併寫回之前一定要先讀：讀不到就當「本來就沒有別家」，
    那是這條路唯一能安全假設的事。
    """
    舊快取: Mapping[str, Any] = {}
    with contextlib.suppress(Exception):
        舊快取 = json.loads(額度快取路徑().read_text(encoding="utf-8"))
    return 舊快取


def _快取裡的那家(快取: Mapping[str, Any], 家族代碼: str) -> Mapping[str, Any] | None:
    """快取裡代碼是這個的那一家；沒有就 None。"""
    return next(
        (家 for 家 in 快取.get("families", []) if 家.get("family") == 家族代碼),
        None,
    )


def _那家的時戳(快取: Mapping[str, Any], 家族代碼: str) -> int | None:
    """這一家自己的數字是幾時寫的；沒這家、時戳讀不成數字都回 None（＝沒數字）。

    舊快取沒有每家自己的 `ts`，退回全域的——讀得回來比讀得漂亮重要。
    """
    家 = _快取裡的那家(快取, 家族代碼)
    if 家 is None:
        return None
    with contextlib.suppress(TypeError, ValueError):
        return int(家.get("ts", 快取.get("ts", 0)))
    return None


def _那幾家的年紀(家族代碼們: tuple[str, ...], 現在: float) -> float | None:
    """點名的那幾家裡**最舊的那一家**幾秒前寫的；有一家沒數字就回 None。

    不看檔案的 mtime，也不看全域 `ts`：快取現在有兩個寫入端，狀態列腳本每次
    工具呼叫都在背景把 `cl` 併進同一個檔，檔案的 mtime 與（狀態列建檔時的）
    全域 `ts` 因此永遠是新的，而 cx／ay 的數字可以是三小時前或根本沒有過。
    拿那兩個當節流依據，`nova 額度 --最舊 900` 會再也不去問人，只回舊數字。
    """
    快取 = _讀得回來的快取()
    時戳們: list[int] = []
    for 代碼 in 家族代碼們:
        時戳 = _那家的時戳(快取, 代碼)
        if 時戳 is None:
            return None
        時戳們.append(時戳)
    return max(現在 - 時戳 for 時戳 in 時戳們)


def _寫入快取檔(家族清單: list[家族型], ts: int | None = None) -> None:
    """把整份家族清單寫進狀態快取檔。**底層，只准經過 `_合併寫入` 叫它。**

    它做的就是「整份換掉」——直接叫它的人會把別的寫入端剛寫的那一家抹掉，
    而抹掉之後外表毫無異狀（見 `_合併寫入`）。保留成獨立一支是因為
    「怎麼寫檔」和「換哪幾家」是兩件事。
    """
    快取檔 = 額度快取路徑()
    快取檔.parent.mkdir(parents=True, exist_ok=True)
    快取資料: 快取資料型 = {
        "ts": int(datetime.now(UTC).timestamp()) if ts is None else ts,
        "families": 家族清單,
    }
    暫存檔: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=快取檔.parent,
            prefix=f".{快取檔.name}.",
            suffix=".tmp",
            delete=False,
        ) as 暫存:
            暫存檔 = Path(暫存.name)
            暫存.write(json.dumps(快取資料, ensure_ascii=False, indent=2))
        暫存檔.replace(快取檔)
        暫存檔 = None
    finally:
        if 暫存檔 is not None:
            暫存檔.unlink(missing_ok=True)


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


def 只讀快取的額度() -> 額度快照 | None:
    """快取裡現在有什麼就是什麼，**一個子程序都不起**；讀不到（沒檔、壞檔）回 None。

    存在的理由是「派工前那道門不准付查詢的代價」：`查詢額度` 會 fork
    codex 的 app-server（15 秒截止）與 agy（30 秒），人敲一次 `nova 派工`
    要等半分鐘的話，那道門很快就會被拿掉。所以快取新就用、舊就當查不到。

    **新不新由呼叫端自己判**（看每一家自己的 `時間`）：這裡不做時間判斷，
    因為「多舊算舊」是那道門的政策，不是讀檔的事。
    """
    return _從快取讀(額度快取路徑(), None)


@contextlib.contextmanager
def _鎖住快取() -> Iterator[None]:
    """鎖住同一份額度快取的合併更新。"""
    快取檔 = 額度快取路徑()
    快取檔.parent.mkdir(parents=True, exist_ok=True)
    with (快取檔.parent / "快取.鎖").open("a+") as 鎖:
        fcntl.flock(鎖.fileno(), fcntl.LOCK_EX)
        yield


def _合併家族清單(舊快取: Mapping[str, Any], 要換的: list[家族型], 現在秒: int) -> list[家族型]:
    """用新資料取代指定家族，保留快取裡其他家族。"""
    換掉的代碼 = {家["family"] for 家 in 要換的}
    保留的家族: list[家族型] = [
        家 for 家 in 舊快取.get("families", []) if 家.get("family") not in 換掉的代碼
    ]
    更新後的家族: list[家族型] = [{**家, "ts": 現在秒} for 家 in 要換的]
    return [*保留的家族, *更新後的家族]


def _合併寫入(
    要換的: list[家族型], *, 現在秒: int, 更新全域ts: bool, 節流秒: int | None = None
) -> bool:
    """**兩個寫入端唯一的寫入口**：只換點名的那幾家，沒點名的原樣留著。

    快取有兩個寫入端（fork 去問 codex／agy 的 `查詢額度`、狀態列餵進來的 `記下狀態列額度`），
    誰整份覆寫都會把另一邊剛寫的抹掉；而抹掉之後外表毫無異狀，只是那一家從此「查不到」。
    所以合併邏輯只准有這一份。

    各家蓋各家的 `ts`；全域 `ts` 只在**去問過人的那條路**更新（`更新全域ts`）——
    只寫一家卻刷新全域，會讓別家的舊數字看起來也是剛查的。
    """
    with _鎖住快取():
        舊快取 = _讀得回來的快取()
        if 節流秒 is not None:
            舊時戳 = _那家的時戳(舊快取, 要換的[0]["family"])
            if 舊時戳 is not None and 現在秒 - 舊時戳 < 節流秒:
                return False
        _寫入快取檔(
            _合併家族清單(舊快取, 要換的, 現在秒),
            ts=現在秒 if 更新全域ts else int(舊快取.get("ts", 現在秒)),
        )
    return True


#: claude 的 CLI **沒有** usage／quota 子命令（2.1.258 實測 `--help` ＋官方 cli-reference），
#: 唯一拿得到數字的地方是狀態列 JSON 的 `rate_limits`。
_狀態列視窗表: tuple[tuple[str, str], ...] = (("five_hour", "5h"), ("seven_day", "7d"))

#: 狀態列腳本**每次工具呼叫**都會跑。比這麼新就不重寫，不然一分鐘寫幾十次檔。
狀態列節流秒 = 60


def _狀態列一個窗(標籤: str, 窗: object) -> 視窗型 | None:
    """狀態列 `rate_limits` 底下的一格 → 一個視窗；讀不成形回 None。

    讀不成形（不是 mapping、沒有 `used_percentage`、百分比不是數字）一律當那一格
    不存在：狀態列 JSON 是別人家的格式，多一格少一格都不該讓寫快取這條路炸掉。
    """
    if not isinstance(窗, Mapping) or "used_percentage" not in 窗:
        return None
    with contextlib.suppress(TypeError, ValueError):
        return {
            "label": 標籤,
            "used_percent": int(float(窗["used_percentage"]) + 0.5),
            "resets_at": int(窗.get("resets_at", 0)),
        }
    return None


def 讀出狀態列額度(原始: Mapping[str, Any]) -> 家族型 | None:
    """claude 狀態列 JSON → `cl` 那一家。**純解析，不碰檔案**（所以測得動）。

    `rate_limits` 整格不在（免費方案、視窗過期、第一次回應之前）就回 None：
    那是「查不到」，不是「用了 0%」——把它寫成 0% 會讓派工前那道門看到一個
    很寬裕的假數字，然後照派、照撞。
    """
    限額 = 原始.get("rate_limits")
    if not isinstance(限額, Mapping):
        return None
    視窗清單: list[視窗型] = []
    for 鍵, 標籤 in _狀態列視窗表:
        if (窗 := _狀態列一個窗(標籤, 限額.get(鍵))) is not None:
            視窗清單.append(窗)
    if not 視窗清單:
        return None
    return {"family": "cl", "windows": 短窗排前面(視窗清單)}


def 記下狀態列額度(原始: Mapping[str, Any], *, 現在: int | None = None) -> bool:
    """把狀態列讀到的 claude 額度**併**進快取；寫了回 True。

    `~/.claude/statusline.sh` 每次工具呼叫都在背景叫它，所以 `cl` 的時戳比
    `狀態列節流秒` 新就不重寫——差幾十秒的百分比不值得每秒寫一次檔。
    """
    家 = 讀出狀態列額度(原始)
    if 家 is None:
        return False
    此刻 = int(datetime.now(UTC).timestamp()) if 現在 is None else 現在
    return _合併寫入([家], 現在秒=此刻, 更新全域ts=False, 節流秒=狀態列節流秒)


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
    if not 該重抓嗎(_那幾家的年紀(("cx", "ay"), time.time()), 最舊秒):
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
        _合併寫入(成功家族清單, 現在秒=現在秒, 更新全域ts=True)

    return 額度快照(時間=現在秒, 家族們=tuple(所有家族))

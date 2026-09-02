"""claude 的額度只有一條路進快取：`nova 額度 --從狀態列` 從 stdin 吃狀態列 JSON。

claude 沒有 usage／quota 子命令（2.1.258 的 `--help` 與官方 cli-reference 都沒有），
唯一拿得到數字的地方是狀態列 JSON 的 `rate_limits.five_hour` / `seven_day`。
於是快取變成**兩個寫入端**：`nova 額度`（fork 去問 codex／agy）與
`nova 額度 --從狀態列`（狀態列腳本在背景餵進來的 claude）。

兩個寫入端寫同一個檔，所以這支釘的是它們之間唯一會互相踩到的那件事：

1. **誰都不准把別家抹掉。** 今天 `查詢額度` 那條路是
   `_寫入快取檔(成功家族清單, ts=現在秒)`——整份 `families` 換成 cx／ay 兩家，
   狀態列寫進去的 `cl` 下一次 `nova 額度` 就沒了。反過來只寫 `cl` 卻刷新全域 `ts`，
   cx／ay 會**看起來也是新的**，於是「這個數字多舊」整個說謊。
2. **每家的新鮮度是自己的。** 派工前那道門要問「claude 這家的數字多舊」，
   問的必須是 `cl` 自己的時戳，不是全域那一個。舊快取沒有分家時戳，
   所以讀端要退回全域 `ts`（`快取轉快照`）。

住整合層、走真的 subprocess：`--從狀態列` 那條路是被 `~/.claude/statusline.sh`
在背景叫的，「回 0、什麼都不印」是它的合約，而合約只有從子程序外面看得到。
反向那一半（`查詢額度` 保不保得住 `cl`）不必 fork 真的 codex，用 monkeypatch
把兩家的查詢換掉，測的是寫檔那一格，不是網路。
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from nova.契約.額度 import 快取轉快照

nova執行檔 = Path(sys.executable).parent / "nova"

#: 先手寫進去的快取時戳。挑一個久遠又明確的秒數，跟「現在」差幾年，
#: 這樣 `全域 ts 有沒有被動過` 不必靠容差就看得出來。
舊全域時戳 = 1_700_000_000

#: 先躺在快取裡的另外兩家。狀態列那條路寫完之後，這兩格要**一個位元都沒變**。
原本的cx: dict[str, object] = {
    "family": "cx",
    "windows": [{"label": "5h", "used_percent": 12, "resets_at": 1_700_003_600}],
}
原本的ay: dict[str, object] = {
    "family": "ay",
    "windows": [{"label": "7d", "used_percent": 34, "resets_at": 1_700_600_000}],
}


def _快取檔(狀態根: Path) -> Path:
    return 狀態根 / "nova" / "額度" / "快取.json"


def _寫舊快取(狀態根: Path) -> Path:
    """手寫一份「只有 cx／ay、只有全域 ts」的舊格式快取。"""
    檔 = _快取檔(狀態根)
    檔.parent.mkdir(parents=True, exist_ok=True)
    檔.write_text(
        json.dumps({"ts": 舊全域時戳, "families": [原本的cx, 原本的ay]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return 檔


def _狀態列原始(現在: int, 五小時用掉: float = 41, 七天用掉: float = 7) -> str:
    """狀態列 JSON 的形狀照官方文件：`resets_at` 是 epoch 秒，百分比是數字。

    百分比收 `float`：官方那一格**不保證是整數**（`used_percentage` 是算出來的），
    而快取裡存的是 int，所以四捨五入這一步得餵得進小數才測得到。
    """
    return json.dumps(
        {
            "session_id": "測試用",
            "model": {"display_name": "Sonnet 4.6"},
            "rate_limits": {
                "five_hour": {"used_percentage": 五小時用掉, "resets_at": 現在 + 3600},
                "seven_day": {"used_percentage": 七天用掉, "resets_at": 現在 + 86400},
            },
        },
        ensure_ascii=False,
    )


def _餵狀態列(狀態根: Path, 原始: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), "額度", "--從狀態列"],
        input=原始,
        env={**os.environ, "XDG_STATE_HOME": str(狀態根)},
        capture_output=True,
        text=True,
        check=False,
    )


def _家(快取: dict[str, object], 代碼: str) -> dict[str, object]:
    家們 = [一家 for 一家 in 快取["families"] if 一家["family"] == 代碼]  # type: ignore[attr-defined]
    assert len(家們) == 1, f"快取裡的 {代碼} 應恰好一格，實際 {len(家們)} 格：{快取}"
    return cast("dict[str, object]", 家們[0])


_並行注入內容 = """
import os
import time
from pathlib import Path

角色 = os.environ.get("NOVA_QUOTA_TEST_ROLE")
if 角色:
    報到 = Path(os.environ["NOVA_QUOTA_TEST_READY"])
    放行 = Path(os.environ["NOVA_QUOTA_TEST_RELEASE"])

    def 等放行():
        報到.touch()
        截止 = time.monotonic() + 30
        while not 放行.exists():
            if time.monotonic() >= 截止:
                raise RuntimeError("測試同步點等不到放行")
            time.sleep(0.005)

    from nova.載體 import 額度 as 額度載體

    if 角色 == "statusline":
        原本寫入 = 額度載體.記下狀態列額度

        def 同步寫入(*args, **kwargs):
            等放行()
            return 原本寫入(*args, **kwargs)

        額度載體.記下狀態列額度 = 同步寫入
    elif 角色 == "query":
        現在秒 = int(os.environ["NOVA_QUOTA_TEST_NOW"])

        def 假codex(**kwargs):
            return [{"label": "5h", "used_percent": 88, "resets_at": 現在秒 + 60}], None

        def 假agy():
            return [{"label": "7d", "used_percent": 55, "resets_at": 現在秒 + 120}], None

        額度載體.查詢codex額度 = 假codex
        額度載體.查詢agy額度 = 假agy
        原本查詢 = 額度載體.查詢額度

        def 同步查詢(*args, **kwargs):
            等放行()
            return 原本查詢(*args, **kwargs)

        額度載體.查詢額度 = 同步查詢
        import nova

        nova.查詢額度 = 同步查詢
"""


def _並行子程序環境(
    共用環境: dict[str, str],
    角色: str,
    報到: Path,
) -> dict[str, str]:
    return {
        **共用環境,
        "NOVA_QUOTA_TEST_ROLE": 角色,
        "NOVA_QUOTA_TEST_READY": str(報到),
    }


def _等到並行報到(報到: Path, 程序: subprocess.Popen[str]) -> None:
    """等一個寫入端到達同步點；程序提前死掉時立刻讓測試說出原因。"""
    截止 = time.monotonic() + 30
    while not 報到.exists():
        if 程序.poll() is not None:
            pytest.fail(f"{報到.name} 的子程序提前結束：{程序.returncode}")
        if time.monotonic() >= 截止:
            pytest.fail(f"等不到 {報到.name}，同步點沒有建立")
        time.sleep(0.005)


def _反覆讀快取(檔: Path, 停止: threading.Event, 已讀到: threading.Event, 壞檔: list[str]) -> None:
    """在兩個寫入端工作時輪讀快取，抓住直接覆寫的截斷窗口。"""
    while not 停止.is_set():
        try:
            json.loads(檔.read_text(encoding="utf-8"))
        except FileNotFoundError:
            壞檔.append("快取檔在寫入期間消失")
            return
        except (UnicodeDecodeError, json.JSONDecodeError) as 錯:
            壞檔.append(repr(錯))
            return
        已讀到.set()
        time.sleep(0.001)


def _讀子程序結果(程序: subprocess.Popen[str]) -> tuple[int | None, str, str]:
    assert 程序.stdout is not None
    assert 程序.stderr is not None
    return 程序.returncode, 程序.stdout.read(), 程序.stderr.read()


def _清掉並行子程序(程序們: tuple[subprocess.Popen[str], ...]) -> None:
    for 程序 in 程序們:
        if 程序.poll() is None:
            程序.kill()
            程序.wait(timeout=5)


def _並行寫兩家(
    檔: Path, 狀態根: Path, 注入目錄: Path, 原始: str, 現在: int
) -> tuple[tuple[int | None, str, str], tuple[int | None, str, str], list[str]]:
    """把狀態列與一般查詢在同一個快取上同時放行，回傳兩邊輸出與讀者看到的壞檔。"""
    釋放 = 檔.parent.parent.parent / "釋放"
    狀態列報到 = 釋放.parent / "狀態列已報到"
    查詢報到 = 釋放.parent / "查詢已報到"
    原本Python路徑 = os.environ.get("PYTHONPATH", "")
    Python路徑 = os.pathsep.join(項 for 項 in (str(注入目錄), 原本Python路徑) if 項)
    共用環境 = {
        **os.environ,
        "XDG_STATE_HOME": str(狀態根),
        "PYTHONPATH": Python路徑,
        "NOVA_QUOTA_TEST_RELEASE": str(釋放),
        "NOVA_QUOTA_TEST_NOW": str(現在),
    }

    def 環境(角色: str, 報到: Path) -> dict[str, str]:
        return _並行子程序環境(共用環境, 角色, 報到)

    停止 = threading.Event()
    已讀到 = threading.Event()
    壞檔: list[str] = []
    讀者 = threading.Thread(target=_反覆讀快取, args=(檔, 停止, 已讀到, 壞檔), daemon=True)
    讀者.start()
    assert 已讀到.wait(timeout=5), "讀者連初始快取都讀不到，測試前提不成立"

    狀態列程序 = subprocess.Popen(  # noqa: S603
        [str(nova執行檔), "額度", "--從狀態列"],
        env=環境("statusline", 狀態列報到),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    查詢程序 = subprocess.Popen(  # noqa: S603
        [str(nova執行檔), "額度", "--最舊", "0"],
        env=環境("query", 查詢報到),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        assert 狀態列程序.stdin is not None
        狀態列程序.stdin.write(原始)
        狀態列程序.stdin.close()
        _等到並行報到(狀態列報到, 狀態列程序)
        _等到並行報到(查詢報到, 查詢程序)
        釋放.touch()
        狀態列程序.wait(timeout=30)
        查詢程序.wait(timeout=30)
        return _讀子程序結果(狀態列程序), _讀子程序結果(查詢程序), 壞檔
    finally:
        #: 前置斷言失敗時也放行，避免測試留下兩個等不到同步點的子程序。
        釋放.touch()
        _清掉並行子程序((狀態列程序, 查詢程序))
        停止.set()
        讀者.join(timeout=5)


def test_兩個寫入端都保留別家_cl帶自己的ts_全域ts不動(tmp_path: Path) -> None:
    """兩個寫入端同時動手時，必須保留三家且讀者永遠只看得到完整 JSON。

    既有的串行測試只能證明「先寫 cl，再寫 cx／ay」的順序；無鎖的
    讀取→合併→覆寫在那個順序下也會通過。這裡讓兩個真正的 `nova` 子程序
    在各自的公開寫入入口前報到，再由父程序同時放行，釘住跨程序競態：
    兩邊都必須以同一份最新快取為基礎合併，不能讓後寫者抹掉另一家。

    快取刻意放大，是為了把直接覆寫的截斷窗口拉長；讀者執行緒在兩個寫入者
    工作期間反覆解析同一個檔案，原子落盤才可能讓它始終讀到完整 JSON。
    """
    狀態根 = tmp_path / "狀態"
    檔 = _寫舊快取(狀態根)
    現在 = int(time.time())
    填充家 = {
        "family": "other",
        "windows": [{"label": "1m", "used_percent": 0, "resets_at": 舊全域時戳}] * 50_000,
    }
    檔.write_text(
        json.dumps(
            {"ts": 舊全域時戳, "families": [原本的cx, 原本的ay, 填充家]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    #: `nova` 是 Python console script；sitecustomize 只在子程序啟動時注入
    #: 同步點與假的兩家查詢，父程序仍然走真的 CLI 入口，不在 pytest 行程內
    #: 直接呼叫私有合併函式。
    注入目錄 = tmp_path / "注入"
    注入目錄.mkdir()
    (注入目錄 / "sitecustomize.py").write_text(_並行注入內容, encoding="utf-8")
    狀態列結果, 查詢結果, 讀到壞檔 = _並行寫兩家(檔, 狀態根, 注入目錄, _狀態列原始(現在), 現在)

    assert 狀態列結果 == (0, "", "")
    assert 查詢結果[0] == 0, 查詢結果[2]
    assert 查詢結果[1] == ""
    assert not 讀到壞檔, f"寫入期間讀到了不完整快取：{讀到壞檔[0]}"

    寫完的 = json.loads(檔.read_text(encoding="utf-8"))
    assert {一家["family"] for 一家 in 寫完的["families"]} == {"cx", "ay", "cl", "other"}
    assert _家(寫完的, "cx")["windows"] == [
        {"label": "5h", "used_percent": 88, "resets_at": 現在 + 60}
    ]
    assert _家(寫完的, "ay")["windows"] == [
        {"label": "7d", "used_percent": 55, "resets_at": 現在 + 120}
    ]
    claude家 = _家(寫完的, "cl")
    assert claude家["windows"] == [
        {"label": "5h", "used_percent": 41, "resets_at": 現在 + 3600},
        {"label": "7d", "used_percent": 7, "resets_at": 現在 + 86400},
    ]
    assert len(cast("list[object]", _家(寫完的, "other")["windows"])) == 50_000

    #: 兩個寫入端的時戳政策仍然要成立：狀態列只蓋 cl，查詢才更新全域 ts。
    assert 寫完的["ts"] != 舊全域時戳
    assert abs(int(claude家["ts"]) - 現在) <= 5  # type: ignore[call-overload]

    快照 = 快取轉快照(寫完的)
    每家 = {一家.家: 一家 for 一家 in 快照.家族們}
    assert 每家["claude"].時間 == int(claude家["ts"])  # type: ignore[call-overload]
    assert 每家["codex"].時間 == int(_家(寫完的, "cx")["ts"])  # type: ignore[call-overload]
    assert 每家["agy"].時間 == int(_家(寫完的, "ay")["ts"])  # type: ignore[call-overload]


def test_寫不進快取也一律回0且一個字都不印(tmp_path: Path) -> None:
    """快取**寫不進去**的時候，`--從狀態列` 還是回 0、還是什麼都不印。

    前兩支測的是「沒數字可寫」；這一支測的是「有數字、寫不下去」。
    這條路是 `~/.claude/statusline.sh` 在背景叫的，它的合約只有兩條——
    **不准印、不准回非 0**——而那兩條在寫檔失敗時一樣算數：

    * 印出來的東西會被狀態列腳本吞進主 agent 的狀態列那一行，
      一個 traceback 就把狀態列變成一坨堆疊；
    * 回非 0 讓宿主那一行（`… | nova 額度 --從狀態列 &`）在每次工具呼叫
      留下一個失敗的背景程序。

    而快取檔寫不進去一點都不稀奇：狀態目錄被別的使用者建過、上一次寫到一半
    留了個同名目錄、狀態碟唯讀。**這種時候正確的行為是「這一輪沒得寫」**，
    跟沒有 `rate_limits` 是同一種結果：那一家過一會兒就自然過期成「查不到」，
    派工前那道門會放行並說出口，沒有人被騙。

    兩種擋法各釘一個丟例外的位置：路徑被目錄佔住是 `write_text` 那一步炸，
    上層目錄是普通檔案則是 `mkdir` 那一步就炸。不用改檔案權限，
    以 root 跑測試的機器上 `chmod` 擋不住任何東西。
    """
    現在 = int(time.time())

    # ── 一、快取檔的位置被一個目錄佔住：寫的時候炸 ────────────────────
    佔住的根 = tmp_path / "佔住"
    被佔的 = _快取檔(佔住的根)
    被佔的.mkdir(parents=True)
    (被佔的 / "裡面本來就有東西").write_text("別動我", encoding="utf-8")

    結果 = _餵狀態列(佔住的根, _狀態列原始(現在))
    assert (結果.returncode, 結果.stdout, 結果.stderr) == (0, "", ""), (
        f"寫不進快取就吵了一句／回了非 0，弄髒的是主 agent 的狀態列：{結果.stderr[:400]}"
    )
    #: 順帶釘住：寫不進去就算了，不准「清出位置再寫」——那會刪掉不是自己的東西。
    assert (被佔的 / "裡面本來就有東西").read_text(encoding="utf-8") == "別動我"

    # ── 二、上層目錄是一個普通檔案：連 mkdir 都做不成 ─────────────────
    擋路的根 = tmp_path / "擋路"
    額度目錄 = _快取檔(擋路的根).parent
    額度目錄.parent.mkdir(parents=True)
    額度目錄.write_text("我是檔案不是目錄", encoding="utf-8")

    再來 = _餵狀態列(擋路的根, _狀態列原始(現在))
    assert (再來.returncode, 再來.stdout, 再來.stderr) == (0, "", ""), (
        f"建不出快取目錄就吵了一句／回了非 0：{再來.stderr[:400]}"
    )
    assert 額度目錄.read_text(encoding="utf-8") == "我是檔案不是目錄"


def _寫自帶時戳的快取(狀態根: Path, 家們: list[dict[str, object]], 全域ts: int) -> Path:
    """手寫一份**每家自帶 `ts`** 的快取。

    跟 `_寫舊快取` 分開，是因為那一份被別的測試拿去做「一個位元都沒變」的比對，
    動它會把那些斷言弄糊。
    """
    檔 = _快取檔(狀態根)
    檔.parent.mkdir(parents=True, exist_ok=True)
    檔.write_text(
        json.dumps({"ts": 全域ts, "families": 家們}, ensure_ascii=False), encoding="utf-8"
    )
    return 檔


def _換成假的兩家(
    monkeypatch: pytest.MonkeyPatch, 狀態根: Path, 現在: int
) -> tuple[list[str], ModuleType]:
    """把 fork 出去問 codex／agy 的那兩支換成記帳的假貨，回（問過誰的名單, 載體模組）。

    測的是「該不該去問」，不是「問得到什麼」，所以一個子程序都不必真的起。
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(狀態根))
    from nova.載體 import 額度 as 額度載體

    問過的: list[str] = []

    def 假codex(**_: object) -> tuple[list[dict[str, object]], None]:
        問過的.append("codex")
        return [{"label": "5h", "used_percent": 88, "resets_at": 現在 + 60}], None

    def 假agy() -> tuple[list[dict[str, object]], None]:
        問過的.append("agy")
        return [{"label": "7d", "used_percent": 55, "resets_at": 現在 + 120}], None

    monkeypatch.setattr(額度載體, "查詢codex額度", 假codex)
    monkeypatch.setattr(額度載體, "查詢agy額度", 假agy)
    return 問過的, 額度載體


def test_狀態列摸新了檔案也不准讓cx_ay的舊數字冒充新鮮(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`查詢額度` 的節流要問**那幾家自己的 `ts`**，不准拿快取檔的 mtime 頂替。

    這是「快取多了第二個寫入端」帶進來的洞，而且它只在這張票之後才存在：
    以前快取檔只有 `查詢額度` 一個人寫，檔案的 mtime 就等於 cx／ay 被問到的時間，
    拿 mtime 當節流依據沒有錯。現在 `~/.claude/statusline.sh` **每次工具呼叫**
    都在背景把 claude 的數字併進同一個檔，於是那個檔的 mtime 永遠不超過一分鐘——
    而 cx／ay 的數字可以是三小時前、昨天、或**根本沒有過**。

    後果不是慢，是說謊：`nova 額度 --最舊 900` 從此再也不會去問 codex／agy，
    永遠回同一組舊數字，而且回得理直氣壯（快照裡的百分比看起來就是個正常數字）。
    這正是這張票在契約層做掉的那件事——「每家的新鮮度是自己的」——只是同一個謊
    還留在**要不要重抓**這個決定上。

    三格把修法夾住，免得矯枉過正：

    1. cx／ay 三小時前 ＋ 狀態列一秒前剛寫過 → **要重問**（今天在這裡紅）。
    2. 快取裡只有 `cl`（狀態列建的，全域 `ts` 就是現在）→ cx／ay 從來沒有過數字，
       一樣**要重問**。這一格順便釘死「把 mtime 換成全域 `ts`」那種假修法：
       全域 `ts` 在這裡是新的，照樣騙得過。
    3. 剛問完 900 秒內再叫一次 → **不准重問**。節流本身是對的，別把它拆了。

    走行程內、假掉兩支查詢函式：測的是寫檔與判新鮮那兩格，不是網路。
    """
    現在 = int(time.time())
    三小時前 = 現在 - 3 * 60 * 60

    # ── 一、cx／ay 的數字三小時前，狀態列剛把檔案摸新 ──────────────────
    摸新根 = tmp_path / "摸新"
    檔 = _寫自帶時戳的快取(
        摸新根,
        [{**原本的cx, "ts": 三小時前}, {**原本的ay, "ts": 三小時前}],
        全域ts=三小時前,
    )
    結果 = _餵狀態列(摸新根, _狀態列原始(現在))
    assert (結果.returncode, 結果.stdout) == (0, ""), f"前提就沒成立：{結果.stderr[:400]}"
    assert abs(檔.stat().st_mtime - time.time()) < 60, "前提：狀態列那條路剛剛摸過這個檔"

    問過的, 額度載體 = _換成假的兩家(monkeypatch, 摸新根, 現在)
    快照 = 額度載體.查詢額度(最舊秒=900.0)

    assert 問過的 == ["codex", "agy"], (
        "cx／ay 的數字是三小時前的，卻因為狀態列一秒前寫過同一個檔就不去問了；"
        f"節流看的是檔案 mtime，不是那幾家自己的 ts。問過的：{問過的}"
    )
    家族表 = {家.家: 家 for 家 in 快照.家族們}
    assert 家族表["codex"].視窗們[0].用掉百分比 == 88, f"回的是快取裡的舊數字：{快照}"
    再讀 = json.loads(檔.read_text(encoding="utf-8"))
    assert _家(再讀, "cl")["windows"], "重問一輪不准順手把狀態列寫的 claude 弄丟"

    # ── 二、快取裡只有 cl：cx／ay 從來沒有過數字 ──────────────────────
    只有cl根 = tmp_path / "只有cl"
    assert _餵狀態列(只有cl根, _狀態列原始(現在)).returncode == 0
    剛建的 = json.loads(_快取檔(只有cl根).read_text(encoding="utf-8"))
    assert [一家["family"] for 一家 in 剛建的["families"]] == ["cl"]
    assert abs(int(剛建的["ts"]) - 現在) <= 5, (
        "前提：狀態列建出來的快取，全域 ts 就是現在——所以拿全域 ts 判新鮮一樣會被騙"
    )

    問過的, 額度載體 = _換成假的兩家(monkeypatch, 只有cl根, 現在)
    額度載體.查詢額度(最舊秒=900.0)

    assert 問過的 == ["codex", "agy"], (
        f"快取裡根本沒有 cx／ay 的數字，卻當成「還很新」直接跳過查詢：{問過的}"
    )

    # ── 三、剛問完就再問：節流還是要管用 ──────────────────────────────
    問過的.clear()
    額度載體.查詢額度(最舊秒=900.0)

    assert 問過的 == [], f"cx／ay 幾秒前才問過，900 秒的節流不該讓它們再被問一次：{問過的}"


def _檔案指紋(檔: Path) -> tuple[bytes, int]:
    """內容加 mtime（奈秒）。

    **內容一樣也不准重寫**：寫了就是多一次磁碟寫入，而狀態列腳本一分鐘會叫幾十次。
    """
    return 檔.read_bytes(), 檔.stat().st_mtime_ns


def test_六十秒內再餵不重寫_沒rate_limits不寫_百分比四捨五入(tmp_path: Path) -> None:
    """`--從狀態列` 那條路的四件事：節流、沒數字不寫、四捨五入、壞 JSON 不出聲。

    它是被 `~/.claude/statusline.sh` **每次工具呼叫**在背景叫的，所以這四件事
    都不是細節：

    * 不節流 ＝ 一分鐘寫幾十次快取檔。
    * `rate_limits` 不在（免費方案、視窗過期、第一次回應之前）卻寫下去 ＝
      把「查不到」寫成「用了 0%」，派工前那道門會看到一個很寬裕的假數字然後照撞。
    * 百分比是算出來的小數，直接 `int()` 截斷會讓 94.6% 變 94%。
    * 狀態列 JSON 是別人家的格式，讀不動就算了——在那裡吵一句、或回一個非 0，
      弄髒的是主 agent 的狀態列。

    全程走真的 subprocess：`回 0、什麼都不印` 這個合約只有從子程序外面看得到。
    """
    現在 = int(time.time())

    # ── 一、六十秒內再餵一次：不重寫 ──────────────────────────────────
    節流根 = tmp_path / "節流"
    第一次 = _餵狀態列(節流根, _狀態列原始(現在))
    assert (第一次.returncode, 第一次.stdout, 第一次.stderr) == (0, "", "")
    檔 = _快取檔(節流根)
    第一次寫完 = _檔案指紋(檔)

    #: 第二次故意換一個**不一樣的**百分比：節流沒作用的話，檔案內容一定跟著變，
    #: 不必靠 mtime 的解析度去分辨「有沒有重寫」。
    第二次 = _餵狀態列(節流根, _狀態列原始(現在, 五小時用掉=88))
    assert (第二次.returncode, 第二次.stdout, 第二次.stderr) == (0, "", "")
    assert _檔案指紋(檔) == 第一次寫完, (
        "六十秒內又寫了一次；狀態列一分鐘叫幾十次，這是幾十次磁碟寫入"
    )

    # ── 二、沒有 rate_limits：檔不建、既有檔一個位元都不動 ────────────
    沒數字的幾種 = (
        json.dumps({"session_id": "測試用", "rate_limits": {}}, ensure_ascii=False),
        json.dumps({"session_id": "測試用", "model": {"display_name": "Sonnet 4.6"}}),
        "{不是 JSON",
    )
    for 第幾種, 原始 in enumerate(沒數字的幾種):
        乾淨根 = tmp_path / f"乾淨-{第幾種}"
        結果 = _餵狀態列(乾淨根, 原始)
        assert (結果.returncode, 結果.stdout, 結果.stderr) == (0, "", ""), (
            f"讀不出數字不是錯，它在狀態列腳本的背景裡：{原始!r} → {結果.stderr[:300]}"
        )
        assert not _快取檔(乾淨根).exists(), (
            f"沒有數字卻建了快取檔（等於把「查不到」寫成 0%）：{原始!r}"
        )

        有舊檔的根 = tmp_path / f"有舊檔-{第幾種}"
        舊檔 = _寫舊快取(有舊檔的根)
        本來的 = _檔案指紋(舊檔)
        再來 = _餵狀態列(有舊檔的根, 原始)
        assert (再來.returncode, 再來.stdout, 再來.stderr) == (0, "", "")
        assert _檔案指紋(舊檔) == 本來的, f"讀不出數字卻動了既有快取：{原始!r}"

    # ── 三、百分比是小數：四捨五入，不是截斷 ──────────────────────────
    for 餵進去的, 該存成 in ((94.6, 95), (94.4, 94)):
        小數根 = tmp_path / f"小數-{餵進去的}"
        結果 = _餵狀態列(小數根, _狀態列原始(現在, 五小時用掉=餵進去的))
        assert (結果.returncode, 結果.stdout, 結果.stderr) == (0, "", "")
        存進去的 = _家(json.loads(_快取檔(小數根).read_text(encoding="utf-8")), "cl")
        assert 存進去的["windows"][0]["used_percent"] == 該存成, (  # type: ignore[index]
            f"{餵進去的}% 應四捨五入成 {該存成}：{存進去的}"
        )
        assert isinstance(存進去的["windows"][0]["used_percent"], int), (  # type: ignore[index]
            "存的是整數；小數存進去，門檻那一比會在別的地方出意外"
        )


def test_狀態列百分比剛好一半要四捨五入進位(tmp_path: Path) -> None:
    """百分比剛好落在 `.5` 時，四捨五入應往上，不接受 Python 銀行家捨入。"""
    現在 = int(time.time())
    根 = tmp_path / "剛好一半"

    結果 = _餵狀態列(根, _狀態列原始(現在, 五小時用掉=94.5))

    assert (結果.returncode, 結果.stdout, 結果.stderr) == (0, "", "")
    快取 = json.loads(_快取檔(根).read_text(encoding="utf-8"))
    claude = _家(快取, "cl")
    assert claude["windows"][0]["used_percent"] == 95  # type: ignore[index]


_交錯注入內容 = """
import os
import time
from pathlib import Path

from nova.載體 import 額度 as 額度載體

角色 = os.environ["NOVA_QUOTA_TEST_ROLE"]
標記目錄 = Path(os.environ["NOVA_QUOTA_TEST_MARK_DIR"])


def 報到(名稱):
    (標記目錄 / 名稱).touch()


def 等標記(名稱, 最多秒=3.0):
    截止 = time.monotonic() + 最多秒
    while not (標記目錄 / 名稱).exists():
        if time.monotonic() >= 截止:
            break
        time.sleep(0.005)


原本讀取 = 額度載體._讀得回來的快取
已過查詢前置 = False


if 角色 == "query":
    原本查詢年紀 = 額度載體._那幾家的年紀

    def 記下已過查詢前置(*args, **kwargs):
        global 已過查詢前置
        結果 = 原本查詢年紀(*args, **kwargs)
        已過查詢前置 = True
        return 結果

    額度載體._那幾家的年紀 = 記下已過查詢前置


讀取次數 = 0


def 交錯讀取():
    global 讀取次數
    讀取次數 += 1
    快取 = 原本讀取()
    if 角色 == "query" and not 已過查詢前置:
        return 快取
    報到(f"{角色}-讀完")
    if 角色 == "statusline":
        等標記("query-讀完")
        報到("statusline-可寫")
    elif 角色 == "query":
        等標記("statusline-可寫")
    return 快取


額度載體._讀得回來的快取 = 交錯讀取

原本寫入 = 額度載體._寫入快取檔


def 交錯寫入(*args, **kwargs):
    if 角色 == "statusline" and (標記目錄 / "query-讀完").exists():
        等標記("query-寫完")
    結果 = 原本寫入(*args, **kwargs)
    if 角色 == "query":
        報到("query-寫完")
    return 結果


額度載體._寫入快取檔 = 交錯寫入

if 角色 == "query":
    現在秒 = int(os.environ["NOVA_QUOTA_TEST_NOW"])

    def 假codex(**kwargs):
        return [{"label": "5h", "used_percent": 88, "resets_at": 現在秒 + 60}], None

    def 假agy():
        return [{"label": "7d", "used_percent": 55, "resets_at": 現在秒 + 120}], None

    額度載體.查詢codex額度 = 假codex
    額度載體.查詢agy額度 = 假agy
"""


def test_兩個寫入端交錯讀同一份舊快取仍保留所有家族且檔案完整(tmp_path: Path) -> None:
    """兩個額度寫入端交錯時，必須保留所有家族且快取每次都能解析成完整 JSON。

    先讓狀態列寫入端讀完舊快取，再啟動一般查詢寫入端；兩邊都在真正合併前
    取得同一份舊內容，並固定讓一般查詢先落盤；這個同步點保護兩個跨程序
    寫入端的合併結果不遺失任何家族。另一條執行緒反覆解析檔案，則釘住落盤
    期間不能暴露截斷或半份 JSON。
    """
    狀態根 = tmp_path / "交錯狀態"
    檔 = _快取檔(狀態根)
    現在 = int(time.time())
    填充家: dict[str, object] = {
        "family": "other",
        "windows": [{"label": "1m", "used_percent": 0, "resets_at": 舊全域時戳}] * 30_000,
    }
    _寫自帶時戳的快取(
        狀態根,
        [{**原本的cx, "ts": 舊全域時戳}, {**原本的ay, "ts": 舊全域時戳}, 填充家],
        全域ts=舊全域時戳,
    )

    標記目錄 = tmp_path / "交錯標記"
    標記目錄.mkdir()
    注入目錄 = tmp_path / "交錯注入"
    注入目錄.mkdir()
    (注入目錄 / "sitecustomize.py").write_text(_交錯注入內容, encoding="utf-8")
    原本Python路徑 = os.environ.get("PYTHONPATH", "")
    Python路徑 = os.pathsep.join(項 for 項 in (str(注入目錄), 原本Python路徑) if 項)
    共用環境 = {
        **os.environ,
        "XDG_STATE_HOME": str(狀態根),
        "PYTHONPATH": Python路徑,
        "NOVA_QUOTA_TEST_MARK_DIR": str(標記目錄),
        "NOVA_QUOTA_TEST_NOW": str(現在),
    }

    停止 = threading.Event()
    已讀到 = threading.Event()
    壞檔: list[str] = []
    讀者 = threading.Thread(target=_反覆讀快取, args=(檔, 停止, 已讀到, 壞檔), daemon=True)
    讀者.start()
    assert 已讀到.wait(timeout=5), "讀者連初始快取都讀不到，測試前提不成立"

    狀態列程序 = subprocess.Popen(  # noqa: S603
        [str(nova執行檔), "額度", "--從狀態列"],
        env={**共用環境, "NOVA_QUOTA_TEST_ROLE": "statusline"},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    查詢程序: subprocess.Popen[str] | None = None
    try:
        assert 狀態列程序.stdin is not None
        狀態列程序.stdin.write(_狀態列原始(現在))
        狀態列程序.stdin.close()
        _等到並行報到(標記目錄 / "statusline-讀完", 狀態列程序)

        查詢程序 = subprocess.Popen(  # noqa: S603
            [str(nova執行檔), "額度", "--最舊", "0"],
            env={**共用環境, "NOVA_QUOTA_TEST_ROLE": "query"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        狀態列程序.wait(timeout=30)
        查詢程序.wait(timeout=30)
        assert 狀態列程序.returncode == 0
        assert 狀態列程序.stdout is not None
        assert 狀態列程序.stderr is not None
        assert 狀態列程序.stdout.read() == ""
        assert 狀態列程序.stderr.read() == ""
        assert 查詢程序.returncode == 0
    finally:
        for 程序 in (狀態列程序, 查詢程序):
            if 程序 is not None and 程序.poll() is None:
                程序.kill()
                程序.wait(timeout=5)
        停止.set()
        讀者.join(timeout=5)

    assert not 壞檔, f"兩個寫入端交錯期間讀到了不完整快取：{壞檔[0]}"
    寫完的 = json.loads(檔.read_text(encoding="utf-8"))
    assert {一家["family"] for 一家 in 寫完的["families"]} == {"cx", "ay", "cl", "other"}
    assert _家(寫完的, "cx")["windows"] == [
        {"label": "5h", "used_percent": 88, "resets_at": 現在 + 60}
    ]
    assert _家(寫完的, "ay")["windows"] == [
        {"label": "7d", "used_percent": 55, "resets_at": 現在 + 120}
    ]
    assert _家(寫完的, "cl")["windows"] == [
        {"label": "5h", "used_percent": 41, "resets_at": 現在 + 3600},
        {"label": "7d", "used_percent": 7, "resets_at": 現在 + 86400},
    ]
    assert len(cast("list[object]", _家(寫完的, "other")["windows"])) == 30_000

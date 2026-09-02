"""派工儀表板的**資料層**：讀取器 → `契約.儀表板` 一份 frozen dataclass。

今天那份儀表板的每個數字是主 agent 手拼 shell 算出來的，邏輯只活在 shell
歷史裡——那是第二真相。這個檔釘的是唯一真相那條路：
**nova 自己的公開讀取器組出一份契約**，模板只准渲染契約裡有的格子。

碰檔案、開 git 子程序，所以住整合層。

被釘的介面（實作還不存在，這個檔現在是紅的）：

    from nova.契約.儀表板 import 儀表板, 儀表板轉字典, ...
    from nova.載體.儀表板 import 組儀表板

    一份: 儀表板 = 組儀表板(專案, 查線們=假的查並行現況)

`查線們` 由參數注入：線的現況要開 `ps` 與 git 子程序才問得到，那不是這一格
要驗的東西；注入之後「線現況 → 契約」這條轉換才驗得到（`跑多久` 那個
`etime` 字串解成秒、退出碼分佈、票標題從哪張票讀）。

import 區的那兩行 `儀表板` 現在被 ruff 排在第三方那一塊：模組還不存在，
isort 的 first-party 判定是看 `src/` 底下有沒有那個檔。**實作落地之後
`ruff check --fix` 會把它們排回 `nova.*` 那一塊**，那是預期中的一次重排。

**三值原則**（票 09）在這裡是硬性行為：
「契約裡沒有這一格」（未接線）、「有這一格但這次查不到」（`None`）、
「有值」是三件不同的事。算不出成本的執行**不准當 0**——低報的成本比沒有
成本更危險，因為它看起來像個數字（同一條規則已經在 `帳本讀取._總成本` 生效）。
"""

import json
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from nova.契約.儀表板 import (
    一家用量,
    一階,
    儀表板轉字典,
    失敗碼,
    帳本可見度,
    收件匣,
    負控覆蓋,
    退出碼分佈,
)
from nova.契約.工作流 import 階段代碼
from nova.契約.成果 import 成果
from nova.契約.線觀測 import 線現況
from nova.契約.遮罩 import 已經遮過了
from nova.載體.儀表板 import 組儀表板
from nova.載體.已處理 import 已處理目錄
from nova.載體.帳本 import 預設帳本目錄
from nova.載體.收件 import 收件目錄, 處理中目錄
from nova.載體.狀態 import 狀態根目錄
from nova.載體.自己動手 import 繞過目錄
from nova.載體.規則表 import 建規則表
from tests.單元.test_儀表板契約 import _契約說的落盤鍵樹

_假憑證 = "sk-ant-api03-" + "A" * 60


def _git(在: Path, *參數: str) -> str:
    """跑一條 git，回 stdout。使用者設定用 `-c` 帶進去，不吃跑測試那台機器的。"""
    出 = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *參數],
        cwd=在,
        capture_output=True,
        text=True,
        check=True,
    )
    return 出.stdout


def _建repo(在: Path) -> str:
    """建一個只有一筆 commit 的 repo，回傳那筆的完整 sha。"""
    在.mkdir(parents=True, exist_ok=True)
    _git(在, "init", "-q", "-b", "main")
    (在 / "README.md").write_text("第一版\n", encoding="utf-8")
    _git(在, "add", ".")
    _git(在, "commit", "-qm", "初始化")
    return _git(在, "rev-parse", "HEAD").strip()


def _寫帳(目錄: Path, 識別: str, 事件們: list[dict[str, Any]]) -> Path:
    """在指定的帳本目錄放一本看得懂的帳（形狀照 `test_帳本跨專案.py:38 寫一份`）。"""
    目錄.mkdir(parents=True, exist_ok=True)
    檔 = 目錄 / f"{識別}.jsonl"
    檔.write_text(
        "".join(json.dumps(事 | {"run": 識別}, ensure_ascii=False) + "\n" for 事 in 事件們),
        encoding="utf-8",
    )
    return 檔


def _造成果(退出碼: int) -> 成果:
    """一筆最小的成果帳，只有退出碼是這支測試在意的。"""
    return 成果(
        執行識別碼="20260902T090000Z-線",
        任務=已經遮過了("做一件事", 因為="測試資料，本來就沒有祕密"),
        收場="完成",
        退出碼=退出碼,
        起="2026-09-02T09:00:00+00:00",
        迄="2026-09-02T09:05:00+00:00",
        走了幾階=7,
        總token=0,
    )


def _造線(**覆寫: object) -> 線現況:
    """假的 `線現況`（造法照 `tests/單元/test_線排版.py:10 _造線資料`）。"""
    預設: dict[str, object] = {
        "名字": "無名",
        "在跑嗎": False,
        "跑多久": None,
        "啟動時間": None,
        "目前階段": None,
        "上一次": None,
        "護欄原因": None,
        "未提交檔案數": 0,
        "基底落後數": 0,
    }
    預設.update(覆寫)
    return 線現況(**預設)  # type: ignore[arg-type]


def _造狀態目錄(tmp_path: Path) -> tuple[Path, str, Callable[[Path], tuple[線現況, ...]]]:
    """造一份「今天真的長這樣」的狀態目錄，回傳（專案根、HEAD sha、注入用的查線們）。

    `XDG_STATE_HOME` 由 conftest 的 autouse fixture 導到 tmp，所以
    `收件目錄()`／`預設帳本目錄()` 這些落點自己就會落在暫存區，不必 monkeypatch。
    """
    專案 = tmp_path / "主線"
    sha = _建repo(專案)

    # 收件匣：等著 3 張。**只有根目錄的檔算數**，`處理中/` 是旁邊那個子目錄。
    收件 = 收件目錄(專案)
    收件.mkdir(parents=True, exist_ok=True)
    for 名 in ("甲", "乙", "丙"):
        (收件 / f"20260902T0900{名}.md").write_text(f"# 待辦{名}\n", encoding="utf-8")

    # 處理中：2 張，其中一張讀不動（非 UTF-8）。**讀不動要數得出來**，
    # 不然「看起來沒事」跟「真的沒事」長得一樣。
    處理中 = 處理中目錄(收件)
    處理中.mkdir(parents=True, exist_ok=True)
    (處理中 / "20260902T0910甲.md").write_text("# 正在做的\n", encoding="utf-8")
    (處理中 / "20260902T0911乙.md").write_bytes(b"\xff\xfe# \xff\xff\xfe")

    # 已完成：`完成一件()` 只搬 `*.收件` 進去，旁邊那兩個 `.json` 是成果帳，
    # `ls | wc -l` 會把它們一起算進去——那正是手拼 shell 算錯的地方。
    已處理 = 已處理目錄(專案)
    已處理.mkdir(parents=True, exist_ok=True)
    (已處理 / "20260902T0800Z-甲.收件").write_text("# 做完的\n", encoding="utf-8")
    (已處理 / "20260902T0800Z-甲.json").write_text("{}", encoding="utf-8")
    (已處理 / "20260902T0801Z-乙.json").write_text("{}", encoding="utf-8")

    # 人手搬出來的四個目錄，nova 不認識它們：一張都不准被算進任何一格。
    for 人手 in ("已完成", "已併入", "鬼影"):
        (收件 / 人手).mkdir()
        (收件 / 人手 / "人手放的.md").write_text("# 人手\n", encoding="utf-8")

    # 繞過記號：一個 session 一個 `.md`。
    繞過 = 繞過目錄(專案)
    繞過.mkdir(parents=True, exist_ok=True)
    (繞過 / "會話甲.md").write_text(
        "2026-09-02T09:00:00+00:00\nnova 生不出這一格\n", encoding="utf-8"
    )

    # 本專案的帳：claude 一次呼叫，有成本，另外帶了快取讀取 token
    # （`總token` 四種都算，`各家.token` 只算輸入＋輸出——兩格不是同一個數）。
    _寫帳(
        預設帳本目錄(專案),
        "20260902T090000Z-本專案",
        [
            {"seq": 1, "ts": "t1", "event": "call_started", "call": 1, "family": "claude"},
            {
                "seq": 2,
                "ts": "t2",
                "event": "call_finished",
                "call": 1,
                "family": "claude",
                "outcome": "success",
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_tokens": 5,
                "cost_usd": 0.5,
            },
        ],
    )

    # 別的專案鍵的帳：codex 一次呼叫，**沒有 cost_usd**，而且失敗帶了 failure_code。
    _寫帳(
        狀態根目錄() / "專案" / "nova-wt-別條線-deadbeef" / "帳本",
        "20260902T093000Z-別條線",
        [
            {"seq": 1, "ts": "t3", "event": "call_started", "call": 1, "family": "codex"},
            {
                "seq": 2,
                "ts": "t4",
                "event": "call_finished",
                "call": 1,
                "family": "codex",
                "outcome": "failed",
                "failure_code": "quota_exhausted",
                "input_tokens": 30,
                "output_tokens": 8,
            },
        ],
    )

    # 線甲：在跑，收件匣裡有一張自己的票（**標題含假憑證，遮罩要吃掉它**）。
    線甲 = tmp_path / "線甲"
    甲處理中 = 處理中目錄(收件目錄(線甲))
    甲處理中.mkdir(parents=True, exist_ok=True)
    (甲處理中 / "20260902T0920.md").write_text(
        f"前言一行不是標題\n\n# 修好收件匣 {_假憑證}\n\n內文\n", encoding="utf-8"
    )

    # 線乙：收工了，而且**自己有一本帳**——七階時間軸從那本帳的 `stage_finished` 讀。
    線乙 = tmp_path / "線乙"
    _寫帳(
        預設帳本目錄(線乙),
        "20260902T094000Z-線乙",
        [
            {
                "seq": 1,
                "ts": "t5",
                "event": "stage_finished",
                "stage": "impl",
                "outcome": "完成",
                "gate_green": True,
            },
            {
                "seq": 2,
                "ts": "t6",
                "event": "stage_finished",
                "stage": "verify",
                "outcome": "完成",
                "gate_green": False,
            },
        ],
    )

    線丙 = tmp_path / "線丙"
    線丁 = tmp_path / "線丁"

    假線們 = (
        _造線(名字="main", 路徑=專案, 是主工作區=True),
        _造線(
            名字="甲",
            路徑=線甲,
            在跑嗎=True,
            跑多久="03:20",
            啟動時間="2026-09-02T09:00:00+00:00",
            目前階段="impl",
        ),
        _造線(名字="乙", 路徑=線乙, 上一次=_造成果(0), 未提交檔案數=2),
        _造線(名字="丙", 路徑=線丙, 上一次=_造成果(4), 護欄原因="預算用完"),
        _造線(名字="丁", 路徑=線丁, 上一次=_造成果(99), 跑多久="亂七八糟"),
    )

    # 負控覆蓋那三格：檔數，不是「刀數」（刀數要 import tests，src 不准，那格未接線）。
    登記們 = 專案 / "tests" / "負控" / "登記們"
    登記們.mkdir(parents=True)
    for 名 in ("__init__.py", "甲.py", "乙.py"):
        (登記們 / 名).write_text("登記 = ()\n", encoding="utf-8")
    紀錄 = 專案 / "docs" / "負控紀錄"
    紀錄.mkdir(parents=True)
    for 名 in ("一.md", "二.md"):
        (紀錄 / 名).write_text("# 紀錄\n", encoding="utf-8")

    def 假查線們(根: Path) -> tuple[線現況, ...]:
        """注入版的 `查並行現況`：**要被問的是專案根**，問錯地方就當場說。"""
        assert 根 == 專案, f"查線們拿到的不是專案根：{根}"
        return 假線們

    return 專案, sha, 假查線們


def test_讀取器對造好的狀態目錄回出契約(tmp_path: Path) -> None:
    """一份儀表板的每一格都要回得出來，而且回的是**讀取器問到的那個數**。

    這支同時守三件事，任何一件破掉都該紅：

    1. **每一格只有一個來源。** 已完成數來自 `已處理/` 底下的 `*.收件`，
       不是 `收件/已完成/`（人手目錄）、也不是 `ls 已處理 | wc -l`（混了成果 json）。
    2. **算不出來不准填零。** 沒有 `cost_usd` 的那本帳要被數進
       `算不出成本的執行數`，而 `總成本美金` 是另外那本的 0.5——不是 0、也不是 None。
    3. **落盤鍵是窮舉的。** `儀表板轉字典` 的頂層鍵集合就是「儀表板有哪幾格」，
       少一格代表模板上會安靜地少一個數字。
    """
    專案, sha, 假查線們 = _造狀態目錄(tmp_path)

    一份 = 組儀表板(專案, 查線們=假查線們)

    # 標頭：時間是 UTC ISO（帶時區，不是本地時間字串）。
    assert datetime.fromisoformat(一份.產生時間).tzinfo is not None
    assert 一份.工作目錄 == str(專案)
    assert 一份.目前commit == sha

    # 錢與量：`總token` 四種 token 都算（100+20+5 = 125），`+ 38` 是別條線那本。
    assert 一份.總token == 163
    assert 一份.總成本美金 == pytest.approx(0.5), "沒有成本的那本要跳過，不准把它當 0 加進來"
    assert 一份.算不出成本的執行數 == 1, "跳過了就要數出來——證據不完整不准長得像事情沒發生"
    assert 一份.呼叫次數 == 2
    assert 一份.繞過次數 == 1

    # 收件匣：等著 3、處理中 2（含讀不動 1）、已完成 1。人手目錄一張都不准混進來。
    assert 一份.收件匣 == 收件匣(等著=3, 處理中=2, 已完成=1, 讀不動=1)

    # 線：只有 `在跑嗎 is True` 且不是主工作區的才算在跑。
    assert 一份.在跑的線 == 1
    assert 一份.退出碼 == 退出碼分佈(成功=1, 確定失敗=0, 未知=0, 護欄=1, 其他=1)
    assert 一份.工作樹數 == 0, "`工作樹們` 第一筆固定是主工作區，要扣掉"

    線們 = {一條.名字: 一條 for 一條 in 一份.線們}
    assert [一條.名字 for 一條 in 一份.線們] == ["main", "甲", "乙", "丙", "丁"]

    主 = 線們["main"]
    assert (主.票標題, 主.路徑) == (None, str(專案)), (
        "主工作區的收件匣是整個專案的匣，拿它當『這條線在做什麼』是錯的"
    )

    甲 = 線們["甲"]
    assert 甲.票標題 is not None
    assert "修好收件匣" in 甲.票標題, "票標題要取處理中那張票的第一個 `# ` 行"
    assert _假憑證 not in 甲.票標題, "票標題會落到磁碟上兩個新地方，漏遮一個字都不會有人說"
    assert (甲.在跑嗎, 甲.目前階段, 甲.啟動時間, 甲.退出碼, 甲.七階) == (
        True,
        "impl",
        "2026-09-02T09:00:00+00:00",
        None,
        (),
    ), "在跑的那條沒有退出碼、也還沒有帳本——查不到就留空，不准編"
    assert 甲.跑了幾秒 == 200, "`跑多久` 是 ps 的 etime 字串（mm:ss），契約上要是秒數"

    乙 = 線們["乙"]
    assert (乙.目前階段, 乙.退出碼, 乙.未提交檔案數) == (None, 0, 2), (
        "查不到階段是 `None`，不准拿空字串或『未知』頂替"
    )
    assert 乙.七階 == (
        一階(階段="impl", 終局="完成", 判準綠=True),
        一階(階段="verify", 終局="完成", 判準綠=False),
    )

    assert (線們["丙"].退出碼, 線們["丙"].護欄原因) == (4, "預算用完")
    assert 線們["丁"].跑了幾秒 is None, "解不動的 etime 是 `None`，不是 0"

    # 各家用量：`token` 只算輸入＋輸出（125 那筆的快取 token 不在這一格）。
    各家 = {一家.供應商: 一家 for 一家 in 一份.各家}
    assert set(各家) == {"claude", "codex"}
    assert all(isinstance(一家, 一家用量) for 一家 in 一份.各家)
    assert (各家["claude"].次數, 各家["claude"].token, 各家["claude"].平均每次) == (1, 120, 120)
    assert (各家["codex"].次數, 各家["codex"].token, 各家["codex"].平均每次) == (1, 38, 38)
    assert 各家["claude"].佔比 == pytest.approx(120 / 158)
    assert 各家["codex"].佔比 == pytest.approx(38 / 158)
    assert sum(一家.佔比 for 一家 in 一份.各家) == pytest.approx(1.0), (
        "佔比的分母要跟分子同一個基準"
    )

    # 帳本看得見多少：四個專案鍵目錄，其中三個真的有帳。
    # **兩個數字要分開**：「沒有帳」跟「沒有這個專案」不是同一件事。
    assert 一份.可見度 == 帳本可見度(
        本專案token=125, 全部token=163, 專案鍵總數=4, 有內容的專案鍵=3, 跳過的檔=0
    )

    assert 一份.失敗碼們 == (失敗碼(代碼="quota_exhausted", 次數=1),)

    assert 一份.負控 == 負控覆蓋(
        登記檔數=2,
        紀錄檔數=2,
        閘規則數=len(建規則表(專案)),
        階段數=len(階段代碼),
    )

    # 落盤鍵：ASCII、而且就是這幾格。多一格少一格都要當場說。
    # **哪幾格是契約自己說的**（`落盤鍵樹`）：這裡再手抄一份 ASCII 鍵集合的話，
    # 兩份一起漏一格照樣相等，而那一格會從 `--json` 上安靜地消失。
    落盤 = 儀表板轉字典(一份)
    assert set(落盤) == set(_契約說的落盤鍵樹())
    assert all(鍵.isascii() for 鍵 in 落盤), "`--json` 是給別的程式讀的，中文鍵在 shell 裡很難打"


def test_成本分流依摘要欄位且空家族的零成本仍要保留(tmp_path: Path) -> None:
    """成本是否算得出來只看摘要的 `總成本美金`，不另猜 `各家` 是否為空。

    兩本有呼叫但沒有 `cost_usd` 的帳，其摘要成本是 `None`；`線乙` 那本只有
    階段事件，公開讀取器明定空家族的摘要成本是 `0.0`。儀表板要保留這個
    已知的零成本，並只把前兩本算進「算不出成本」的數量。
    """
    專案, _sha, 假查線們 = _造狀態目錄(tmp_path)
    # 把唯一那本帶成本的帳換掉（同一個執行識別碼，蓋過去）：現在只有兩本成本未知。
    _寫帳(
        預設帳本目錄(專案),
        "20260902T090000Z-本專案",
        [
            {"seq": 1, "ts": "t1", "event": "call_started", "call": 1, "family": "claude"},
            {
                "seq": 2,
                "ts": "t2",
                "event": "call_finished",
                "call": 1,
                "family": "claude",
                "outcome": "success",
                "input_tokens": 100,
                "output_tokens": 20,
            },
        ],
    )

    一份 = 組儀表板(專案, 查線們=假查線們)

    assert (一份.總成本美金, 一份.算不出成本的執行數) == (0.0, 2), (
        "成本分流要依摘要的 None／數值；空家族的 0.0 不是查不到，兩本缺成本才要被計數"
    )


def test_所有執行都無成本時總成本是查不到不是零(tmp_path: Path) -> None:
    """所有已發現執行都沒有成本時，總成本必須保留「查不到」而不是補零。"""
    專案, _sha, 假查線們 = _造狀態目錄(tmp_path)

    # 把 fixture 裡唯一有成本的執行改成沒有 `cost_usd`。
    _寫帳(
        預設帳本目錄(專案),
        "20260902T090000Z-本專案",
        [
            {"seq": 1, "ts": "t1", "event": "call_started", "call": 1, "family": "claude"},
            {
                "seq": 2,
                "ts": "t2",
                "event": "call_finished",
                "call": 1,
                "family": "claude",
                "outcome": "success",
                "input_tokens": 100,
                "output_tokens": 20,
            },
        ],
    )

    # fixture 的線乙原本只有階段事件，摘要成本是已知的 0.0；也改成缺成本的呼叫，
    # 讓跨專案盤點到的三本帳全部都是 `總成本美金 is None`。
    _寫帳(
        預設帳本目錄(tmp_path / "線乙"),
        "20260902T094000Z-線乙",
        [
            {"seq": 1, "ts": "t5", "event": "call_started", "call": 1, "family": "agy"},
            {
                "seq": 2,
                "ts": "t6",
                "event": "call_finished",
                "call": 1,
                "family": "agy",
                "outcome": "success",
                "input_tokens": 10,
                "output_tokens": 2,
            },
        ],
    )

    一份 = 組儀表板(專案, 查線們=假查線們)

    assert (一份.總成本美金, 一份.算不出成本的執行數) == (None, 3), (
        "所有成本都查不到時不准把空的成本清單 sum 成 0"
    )


def test_查不到在不在跑的線不准算進已收線的退出碼分佈(tmp_path: Path) -> None:
    """`在跑嗎 is None` 是「問不到那個程序」，不是「收工了」。

    把 `None` 當成 `False` 的話，一條問不到狀態的線會帶著它上一次的退出碼
    被算成「這次收線收成 0」——**上一輪的結果會冒充成這一輪的結果**。
    只有明確 `is False` 才有資格進這張分佈表。
    """
    專案, _sha, _假查線們 = _造狀態目錄(tmp_path)
    問不到的 = _造線(名字="戊", 路徑=tmp_path / "線戊", 在跑嗎=None, 上一次=_造成果(0))

    一份 = 組儀表板(專案, 查線們=lambda _: (問不到的,))

    assert 一份.退出碼 == 退出碼分佈(成功=0, 確定失敗=0, 未知=0, 護欄=0, 其他=0), (
        "問不到程序狀態的線還沒有這一輪的退出碼，拿上一次那個頂替就是編一個結果出來"
    )


def test_失敗碼多過七個只留前七名(tmp_path: Path) -> None:
    """介面上那一區寫的是**前七名**，資料層就要只回七筆。

    帳本會一直長，失敗碼的種類跟著長。全部回出去的話那一區會無上限往下拉，
    而「最常見的是哪幾個」——那一區存在的唯一理由——反而看不出來。
    """
    專案, _sha, 假查線們 = _造狀態目錄(tmp_path)
    幾次 = {
        "fc_a": 9,
        "fc_b": 8,
        "fc_c": 7,
        "fc_d": 6,
        "fc_e": 5,
        "fc_f": 4,
        "fc_g": 3,
        "fc_h": 2,
    }
    事件們: list[dict[str, Any]] = []
    for 碼, 次 in 幾次.items():
        for _ in range(次):
            呼叫 = len(事件們) // 2 + 1
            事件們.append(
                {
                    "seq": len(事件們) + 1,
                    "ts": "t7",
                    "event": "call_started",
                    "call": 呼叫,
                    "family": "codex",
                }
            )
            事件們.append(
                {
                    "seq": len(事件們) + 1,
                    "ts": "t8",
                    "event": "call_finished",
                    "call": 呼叫,
                    "family": "codex",
                    "outcome": "failed",
                    "failure_code": 碼,
                }
            )
    _寫帳(
        狀態根目錄() / "專案" / "nova-wt-失敗碼-cafe" / "帳本",
        "20260902T095000Z-失敗碼",
        事件們,
    )

    一份 = 組儀表板(專案, 查線們=假查線們)

    assert 一份.失敗碼們 == tuple(失敗碼(代碼=碼, 次數=次) for 碼, 次 in list(幾次.items())[:7]), (
        "失敗碼那一區是前七名：第八名（與更後面的 quota_exhausted）不准擠進來"
    )

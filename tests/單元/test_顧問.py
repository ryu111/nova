"""顧問把「同一個護欄原因反覆出現」打包成診斷素材時的行為契約。

這個檔守三件事，三件都是「顧問不准變成第二個亂改東西的執法點」的機械背書：

* **素材自己也要去重**——流 2 還沒回票之前，每輪醒來都不准再堆一份。
* **去重鍵是原因＋票**——已經有人在處理這個原因就不觸發，收件匣與處理中都算。
* **模板對所有原因逐字一致**——顧問只搬證據，不准替診斷先猜好修法。

只碰 `tmp_path`：狀態根目錄由 conftest 的 `帳本不准寫到家目錄` 導進暫存區。
"""

import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nova.載體.專案脈絡 import 建專案執行脈絡
from nova.載體.已處理 import 已處理目錄
from nova.載體.收件 import 收件目錄, 處理中目錄
from nova.載體.狀態 import 狀態根目錄
from nova.載體.顧問 import 落成診斷素材

#: 所有測試共用的「現在」。**收成參數不 monkeypatch `datetime`**，
#: 所以窗口起訖、素材檔名都由它推得出來，兩次呼叫的結果才比得動。
_當下 = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)

#: 三筆同原因的執行識別碼；`迄` 各往前一小時，全部落在 24 小時窗口內。
_三筆 = ("run-甲", "run-乙", "run-丙")

#: 收件匣檔名的形狀：`<時戳>-<來源>-<標籤>-<亂碼>.md`，來源要認得出來。
#: 這裡直接寫檔不走 `丟一件`——那支對自主來源要求四欄，
#: 而這幾張票測的是去重鍵，不是票的完整性。
_票檔名 = "20260903T090000Z-typed-顧問測試用票-abc123.md"


def _時戳(那時: datetime) -> str:
    """成果帳上的 `ended_at` 長什麼樣（`帳本` 那支落盤格式）。"""
    return 那時.isoformat(timespec="milliseconds").replace("+00:00", "Z")


#: `覆寫` 裡放這個值＝**這一欄整個不寫進帳**。跟 `None` 是兩件事：
#: `None` 是「有這一欄、沒撞護欄」，缺鍵是「那時候還沒有這一欄」的舊帳。
_沒有這一欄 = object()


def _落一筆成果(
    專案: Path,
    *,
    執行識別碼: str,
    原因: str,
    迄: datetime,
    覆寫: dict[str, object] | None = None,
) -> Path:
    """直接寫一份成果帳的 JSON（鍵是落盤用的 ASCII）。

    `覆寫` 收成一格 mapping 而不是一個旗標一個參數：兄弟測試要造的變體
    （`收場="done"` 的驗收紅、缺 `guardrail_reason` 鍵的舊帳）都只是換幾個欄，
    攤成具名參數會讓這支助手一路長胖到撞 ruff 的參數上限。
    """
    目錄 = 已處理目錄(專案)
    目錄.mkdir(parents=True, exist_ok=True)
    一筆: dict[str, object] = {
        "run_id": 執行識別碼,
        "task": "把測試補齊",
        "outcome": "guardrail",
        "exit_code": 4,
        "started_at": _時戳(迄 - timedelta(minutes=20)),
        "ended_at": _時戳(迄),
        "steps": 6,
        "tokens": 12345,
        "source": "schedule",
        "guardrail_reason": 原因,
    }
    一筆.update(覆寫 or {})
    一筆 = {鍵: 值 for 鍵, 值 in 一筆.items() if 值 is not _沒有這一欄}
    落點 = 目錄 / f"{執行識別碼}.json"
    落點.write_text(json.dumps(一筆, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 落點


def _造三筆同原因(專案: Path, 原因: str) -> None:
    """三筆撞在同一個護欄原因、`迄` 都在窗口內的成果帳。"""
    for 第幾, 號 in enumerate(_三筆, start=1):
        _落一筆成果(專案, 執行識別碼=號, 原因=原因, 迄=_當下 - timedelta(hours=第幾))


def _顧問目錄(專案: Path) -> Path:
    """素材的落點。跟收件、帳本、已處理同一條規則，**不落在工作目錄**。"""
    return 建專案執行脈絡(專案).顧問


def _顧問目錄裡的檔(專案: Path) -> list[Path]:
    目錄 = _顧問目錄(專案)
    return sorted(路 for 路 in 目錄.iterdir() if 路.is_file()) if 目錄.is_dir() else []


@pytest.fixture
def 專案(tmp_path: Path) -> Path:
    """一個乾淨的工作目錄；狀態全部落在暫存的狀態根底下。"""
    根 = tmp_path / "repo"
    根.mkdir()
    return 根


def test_三筆同原因連跑兩次只產一個brief(專案: Path) -> None:
    """守素材自己的去重：同一個原因在同一個窗口內只准留一份，證據要齊三筆。"""
    _造三筆同原因(專案, "touched-tests")

    第一次 = 落成診斷素材(專案=專案, 當下=_當下, 門檻=3, 窗口=timedelta(hours=24))
    第二次 = 落成診斷素材(專案=專案, 當下=_當下, 門檻=3, 窗口=timedelta(hours=24))

    assert 第一次 is not None, "三筆同原因達門檻，該產得出一份診斷素材"
    assert 第二次 is None, "同一個原因在同一個窗口內已經有素材了，不准再堆一份"
    assert _顧問目錄裡的檔(專案) == [第一次]
    assert "touched-tests" in 第一次.name
    內容 = 第一次.read_text(encoding="utf-8")
    for 號 in _三筆:
        assert 號 in 內容, f"素材要點得出是哪幾次執行，缺了 {號}"


@pytest.mark.parametrize(
    ("票內容", "放哪"),
    [
        ("# 根因診斷：touched-tests\n\n- 這個原因已經在診斷了\n", "收件"),
        ("# 紅一直送錯角色\n\n<!--nova:蓋住原因 touched-tests-->\n\n## 輸入\n", "收件"),
        ("# 根因診斷：touched-tests\n\n- 這個原因已經在診斷了\n", "處理中"),
    ],
    ids=["流2出的票帶機器鍵", "人手寫的票帶蓋住原因標記", "票已經被收下在處理中"],
)
def test_已有同原因的票就不產brief(專案: Path, 票內容: str, 放哪: str) -> None:
    """守去重鍵是「原因＋票」：已經有人在處理這個原因就不觸發，兩個目錄都要看。"""
    _造三筆同原因(專案, "touched-tests")
    目的地 = 收件目錄(專案) if 放哪 == "收件" else 處理中目錄(收件目錄(專案))
    目的地.mkdir(parents=True, exist_ok=True)
    (目的地 / _票檔名).write_text(票內容, encoding="utf-8")

    落點 = 落成診斷素材(專案=專案, 當下=_當下, 門檻=3, 窗口=timedelta(hours=24))

    assert 落點 is None, "這個原因已經有票了，再堆一份素材就是重複派工"
    assert _顧問目錄裡的檔(專案) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root 讀得動 0o000 的目錄，這條驗不了")
def test_收件匣讀不動時不觸發(專案: Path) -> None:
    """守 fail-closed：問不出「有沒有票」的時候算它有，寧可漏一輪也不堆第二份素材。

    收件匣**不存在**是第一次跑的正常狀態（那時該觸發）；
    存在卻讀不動是「查不到」，跟「查到沒有」不是同一件事。
    """
    _造三筆同原因(專案, "touched-tests")
    收件 = 收件目錄(專案)
    收件.mkdir(parents=True, exist_ok=True)
    收件.chmod(0o000)
    try:
        落點 = 落成診斷素材(專案=專案, 當下=_當下, 門檻=3, 窗口=timedelta(hours=24))
        檔們 = _顧問目錄裡的檔(專案)
    finally:
        收件.chmod(0o755)

    assert 落點 is None, "收件匣讀不動就答不出這個原因有沒有票，答不出來時不准觸發"
    assert 檔們 == [], "查不到票的時候落了素材，等於把 fail-closed 讀成 fail-open"


@pytest.mark.parametrize(
    ("幾小時前", "門檻", "窗口小時", "算進來的"),
    [
        ((1, 2), 2, 24, (1, 2)),
        ((1, 2), 3, 24, ()),
        ((26, 27, 28), 3, 30, (26, 27, 28)),
        ((26, 27, 32), 3, 30, ()),
    ],
    ids=[
        "門檻2兩筆就達標",
        "門檻3兩筆還不夠",
        "窗口30小時吃得到第28小時那筆",
        "窗口30小時吃不到第32小時那筆",
    ],
)
def test_門檻與窗口是參數不是常數(
    專案: Path,
    幾小時前: tuple[int, ...],
    門檻: int,
    窗口小時: int,
    算進來的: tuple[int, ...],
) -> None:
    """守門檻與窗口由呼叫端給定：換一組參數，同一份帳要換一個答案。

    寫死 24 小時或寫死 3 次的話，這四組裡至少一組會答錯——
    而「要不要放寬」是人的決定，不是撞到了就調高。
    """
    原因 = "touched-tests"
    for 小時 in 幾小時前:
        _落一筆成果(
            專案,
            執行識別碼=f"run-{小時}h",
            原因=原因,
            迄=_當下 - timedelta(hours=小時),
        )

    落點 = 落成診斷素材(專案=專案, 當下=_當下, 門檻=門檻, 窗口=timedelta(hours=窗口小時))

    if not 算進來的:
        assert 落點 is None, f"窗口 {窗口小時} 小時、門檻 {門檻} 應該還沒達標"
        assert _顧問目錄裡的檔(專案) == []
        return
    assert 落點 is not None, f"窗口 {窗口小時} 小時、門檻 {門檻} 應該達標了"
    內容 = 落點.read_text(encoding="utf-8")
    for 小時 in 幾小時前:
        入帳了 = 小時 in 算進來的
        assert (f"run-{小時}h" in 內容) is 入帳了, (
            f"第 {小時} 小時那筆在 {窗口小時} 小時窗口內{'該' if 入帳了 else '不該'}算進來"
        )
    assert f"命中：{len(算進來的)} 次，門檻 {門檻}" in 內容


def test_驗收紅那種4也算進來而沒記原因的舊帳只略過(專案: Path) -> None:
    """守過濾判準是退出碼＋有沒有記原因，不是 `收場` 字串；略過的舊帳要出聲。

    驗收紅那條 4 的 `收場` 寫的是 `done`，拿 `收場 == "guardrail"` 過濾會靜靜漏掉它。
    而沒記原因的舊帳不進計數，卻要在素材上數得出來——安靜略過會讓人
    以為那個窗口真的只有這幾筆。
    """
    原因 = "acceptance-failed"
    for 第幾 in range(1, 4):
        _落一筆成果(
            專案,
            執行識別碼=f"run-驗收紅-{第幾}",
            原因=原因,
            迄=_當下 - timedelta(hours=第幾),
            覆寫={"outcome": "done"},
        )
    for 第幾 in range(1, 6):
        _落一筆成果(
            專案,
            執行識別碼=f"run-舊帳-{第幾}",
            原因=原因,
            迄=_當下 - timedelta(hours=第幾),
            覆寫={"guardrail_reason": _沒有這一欄},
        )

    落點 = 落成診斷素材(專案=專案, 當下=_當下, 門檻=3, 窗口=timedelta(hours=24))

    assert 落點 is not None, "三筆 `收場=done` 的驗收紅也是三次同原因，該產得出素材"
    assert 原因 in 落點.name
    內容 = 落點.read_text(encoding="utf-8")
    assert "命中：3 次，門檻 3" in 內容, "沒記原因的舊帳不准被數進命中次數"
    for 第幾 in range(1, 4):
        assert f"run-驗收紅-{第幾}" in 內容
    for 第幾 in range(1, 6):
        assert f"run-舊帳-{第幾}" not in 內容, "沒記原因的帳答不出是哪一種護欄，不准當證據"
    assert re.search(r"略過.*\b5 筆", 內容), f"略過了 5 筆舊帳卻沒印出來：\n{內容}"


def _挖掉資料欄(內容: str, *, 原因: str, 狀態根: Path) -> str:
    """把素材裡「跟這次資料有關」的字挖掉，只留模板本身的措辭。"""
    挖過 = 內容.replace(str(狀態根), "<狀態根>").replace(原因, "<原因>")
    return re.sub(r"\d{8}T\d{6}Z", "<時戳>", 挖過)


def test_brief不含任何按原因分支的措辭(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """守顧問只出證據不猜修法：換一個護欄原因，素材除了資料欄以外要逐字相同。"""
    專案 = tmp_path / "repo"
    專案.mkdir()
    挖過的: dict[str, str] = {}
    for 原因 in ("touched-tests", "stagnation"):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / f"state-{原因}"))
        _造三筆同原因(專案, 原因)
        落點 = 落成診斷素材(專案=專案, 當下=_當下, 門檻=3, 窗口=timedelta(hours=24))
        assert 落點 is not None, f"{原因} 三筆達門檻，該產得出素材"
        挖過的[原因] = _挖掉資料欄(落點.read_text(encoding="utf-8"), 原因=原因, 狀態根=狀態根目錄())

    assert 挖過的["touched-tests"] == 挖過的["stagnation"], (
        "模板對所有護欄原因必須逐字一致——按原因分支就是替診斷先猜好修法"
    )

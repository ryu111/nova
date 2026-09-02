"""`nova 顧問` 這格機械工序接上命令列之後的行為契約。

**直接呼叫 `主程式`，不開子程序**：coverage 追不到子程序的行，
變異閘會判成 `WRONG_TEST：沒覆蓋`（同 `tests/整合/test_線.py` 的理由）。

這個檔守三件事：

* 印出來的派工指令**貼了就跑得動**——顧問自己不呼叫模型，
  它交出去的那條指令就是它唯一的產出介面，跑不動等於沒有產出。
* 帳本目錄讀不到時回 **3（結果未知）**，不是 0。
  「沒東西可看」跟「看不到」長得一樣的話，這格就不再是帳。
* 略過了幾筆沒記原因的舊帳，**當場講出來**：略過得無聲無息的話，
  「今天沒有重覆」跟「有一半的帳我數不進去」在終端機上長得一模一樣。
"""

import json
import os
import re
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nova.契約.派工 import 工作種類
from nova.載體 import 命令列
from nova.載體.剖析器 import 建剖析器
from nova.載體.專案脈絡 import 建專案執行脈絡
from nova.載體.已處理 import 已處理目錄
from nova.載體.派工表 import 怎麼派
from nova.載體.狀態 import 狀態根目錄

#: 派工指令的前綴：貼進終端機就是這幾個字開頭。
_指令前綴 = ("uv", "run", "nova", "問")


def _時戳(那時: datetime) -> str:
    return 那時.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _落一筆(目錄: Path, 號: str, 迄: datetime, 原因: str | None) -> None:
    """一筆撞了護欄的成果帳。退出碼 4 ＋ 記了原因，就是顧問要數的那種。

    `原因=None` ＝帳上**根本沒有 `guardrail_reason` 這一欄**的舊帳：
    退出碼一樣是 4，但答不出是哪一種護欄，所以它不進計數。
    """
    目錄.mkdir(parents=True, exist_ok=True)
    一筆: dict[str, object] = {
        "run_id": 號,
        "task": "把測試補齊",
        "outcome": "guardrail",
        "exit_code": 4,
        "started_at": _時戳(迄 - timedelta(minutes=20)),
        "ended_at": _時戳(迄),
        "steps": 6,
        "tokens": 12345,
        "source": "schedule",
    }
    if 原因 is not None:
        一筆["guardrail_reason"] = 原因
    (目錄 / f"{號}.json").write_text(
        json.dumps(一筆, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _造三筆同原因(專案: Path, 原因: str) -> None:
    """三筆撞在同一個護欄原因、`迄` 都在最近幾小時內的成果帳。

    這裡不給 `當下`：走的是命令列，沒有「假裝現在幾點」的旗標，
    所以帳要落在真正的現在往前幾小時。
    """
    目錄 = 已處理目錄(專案)
    此刻 = datetime.now(UTC)
    for 第幾, 號 in enumerate(("run-甲", "run-乙", "run-丙"), start=1):
        _落一筆(目錄, 號, 此刻 - timedelta(hours=第幾), 原因)


def _挑出派工指令(輸出文字: str) -> str:
    for 行 in 輸出文字.splitlines():
        if 行.strip().startswith(" ".join(_指令前綴)):
            return 行.strip()
    pytest.fail(f"輸出裡沒有貼得動的派工指令：\n{輸出文字}")


def test_顧問印的派工指令貼上就跑得動(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """守顧問唯一的產出介面：那條指令要被剖析器與前置關卡放行，且**不動 `nova 問` 的旗標**。

    唯讀是流 2 要的，所以指令不准帶 `--可編輯`／`--全開`。
    答案落到哪是**顧問這邊的事**：走 shell 重導向落進狀態目錄的 `顧問/`，
    而不是靠 `nova 問` 那組旗標替診斷開一條寫入路徑——
    `nova 問` 的唯讀規則是別的模組的保證，顧問只借它，不改它。
    """
    專案 = tmp_path / "repo"
    專案.mkdir()
    monkeypatch.chdir(專案)
    _造三筆同原因(專案, "touched-tests")

    碼 = 命令列.主程式(["--根目錄", str(專案), "顧問", "--門檻", "3", "--窗口小時", "24"])

    輸出 = capsys.readouterr()
    合起來 = 輸出.out + 輸出.err
    assert 碼 == 0, 合起來
    素材們 = sorted(建專案執行脈絡(專案).顧問.glob("*.md"))
    assert len(素材們) == 1, f"三筆同原因該產出一份素材，實際 {素材們}"
    素材 = 素材們[0]
    指令 = _挑出派工指令(合起來)
    assert "--可編輯" not in 指令, "派的是唯讀診斷，給了可編輯就變成第二個亂改東西的執法點"
    assert "--全開" not in 指令, "同上：診斷不准拿到寫入權"
    assert f"--提示檔 {素材}" in 指令, f"提示檔要指到剛落的素材（絕對路徑）：{指令}"

    片段 = shlex.split(指令)
    assert 片段.count(">") == 1, f"答案要用一個 shell 重導向落檔：{指令}"
    切點 = 片段.index(">")
    問的片段, 落檔 = 片段[:切點], 片段[切點 + 1 :]
    assert 落檔 == [str(素材.with_name(f"{素材.stem}.答.md"))], (
        f"答案要落回素材旁邊的 <時戳>-<原因>.答.md，實際 {落檔}"
    )
    assert tuple(問的片段[:4]) == _指令前綴, (
        f"貼了就跑的指令要以 {' '.join(_指令前綴)} 開頭：{指令}"
    )
    參數 = 建剖析器(命令列.處理們).parse_args(問的片段[3:])
    assert 參數.思考深度 == "max"
    assert 參數.用 == ",".join(怎麼派(工作種類.推理).腦們), "沒給 --診斷用 就照派工表推理列"
    assert 參數.輸出檔 is None, "落檔走重導向，不借 nova 問 的 --輸出檔"
    assert not getattr(參數, "載體代寫", False), (
        "顧問不准為了落檔去動 nova 問 那組旗標——那是別的模組的保證"
    )

    # 憑證與預算不是這支要驗的東西（沒有它們每台機器結果都不一樣），
    # 擋掉之後剩下的就是「唯讀 ＋ 輸出檔」這個組合過不過得了前置關卡。
    monkeypatch.setattr(命令列, "_秘密先交出去", lambda *_: None)
    monkeypatch.setattr(命令列, "_問的預算關卡", lambda *_: None)
    這次 = 命令列._問的前置(參數)

    assert not isinstance(這次, int), (
        f"印出來的指令被 nova 問 自己擋掉了（退出碼 {這次}）：{capsys.readouterr().err}"
    )


def test_三個專案各撞一次也數得到三次(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """守顧問是**跨專案**數的：同一個原因散在三棵派工樹上，合計就是三次。

    每棵派工樹是自己一個 `專案識別`，只掃 cwd 那個等於問「今晚重覆了嗎」
    卻只翻自己那一頁——三個各一次會被讀成「誰都沒有重覆」。
    素材落在 cwd 這個權威 repo 底下，證據要點得出是哪個專案的哪一次。
    """
    專案 = tmp_path / "repo"
    專案.mkdir()
    monkeypatch.chdir(專案)
    此刻 = datetime.now(UTC)
    _落一筆(已處理目錄(專案), "run-自己這棵", 此刻 - timedelta(hours=1), "touched-tests")
    別人們 = ("別的派工樹-1111", "別的派工樹-2222")
    for 第幾, 識別 in enumerate(別人們, start=2):
        _落一筆(
            狀態根目錄() / "專案" / 識別 / "已處理",
            f"run-{識別}",
            此刻 - timedelta(hours=第幾),
            "touched-tests",
        )

    碼 = 命令列.主程式(["--根目錄", str(專案), "顧問", "--門檻", "3", "--窗口小時", "24"])

    輸出 = capsys.readouterr()
    assert 碼 == 0, 輸出.out + 輸出.err
    素材們 = sorted(建專案執行脈絡(專案).顧問.glob("*.md"))
    assert len(素材們) == 1, f"三個專案各一次就是三次，該產出一份素材，實際 {素材們}"
    內容 = 素材們[0].read_text(encoding="utf-8")
    assert "命中：3 次，門檻 3" in 內容
    assert "run-自己這棵" in 內容
    for 識別 in 別人們:
        assert 識別 in 內容, f"素材要點得出這一次是哪個專案的：缺了 {識別}"
        帳本 = 狀態根目錄() / "專案" / 識別 / "帳本" / f"run-{識別}.jsonl"
        assert str(帳本) in 內容, f"事件帳本要給絕對路徑，唯讀診斷才讀得到：{帳本}"


def _略過那一行(輸出文字: str, *, 雜訊: str) -> str:
    """挑出「略過了幾筆舊帳」那一行。

    先濾掉帶著暫存路徑的行：pytest 拿測試函式的名字當暫存目錄名，
    印出來的素材路徑會整段帶著這支測試的名字——不濾掉的話，
    那條路徑會自己冒充成這一行，而這支測試就永遠是綠的。
    """
    行們 = [行 for 行 in 輸出文字.splitlines() if "略過" in 行 and 雜訊 not in 行]
    if not 行們:
        pytest.fail(f"輸出裡沒有一行講到略過了幾筆舊帳：\n{輸出文字}")
    return 行們[0]


@pytest.mark.parametrize(
    ("有原因幾筆", "該有幾份素材"),
    [(2, 0), (3, 1)],
    ids=["沒達門檻的時候也要出聲", "產得出素材的時候也要出聲"],
)
def test_略過了幾筆沒記原因的舊帳要印在輸出上(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    有原因幾筆: int,
    該有幾份素材: int,
) -> None:
    """守略過的舊帳要**在終端機上**數得出來，不是只寫進素材檔。

    顧問只數得動記了原因的帳，沒記原因的一律略過。略過得無聲無息的話，
    看到「沒有護欄原因達門檻 3」的人會以為那個窗口真的就只有這幾筆——
    而實際上被略過的可能比數進去的還多，結論的方向永遠是「看起來還沒到門檻」。

    達不達門檻都要講：不達門檻那條路根本不產素材，把這行只寫進素材裡
    等於在最需要它的那條路上剛好沒有它。
    """
    專案 = tmp_path / "repo"
    專案.mkdir()
    monkeypatch.chdir(專案)
    目錄 = 已處理目錄(專案)
    此刻 = datetime.now(UTC)
    for 第幾 in range(1, 有原因幾筆 + 1):
        _落一筆(目錄, f"run-有原因-{第幾}", 此刻 - timedelta(hours=第幾), "touched-tests")
    for 第幾 in range(1, 6):
        _落一筆(目錄, f"run-舊帳-{第幾}", 此刻 - timedelta(hours=第幾), None)

    碼 = 命令列.主程式(["--根目錄", str(專案), "顧問", "--門檻", "3", "--窗口小時", "24"])

    輸出 = capsys.readouterr()
    合起來 = 輸出.out + 輸出.err
    assert 碼 == 0, 合起來
    素材們 = sorted(建專案執行脈絡(專案).顧問.glob("*.md"))
    assert len(素材們) == 該有幾份素材, f"這組資料該產出 {該有幾份素材} 份素材，實際 {素材們}"
    那一行 = _略過那一行(合起來, 雜訊=str(tmp_path))
    assert re.search(r"\b5 筆", 那一行), f"略過了 5 筆沒記原因的舊帳，數字要對得上：{那一行}"
    assert "原因" in 那一行, f"要講清楚略過的是「沒記原因」的帳，不是隨便略過了什麼：{那一行}"


@pytest.mark.skipif(os.geteuid() == 0, reason="root 讀得動 0o000 的目錄，這條驗不了")
def test_帳本目錄讀不到回3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """守「看不到」不准長得像「沒東西可看」：帳讀不動是結果未知，回 3。"""
    專案 = tmp_path / "repo"
    專案.mkdir()
    monkeypatch.chdir(專案)
    _造三筆同原因(專案, "touched-tests")
    帳根 = 狀態根目錄() / "專案"
    帳根.chmod(0o000)
    try:
        碼 = 命令列.主程式(["--根目錄", str(專案), "顧問"])
    finally:
        帳根.chmod(0o755)

    assert 碼 == 3, "讀不到帳卻回 0，等於告訴上游『今天沒有重覆』"


@pytest.mark.skipif(os.geteuid() == 0, reason="root 讀得動 0o000 的目錄，這條驗不了")
def test_別的專案的帳讀不動時也回3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """守「數得完整」才准下結論：顧問是跨專案數的，少數到一個專案就答不出次數。

    顧問問的是「這個原因在**全部**派工樹上撞了幾次」。任何一個專案的成果帳
    列不動，這個數字就是未知——這時候回 0 等於拿著一份少算過的帳去說
    「就這幾筆」，而少算的方向永遠是「看起來還沒到門檻」。
    """
    專案 = tmp_path / "repo"
    專案.mkdir()
    monkeypatch.chdir(專案)
    _造三筆同原因(專案, "touched-tests")
    別人的帳 = 狀態根目錄() / "專案" / "別的派工樹-0000" / "已處理"
    _落一筆(別人的帳, "run-丁", datetime.now(UTC) - timedelta(hours=4), "touched-tests")
    別人的帳.chmod(0o000)
    try:
        碼 = 命令列.主程式(["--根目錄", str(專案), "顧問", "--門檻", "3", "--窗口小時", "24"])
    finally:
        別人的帳.chmod(0o755)

    assert 碼 == 3, "有一個專案的帳列不動，次數就是未知，不准當成『數完了』"

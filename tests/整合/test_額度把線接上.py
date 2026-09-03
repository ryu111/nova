"""額度那條線的**終點**：命令列有沒有真的去讀迴圈與收件匣寫下來的那幾格。

`結束代碼.額度`／`結束.不早於`（22a-1）與 `收件單.起點`／`收件.等重置的`（22a-2）
已經是機器讀得到的欄位了，但欄位有值不等於有人在讀。這個檔守的是三個關節，
少任何一個，整條線就安靜地退回「撞牆之後 72 分鐘沒有任何機制會動」，
而且**退回去的樣子看起來還是有做**（票在、欄位在、狀態檔在）：

1. 撞到上游額度那一輪要排出一張**帶著起點與不早於**的接續票，
   時刻讀不出來就**不排、留給人**——不准猜一個時刻。
2. 重置還沒到就醒來，看到「有票在等重置」要是它自己的狀態（`waiting`），
   **不是空收件匣**——壓成空匣就會每次醒來另生一張新票去撞同一個額度。
3. 時間到了要從**票上那一階**接續，不是從頭再跑一次測試階。

外加一條分流：額度沿用退出碼 4，但**不准冒充護欄**。護欄是「nova 自己設的上限
擋下來了，放寬與否是人的決定」；上游額度沒有上限可放寬，人沒有決定要下。

**票都從真的 `nova 跑` 自己長出來**：測試自己呼叫 `接著排(起點=…, 不早於=…)`
的話，生產路徑一格都沒傳也照樣全綠——缺的正是那一段接線，不是收件匣的簽章。
"""

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nova.載體.命令列 import 主程式
from nova.迴圈 import 角色提示

做假CLI型 = Callable[..., tuple[Path, Path]]

#: 走真命令列那幾支用的執行檔與退出碼。**額度沿用 4，不造第五個碼。**
nova執行檔 = Path(sys.executable).parent / "nova"
護欄碼, 放行碼 = 4, 0
#: `claude_quota.txt` 那句 `resets 4:40pm (Asia/Taipei)` ＝ 08:40Z。
#: 時區在原文字串裡，所以這個期望值跟跑測試那台機器的時區無關。
重置的時分 = "08:40:00+00:00"
#: 早就過去的時刻。到期後那一支要走「時間門已經開了」那條路，而真時鐘算出來的
#: 重置時戳必定在未來——所以測試把 CLI 排出來的票**只改時刻**，不手造整張票。
早就到了的ISO = "2020-01-01T00:00:00+00:00"


@pytest.fixture
def 佈景(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """狀態根與專案目錄。`XDG_STATE_HOME` 一起設，行程內那一段才看同一份狀態。"""
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(狀態))
    return 狀態, 專案


def _跑(*參數: str, 狀態: Path, 在: Path) -> subprocess.CompletedProcess[str]:
    """走真的 `nova`。

    **落票那一段不能 `主程式([...])` 行程內叫**：那條路上有幾格直接讀 `sys.argv`
    （`_派工該擋的理由`、`_背景起一條線`），pytest 的 argv 會讓它在第一道門
    就回 2，測到的是別的東西。
    """
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )


def _敲一次(執行檔: Path, *, 狀態: Path, 專案: Path) -> subprocess.CompletedProcess[str]:
    """`nova 跑`：它自己會把題目落成收件檔再收下來，所以票是**產品排出來的**。"""
    return _跑(
        "跑",
        "把某件事做完",
        "--用",
        "claude",
        "--審查用",
        "codex",
        "--執行檔",
        str(執行檔),
        "--最多步數",
        "1",
        "--判準",
        "true",
        狀態=狀態,
        在=專案,
    )


def _醒一次(執行檔: Path, *, 專案: Path, 起點: str = "test") -> int:
    """排程醒來走的那一條——`工作流 --從收件匣`，沒有別條路。**行程內叫，不開子行程。**

    醒來這一側沒有直接讀 `sys.argv` 的格子（讀的那幾格都在落票那一側，見 `_跑`），
    所以 `主程式([...])` 走的是同一條路。行程內走還有一個非走不可的理由：
    「收下一件回 None 的時候先問有沒有票在等重置」那一格，只有在行程內跑
    才量得到它有沒有被繞過——把它丟進子行程，就得叫每一把刀的子行程都去付
    coverage 的啟動成本，那是拿別票的秒數來買這一票的能見度。

    `--起點 test` 固定給：接續票上寫著哪一階，要贏過這個旗標。
    """
    return 主程式(
        [
            "工作流",
            "--從收件匣",
            "--工作目錄",
            str(專案),
            "--用",
            "claude",
            "--審查用",
            "codex",
            "--起點",
            起點,
            "--執行檔",
            str(執行檔),
            "--最多步數",
            "1",
            "--判準",
            "true",
        ]
    )


def _本機的時分(ISO時戳: str) -> str:
    """那個時刻在**跑測試這台機器**上是幾點幾分。

    人讀的那一句要用本機時間：看到 `16:40` 才知道要不要等，
    看到 `2026-09-03T08:40:00+00:00` 得先自己換算一次時區。
    """
    return datetime.fromisoformat(ISO時戳).astimezone().strftime("%H:%M")


def _唯一的(狀態: Path, 相對: str) -> Path:
    """這個專案的那一份（收件匣／狀態檔／成果帳）。專案目錄名帶雜湊，所以用 glob。"""
    return next((狀態 / "nova" / "專案").glob(f"*/{相對}"))


def _等著的(狀態: Path) -> list[Path]:
    """收件匣**根目錄**躺著的票：等重置的那張就在這裡，不在 `處理中/`。"""
    return sorted(路 for 路 in _唯一的(狀態, "收件").iterdir() if 路.is_file())


def _成果帳(狀態: Path) -> dict[str, object]:
    帳: dict[str, object] = json.loads(_唯一的(狀態, "已處理/*.json").read_text(encoding="utf-8"))
    return 帳


def _現況(狀態: Path) -> dict[str, object]:
    現況: dict[str, object] = json.loads(_唯一的(狀態, "狀態.json").read_text(encoding="utf-8"))
    return 現況


def _換掉那句話(原檔: Path, 落點: Path, 新的一句: str) -> Path:
    """拿同一個信封、只換 `result` 那句話——形狀一模一樣，只有時間讀不出來。"""
    信封 = json.loads(原檔.read_text(encoding="utf-8"))
    信封["result"] = 新的一句
    落點.write_text(json.dumps(信封, ensure_ascii=False), encoding="utf-8")
    return 落點


def test_收成額度的線退出碼四狀態是等重置而且醒來不會另生新票(
    佈景: tuple[Path, Path], 做假CLI: 做假CLI型, capsys: pytest.CaptureFixture[str]
) -> None:
    """撞到上游額度那一輪要**留下一張等重置的票**，而重置前醒來看得懂它。

    這一支釘住同一條因果鏈上的四件事，斷任何一節那 72 分鐘就回來：

    1. 退出碼 4 ＋ 成果帳 `outcome=quota` ＋ **沒有** `guardrail_reason`：
       外圈看得出「不是壞了、不用人」，而且不是「nova 自己的上限擋下來了」。
       `nova 線` 那一行同理——印成護欄會把人推去翻 nova 的上限設定，
       那裡沒有東西可調。
    2. 狀態檔的 `resume_not_before`：人與未來的掃描器共用同一個時刻；
       同一份狀態檔上給人看的那一句話講的是**本機時間**（機器讀的那一格才是 UTC）。
    3. 收件匣裡**剛好一張**接續票，標記帶起點／不早於／額度等待，
       而且 `輪次` 沒加一（額度不吃「題目可能卡住」那個計數器）。
    4. 重置前醒來：**票留在原地、不准另生一張新票**，這一輪的收場是 `waiting`。
    """
    狀態, 專案 = 佈景
    執行檔, _紀錄 = 做假CLI("claude", "claude_quota.txt")

    跑完 = _敲一次(執行檔, 狀態=狀態, 專案=專案)

    assert 跑完.returncode == 護欄碼, (
        f"撞到上游額度收在退出碼 {跑完.returncode}——1 是「東西壞了、人來修」，"
        f"然後沒有人來：{跑完.stderr[-500:]}"
    )
    帳 = _成果帳(狀態)
    assert 帳["outcome"] == "quota", f"成果帳上分不出額度就沒人查得出那天發生什麼事：{帳}"
    assert 帳["exit_code"] == 護欄碼
    assert 帳.get("guardrail_reason") is None, (
        "額度那一輪沒有護欄擋過任何東西，「是哪一種護欄」那一格就得整格不出現——"
        f"填了字，下游「有 guardrail_reason 就是護欄」的判斷全都會跟著說錯：{帳}"
    )

    現況 = _現況(狀態)
    不早於 = str(現況.get("resume_not_before", ""))
    assert 不早於.endswith(重置的時分), (
        f"`resets 4:40pm (Asia/Taipei)` ＝ 08:40Z，狀態檔寫的是 {不早於!r}：{現況}"
    )
    assert datetime.fromisoformat(不早於) > datetime.now(UTC), (
        "已過的時刻要推到隔天，不然下一次醒來就白撞一次"
    )

    理由 = str(現況.get("last_wake_reason", ""))
    assert "已排回收件匣等重置" in 理由, f"人翻狀態檔要看得出這一輪把事情排回去了：{現況}"
    assert _本機的時分(不早於) in 理由, (
        f"那一句話是給人看的，要寫他手錶上的 {_本機的時分(不早於)}：{理由!r}"
    )
    assert 不早於 not in 理由, (
        "機器讀的 UTC 時戳原封不動貼進人讀的那句話，等於要人自己換算時區——"
        f"`resume_not_before` 那一格已經是給機器的了：{理由!r}"
    )

    票們 = _等著的(狀態)
    assert len(票們) == 1, f"額度那輪要自己排回收件匣，剛好一張：{票們}"
    標記 = 票們[0].read_text(encoding="utf-8")
    for 該有的 in ("起點=test", f"不早於={不早於}", "額度等待=1", "輪次=1"):
        assert 該有的 in 標記, f"接續票的標記少了 {該有的}：\n{標記}"
    assert "上游額度上限" in 標記, (
        f"前情寫「撞到上限」會被實作員讀成 nova 自己的預算停，然後從頭再做一次：\n{標記}"
    )

    線 = _跑("線", 狀態=狀態, 在=專案)
    那一行 = next((行 for 行 in 線.stdout.splitlines() if "上一次怎麼收的" in 行), "")
    assert 那一行, f"`nova 線` 沒印出這條線上一次怎麼收的：\n{線.stdout}\n{線.stderr[-300:]}"
    assert "額度用完，等重置" in 那一行, (
        f"那一行要看得出「這條線是等重置，不是壞了、也不用改判準」：{那一行}"
    )
    assert "護欄" not in 那一行, (
        f"上游的窗時間到自己開，沒有上限可放寬——印成護欄是把人帶去沒有東西可調的地方：{那一行}"
    )

    碼 = _醒一次(執行檔, 專案=專案)
    醒的輸出 = capsys.readouterr()

    assert 碼 == 放行碼, f"有票在等重置不是錯誤（退出碼 {碼}）：{醒的輸出.err[-400:]}"
    assert _等著的(狀態) == 票們, (
        "重置前醒來把等重置當成「收件匣是空的」→ 從規格對照又長一張票，"
        f"下次拿新票去撞同一個額度：{_等著的(狀態)}"
    )
    assert "等重置" in 醒的輸出.out + 醒的輸出.err, (
        f"人看到票躺在那裡要知道它在等時鐘，不是卡住：{醒的輸出.out}\n{醒的輸出.err[-400:]}"
    )
    醒完 = _現況(狀態)
    assert 醒完["last_wake_outcome"] == "waiting", (
        f"「有票在等額度重置」是自己的狀態，不准跟空收件匣壓成同一個：{醒完}"
    )


def test_到期後從原階段接續而不是從頭來(佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
    """時間到了要接的是**票上寫的那一階**，不是命令列給的起點。

    等對了時間卻接錯了階段，代價跟沒等一樣：上一輪已經付過錢的實作階被丟掉、
    測試還會被重寫一次。所以這裡故意用 `--起點 test` 醒來，票上寫的是 `impl`——
    讀票的那條路要贏過旗標預設。

    票由真的 `nova 跑` 排出來，測試只改兩格：停在哪一階（假 CLI 決定不了）、
    以及把時間門推成已開（真時鐘算出來的重置時刻永遠在未來）。
    **醒來那一段走行程內的 `主程式([...])`**：接續這條路的判斷就在行程內，
    不必為了看見它去動別把刀的環境。
    """
    狀態, 專案 = 佈景
    撞牆的, _ = 做假CLI("claude", "claude_quota.txt")

    撞一次 = _敲一次(撞牆的, 狀態=狀態, 專案=專案)
    assert 撞一次.returncode == 護欄碼, f"前提：這一支要的是額度那條路：{撞一次.stderr[-400:]}"

    票們 = _等著的(狀態)
    assert len(票們) == 1, f"要有一張 CLI 自己排出來的接續票才有東西可接：{票們}"
    原本的 = 票們[0].read_text(encoding="utf-8")
    改過的, 換掉起點 = re.subn(r"起點=[^\s>]+", "起點=impl", 原本的)
    改過的, 換掉不早於 = re.subn(r"不早於=[^\s>]+", f"不早於={早就到了的ISO}", 改過的)
    assert (換掉起點, 換掉不早於) == (1, 1), (
        f"接續票上沒有 `起點`／`不早於` 可改——那兩格是這條路的載體：\n{原本的}"
    )
    票們[0].write_text(改過的, encoding="utf-8")

    好好的, 紀錄 = 做假CLI("claude", "claude_ok.json")
    碼 = _醒一次(好好的, 專案=專案)

    assert 紀錄.exists(), f"時間到了卻沒有叫過任何一次模型（退出碼 {碼}）"
    提示 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"][-1]
    assert 角色提示.實作員身分 in 提示, (
        f"到期後接的不是停下來的那一階——票上的 `起點` 沒被讀：\n{提示[:400]}"
    )
    assert "最少的程式碼讓它綠" in 提示, "接續後的階段標題仍應是實作階，不是測試階開場"
    assert 角色提示.測試員 not in 提示, "從 test 重跑＝上一輪的 impl 白付一次錢，測試還會被重寫"
    assert "上游額度上限" in 提示, (
        "前情要講清楚上一輪是撞到**上游**的額度，不是 nova 自己的預算停——"
        "寫成後者，實作員會把已經做完的再做一次"
    )


def test_讀不出重置時間那件要留給人不准當成處理完(
    佈景: tuple[Path, Path], tmp_path: Path, 做假CLI: 做假CLI型
) -> None:
    """重置時刻讀不出來就**不排接續票、也不准把那件收成處理完**。

    不猜時間只答了一半：猜早了再撞一次、再燒一次錢，猜晚了那條線整晚躺著，
    所以不排是對的。但沒有接續票就代表**沒有人會再來接**——這時候把當初丟進來的
    那張請求搬進 `已處理/`，nova 等於宣稱這件做完了：收件匣空的、佇列空的，
    而狀態檔那句話下一次醒來就被整檔蓋掉。那件事得留在看得見的地方，
    理由也要落在成果帳上（狀態檔活不過下一次醒來）。
    """
    狀態, 專案 = 佈景
    實錄 = Path(__file__).resolve().parent / "實錄" / "claude_quota.txt"
    改過的 = _換掉那句話(
        實錄, tmp_path / "說不清楚幾點.txt", "You've hit your session limit · resets soon"
    )
    執行檔, _紀錄 = 做假CLI("claude", str(改過的))

    跑完 = _敲一次(執行檔, 狀態=狀態, 專案=專案)

    assert 跑完.returncode == 護欄碼, f"前提：這一支要走額度那條路：{跑完.stderr[-400:]}"
    帳 = _成果帳(狀態)
    assert 帳["outcome"] == "quota", f"前提：這一輪要收成額度：{帳}"
    assert _等著的(狀態) == [], f"讀不出重置時間卻還是排了一張接續票＝猜了一個時刻：{_等著的(狀態)}"
    assert "要你看一下" in str(帳.get("skip_reason") or ""), (
        "沒排票的理由只寫進 15 分鐘就被蓋掉的狀態檔、成果帳上一個字都沒有——"
        f"人隔天翻帳只看到一個 quota，不知道它在等人不是等時鐘：{帳}"
    )

    收件匣 = _唯一的(狀態, "收件")
    assert sorted(路.name for 路 in (收件匣 / "處理中").glob("*")), (
        "沒排接續票就沒有人會再來接這件，而當初丟進來的那句話已經不在 `處理中/`——"
        f"收件匣空的、佇列空的，看起來就像做完了：{sorted(收件匣.iterdir())}"
    )
    assert not list((收件匣.parent / "已處理").glob("*.收件")), (
        "把請求搬進 `已處理/` 就是宣稱這件處理完了——這一輪一步都沒做完，"
        "只是上游的窗關著而且連幾點開都讀不出來"
    )

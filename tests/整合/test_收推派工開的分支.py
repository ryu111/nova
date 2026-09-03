"""`派工` 開的樹跟 `收` 推的東西必須是同一個形狀：一條有名字的分支。

住整合層不住單元層：這裡真的 fork git、真的開 worktree、真的推進一個本地
bare repo 當 origin。墊片測得出「參數有沒有傳對」，測不出「推完之後 origin 上
到底多了什麼 ref」——而這一格死掉的就是最後那一步。

死過一次的形狀（42d695）：`派工` 開的樹全是 detached、`收` 推的是 `HEAD`，git 回
`The destination you provided is not a full refname`——閘全綠、commit 成功，
收尾在最後一步掉下去，整套閘白跑。所以這裡釘五件事：

1. `派工` 這條真的接線：一趟 `nova 派工` 跑完，開出來的樹當場就掛在
   `nova/<UTC 時戳>-<票末六碼>` 上，而且全 ASCII——票標題那段中文不進分支名，
   因為 repo 是 public、分支名會進 URL。
2. `收` 推的是完整 refspec `HEAD:refs/heads/<分支>`，origin 上真的長出那個 ref。
3. **相同分支名**開第二棵樹要撞——`worktree add -b` 撞名正是「一條分支變兩棵樹」
   該被擋下的地方；不做 `-B`、不加後綴繞過，也不准退回 detached。
   （「透過 `派工` 撞到相同分支名」歸 45129：搶原票之後檔名不變、六碼才相同。）
4. 對一棵 detached 的樹跑 `收`：退出碼 1、**一次 push 都不准發**，訊息說「這棵樹
   不是派工開的形狀」。分支是在 commit 之前就問的，所以停下來的時候現場還沒被動過；
   不猜分支名，也不准用 `HEAD:refs/heads/HEAD` 那種「讓 git 不抱怨」的寫法。
5. 「問不出分支」**不是** detached：`git symbolic-ref` 沒問成（實測壞路徑回 128）
   時同樣停在 1、同樣不推，但不准套第 4 條那句話——要把 git 自己的抱怨交出去。
   不然人拿到的建議是「這棵樹請用 nova 派工 重開」，而樹好好掛在分支上，
   壞的是別的東西，重開一棵一樣壞。
"""

import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from nova.契約.退出碼 import 放行, 閘紅
from nova.載體 import 命令列
from nova.載體.命令 import 收 as 收模組
from nova.載體.命令列 import 主程式
from nova.載體.工作樹 import 開一個工作樹
from nova.載體.收件 import 收件目錄, 處理中目錄

#: 形狀來自 `派工`：時戳取自收件檔名（`收件.py:262`），六碼是同一個檔名尾的亂碼。
#: 全 ASCII 是硬要求——repo 是 public，分支名會進 URL，票標題的中文不進來。
分支名 = "nova/20260902T041530Z-e023f9"

#: 假 git 在「答不出分支」模式下吐的那句話。真的 git 這時吐的是英文 fatal，
#: 這裡刻意換成一句認得出來的字：測試要釘的是**這句話有沒有被端到人面前**。
問不出時git的抱怨 = "fatal: 假 git 今天答不出 HEAD 是哪條 ref"

#: 假 git 在「收不掉樹」模式下吐的那句話。真的 git 這時吐的是英文（樹髒、被佔用
#: 之類），這裡同樣換成認得出來的字。
收不掉樹時git的抱怨 = "fatal: 假 git 今天收不掉這棵樹"


def _跑git(工作目錄: Path, *參數: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603, S607 —— 測試自己組的 git 指令
        ["git", *參數], cwd=工作目錄, capture_output=True, text=True, check=False
    )


def _造假gh與記錄用git(測具: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """PATH 前面擺一個記錄 argv 的 `git`（委派給真的 git）與一個什麼都答應的 `gh`。

    git 一定要委派真的：這一支測的是「推完 origin 上有什麼」，拿假 git 自問自答
    就等於沒測。gh 則不能是真的——測試不准碰 GitHub。
    """
    真git = shutil.which("git")
    assert 真git, "沒有 git 就跑不了這一支整合測試"
    執行檔目錄 = 測具 / "假執行檔"
    執行檔目錄.mkdir(parents=True)
    紀錄 = 測具 / "收尾指令.jsonl"

    共同開頭 = f"""#!{sys.executable}
import json
import os
import pathlib
import sys
with open(os.environ['NOVA_收推分支紀錄'], 'a', encoding='utf-8') as 檔:
    json.dump(
        {{
            '程式': pathlib.Path(sys.argv[0]).name,
            'argv': sys.argv[1:],
            'cwd': os.getcwd(),
        }},
        檔,
        ensure_ascii=False,
    )
    檔.write("\\n")
"""
    # 開關擺在環境變數上，這樣「答不出分支」那一支跟其餘幾支共用同一個假 git：
    # 攔的是**前綴**，`--short HEAD` 與 `-q --short HEAD` 兩種寫法都攔得到。
    答不出分支 = (
        "if sys.argv[1:2] == ['symbolic-ref'] and os.environ.get('NOVA_收推答不出分支'):\n"
        f"    sys.stderr.write({問不出時git的抱怨!r} + '\\n')\n"
        "    sys.exit(128)\n"
    )
    # 同一個開關手法：只攔 `worktree remove` 這一道，其餘照樣委派真的 git——
    # 「收不掉樹」那一支要看的是 merge 之後的收場，前面每一步都得是真的。
    收不掉樹 = (
        "if sys.argv[1:3] == ['worktree', 'remove'] and os.environ.get('NOVA_收推收不掉樹'):\n"
        f"    sys.stderr.write({收不掉樹時git的抱怨!r} + '\\n')\n"
        "    sys.exit(1)\n"
    )
    (執行檔目錄 / "git").write_text(
        f"{共同開頭}{答不出分支}{收不掉樹}os.execv({真git!r}, [{真git!r}, *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    (執行檔目錄 / "gh").write_text(共同開頭, encoding="utf-8")
    for 名稱 in ("git", "gh"):
        路徑 = 執行檔目錄 / 名稱
        路徑.chmod(路徑.stat().st_mode | stat.S_IEXEC)

    monkeypatch.setenv("NOVA_收推分支紀錄", str(紀錄))
    monkeypatch.setenv("PATH", os.pathsep.join((str(執行檔目錄), os.environ.get("PATH", ""))))
    return 紀錄


def _造專案與origin(暫存根: Path) -> tuple[Path, Path, str]:
    """造一個 bare repo 當 origin、一個接上它的專案，回傳（專案、origin、起點 sha）。"""
    origin = 暫存根 / "origin.git"
    assert _跑git(暫存根, "init", "-q", "--bare", "-b", "main", str(origin)).returncode == 0

    專案 = 暫存根 / "專案"
    專案.mkdir()
    for 指令 in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "測試@例子"),
        ("config", "user.name", "測試"),
        ("config", "commit.gpgsign", "false"),
        ("remote", "add", "origin", str(origin)),
    ):
        assert _跑git(專案, *指令).returncode == 0
    (專案 / "共用.txt").write_text("第一版\n", encoding="utf-8")
    assert _跑git(專案, "add", "-A").returncode == 0
    assert _跑git(專案, "commit", "-q", "-m", "第一版").returncode == 0
    assert _跑git(專案, "push", "-q", "origin", "main").returncode == 0
    return 專案, origin, _跑git(專案, "rev-parse", "HEAD").stdout.strip()


def _讀呼叫(紀錄: Path) -> list[tuple[str, list[str]]]:
    if not 紀錄.exists():
        return []
    呼叫: list[tuple[str, list[str]]] = []
    for 行 in 紀錄.read_text(encoding="utf-8").splitlines():
        資料 = cast(dict[str, object], json.loads(行))
        呼叫.append((str(資料["程式"]), [str(值) for 值 in cast(list[object], 資料["argv"])]))
    return 呼叫


def _讀呼叫含cwd(紀錄: Path) -> list[tuple[str, list[str], Path]]:
    """跟 `_讀呼叫` 同一份紀錄，但連每一道指令**是站在哪裡跑的**一起讀出來。

    argv 說得出「跑了什麼」，說不出「在哪裡跑」，而 11b 死掉的那一格正是後者：
    merge 之後 `根` 隨時會不見，站在那裡發指令的東西全都會跟著它一起掉下去。
    """
    if not 紀錄.exists():
        return []
    呼叫: list[tuple[str, list[str], Path]] = []
    for 行 in 紀錄.read_text(encoding="utf-8").splitlines():
        資料 = cast(dict[str, object], json.loads(行))
        呼叫.append(
            (
                str(資料["程式"]),
                [str(值) for 值 in cast(list[object], 資料["argv"])],
                Path(str(資料["cwd"])),
            )
        )
    return 呼叫


def _推的那幾次(紀錄: Path) -> list[list[str]]:
    return [參數 for 名稱, 參數 in _讀呼叫(紀錄) if 名稱 == "git" and 參數[:1] == ["push"]]


def _斷言有gh指令(紀錄: Path, *開頭: str) -> list[str]:
    """斷言假 `gh` 收到過以 `開頭` 起首的一道指令，並回傳那次的 argv。"""
    for 名稱, 參數 in _讀呼叫(紀錄):
        if 名稱 == "gh" and 參數[: len(開頭)] == list(開頭):
            return 參數
    訊息 = f"找不到 gh {' '.join(開頭)}：{_讀呼叫(紀錄)}"
    raise AssertionError(訊息)


def _origin上的分支(origin: Path) -> set[str]:
    輸出 = _跑git(origin, "for-each-ref", "--format=%(refname)", "refs/heads/").stdout
    return {行.strip() for 行 in 輸出.splitlines() if 行.strip()}


def _收尾參數(工作目錄: Path) -> list[str]:
    return ["收", "--工作目錄", str(工作目錄), "--不記帳", "--訊息", "測試收尾"]


@pytest.fixture
def 閘放行(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """把提交閘設成放行：這一支釘的是閘之後的那一步，不是閘本身。"""

    def 設定() -> None:
        monkeypatch.setattr(收模組, "_收尾閘", lambda *_: 放行)

    return 設定


def test_派工真的把樹開在ASCII分支上(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """走真的 `nova 派工`（不是直呼 `開一個工作樹`）：開出來的樹當場掛在分支上。

    直呼 primitive 的測試證明不了接線：`命令列.py` 那一行把分支名傳錯，
    primitive 那幾支照樣全綠。所以這一支從命令列這端進去，只擋掉「真的在背景
    叫一顆模型起來」那一步。

    分支名是 `nova/<線名頭段>-<線名尾段>`：線名（＝收件檔名）中間那幾段是票
    標題，含中文；分支名不准含中文，repo 是 public、分支名會進 URL。
    """
    專案, _origin, _起點commit = _造專案與origin(tmp_path)
    票檔 = tmp_path / "票.md"
    票檔.write_text("收尾推不動派工開的樹\n", encoding="utf-8")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    發射過: list[tuple[list[str], dict[str, object]]] = []

    def 記下來不發射(參: list[str], **其餘: object) -> None:
        發射過.append((list(參), dict(其餘)))

    monkeypatch.setattr(命令列, "發射背景程序", 記下來不發射)
    參數 = [
        "派工",
        str(票檔),
        "--工作目錄",
        str(專案),
        "--判準",
        "true",
        "--最多步數",
        "0",
    ]
    # `_派工該擋的理由` 靠 `sys.argv` 認出「這是從命令列派的」，背景那條靠同一份重發。
    monkeypatch.setattr(sys, "argv", ["nova", *參數])

    碼 = 主程式(參數)

    輸出 = capsys.readouterr()
    assert 碼 == 放行, f"派工沒派出去：{輸出.err}"
    assert 發射過, "背景那條線沒發射（樁沒被呼叫，這一支就沒走到接線那一步）"
    線名 = next(
        行.split("線名：", maxsplit=1)[1].strip() for 行 in 輸出.out.splitlines() if "線名：" in 行
    )

    在處理中 = sorted(處理中目錄(收件目錄(專案)).glob("*.md"))
    assert len(在處理中) == 1, f"處理中/ 不是恰好一件：{在處理中}"
    assert 在處理中[0].name.endswith(f"-{線名}.md"), (
        f"處理中那份不是這條線的票（線名 {線名}）：{在處理中[0].name}"
    )

    樹 = 專案.parent / f"nova-wt-{線名}"
    assert 發射過[0][1]["在哪跑"] == 樹, (
        f"背景那條線沒被派進自己的工作樹（它會在主工作區裡跑）：{發射過[0][1]}"
    )
    掛在 = _跑git(樹, "symbolic-ref", "--short", "HEAD").stdout.strip()
    各段 = 線名.split("-")
    assert 掛在 == f"nova/{各段[0]}-{各段[-1]}", (
        f"派工開的樹沒掛在 `nova/<時戳>-<六碼>` 上（線名 {線名}）：{掛在!r}"
    )
    assert 掛在.isascii(), f"分支名帶了非 ASCII，它會進 PR 的 URL：{掛在!r}"
    assert not 線名.isascii(), "線名本來就含票標題的中文；它若變成全 ASCII，這支就白測了"


def test_收把派工開的分支推成完整refspec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """派工形狀的樹 → 在裡面改一次 → `收` 推得上去，origin 真的多了那個 ref。

    這一支只釘 push 那一段的形狀（完整 refspec、origin 上真的長出東西）；
    收場（樹收掉、分支刪掉、退出碼 0）歸下面那一支整趟的測試。
    """
    專案, origin, 起點commit = _造專案與origin(tmp_path)
    紀錄 = _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    樹 = 開一個工作樹(
        專案,
        落點=tmp_path / f"nova-wt-{分支名.rsplit('/', maxsplit=1)[-1]}",
        起點commit=起點commit,
        分支=分支名,
    )
    (樹 / "分支的產出.txt").write_text("這一條線做完的事\n", encoding="utf-8")
    閘放行()

    碼 = 主程式(_收尾參數(樹))

    推 = _推的那幾次(紀錄)
    assert 推 == [["push", "--set-upstream", "origin", f"HEAD:refs/heads/{分支名}"]], (
        f"push 要帶完整 refspec，分支名從 `git symbolic-ref --short HEAD` 讀：{推}"
    )
    assert f"refs/heads/{分支名}" in _origin上的分支(origin), (
        "origin 上沒長出這條分支——收尾到不了終點，前面整套閘白跑"
    )
    推上去的commit = _跑git(origin, "rev-parse", f"refs/heads/{分支名}").stdout.strip()
    assert 推上去的commit != 起點commit, "`收` 應該先 commit 再 push，origin 上還停在起點"
    assert (
        _跑git(origin, "show", f"refs/heads/{分支名}:分支的產出.txt").stdout == "這一條線做完的事\n"
    ), "origin 上那條分支不是這棵樹剛 commit 的東西"

    輸出 = capsys.readouterr()
    assert 碼 == 放行, f"閘綠、推成功、PR 也合併了，這一趟該收 0：收到 {碼}\n{輸出.err}"


def test_收在派工開的樹上整趟走完要收0(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """在派工開的樹上跑 `收`：合併之後**現場要收乾淨**——樹不在、本地分支不在、收 0。

    「收 0」的意思在派工樹上包含兩件事，缺一件都是假綠：那棵樹不在了、它掛的
    本地分支也不在了。留著樹就是留著一棵沒人會再進去的目錄，留著分支則會讓下一次
    同名派工撞在一條沒人用的分支上，而且沒人講得出它是哪一票留的（`docs/負控紀錄/
    0010`）。

    `--delete-branch` 在派工樹上是明確有害的，所以順便釘死 argv：`gh pr merge
    --delete-branch` 會先 `git checkout <base>`，而 base 正被主工作區佔著，linked
    worktree 裡那道 checkout 回 128——**merge 已經做完了才回非零**，`收` 收 1，樹
    與分支照樣留著。遠端那條分支由 repo 的 delete-branch-on-merge 刪，所以派工樹這
    條路只給 `--squash`；主工作區那條路照舊帶 `--delete-branch`（`test_收尾紅線.py`
    的 `test_合併指令一定帶刪除分支旗標` 釘著）。

    gh 是假的（測試不准碰 GitHub），git 是真的：這一支要看的是「跑完之後這個 repo
    上還剩什麼」，拿假 git 自問自答就等於沒測。
    """
    專案, origin, 起點commit = _造專案與origin(tmp_path)
    紀錄 = _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    樹 = 開一個工作樹(
        專案,
        落點=tmp_path / f"nova-wt-{分支名.rsplit('/', maxsplit=1)[-1]}",
        起點commit=起點commit,
        分支=分支名,
    )
    (樹 / "分支的產出.txt").write_text("這一條線做完的事\n", encoding="utf-8")
    閘放行()

    碼 = 主程式(_收尾參數(樹))

    輸出 = capsys.readouterr()
    assert 碼 == 放行, f"閘綠、PR 合併了，收尾卻回 {碼}\n{輸出.out}\n{輸出.err}"
    assert not 樹.exists(), f"PR 合併了、樹還在：這棵樹沒人會再進去，卻要人手動清：{樹}"
    留著的分支 = _跑git(專案, "branch", "--list", 分支名).stdout.strip()
    assert 留著的分支 == "", (
        f"本地分支 {分支名} 還在——下一次同名派工會撞在一條沒人用的分支上：{留著的分支!r}"
    )
    樹清單 = [
        行
        for 行 in _跑git(專案, "worktree", "list", "--porcelain").stdout.splitlines()
        if 行.startswith("worktree ")
    ]
    assert 樹清單 == [f"worktree {專案}"], f"worktree 清單裡還留著派工那棵樹的登記：{樹清單}"

    合併 = _斷言有gh指令(紀錄, "pr", "merge")
    assert "--squash" in 合併, f"合併政策沒變：一律 squash：{合併}"
    assert "--delete-branch" not in 合併, (
        "派工樹上不准帶 `--delete-branch`：gh 會先 checkout base，"
        f"而 base 被主工作區佔著，那道 checkout 回 128 是在 merge 之後才發生的：{合併}"
    )
    assert f"refs/heads/{分支名}" in _origin上的分支(origin), (
        "本地收乾淨了，但 origin 上那條分支根本沒推上去——這一趟白跑"
    )


def test_合併之後每一道指令的cwd只准是主工作區(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """`gh pr merge` 之後，`收` 發出去的每一道指令都只准站在**主工作區**跑。

    merge 之後這棵派工樹隨時會不見（下一步就是 `收掉工作樹`），所以「站在樹裡發
    指令」從那一秒起就是一顆定時炸彈：樹一收掉，那個 cwd 就是一個不存在的 inode，
    後面任何還指著它的東西都會炸——而炸的時候 PR 已經合併、遠端已經動過，`收` 只
    能回非零，人看到非零會再跑一次，那時連 `cd` 都進不去（票 05／07 的接續同一格）。

    「拿掉樹之前站在樹裡跑」跑得動不等於它是對的：`git worktree remove` 收掉自己
    站的那棵樹，git 回 0，但那是**運氣**——收的順序、git 版本、樹裡有沒有別的東西
    佔著，任何一項變了就換成「merge 做完了才回非零、樹與分支留著」，正是 0010 記的
    那個現場。所以這裡不看「這次有沒有成功」，看的是**位置**：合併之後那幾道
    `worktree list`／`worktree remove`／`branch -D` 全部都要從主工作區發出去。
    `收掉工作樹(落點)` 的簽章不必動——它自己已經問得到主工作區在哪。

    argv 由假 CLI 一併記下 cwd（`_讀呼叫含cwd`）：假 gh 收到 `pr merge` 的那一刻
    就是分界線，那之後每一筆的 cwd 都要等於主工作區。
    """
    專案, _origin, 起點commit = _造專案與origin(tmp_path)
    紀錄 = _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    樹 = 開一個工作樹(
        專案,
        落點=tmp_path / f"nova-wt-{分支名.rsplit('/', maxsplit=1)[-1]}",
        起點commit=起點commit,
        分支=分支名,
    )
    (樹 / "分支的產出.txt").write_text("這一條線做完的事\n", encoding="utf-8")
    閘放行()

    碼 = 主程式(_收尾參數(樹))

    輸出 = capsys.readouterr()
    assert 碼 == 放行, f"這一支要看的是合併之後的 cwd，前面得先走到合併：{碼}\n{輸出.err}"
    呼叫 = _讀呼叫含cwd(紀錄)
    合併在第幾筆 = [
        序
        for 序, (名稱, 參數, _) in enumerate(呼叫)
        if 名稱 == "gh" and 參數[:2] == ["pr", "merge"]
    ]
    assert len(合併在第幾筆) == 1, f"`gh pr merge` 該恰好發生一次：{呼叫}"

    站錯地方的 = [
        (名稱, 參數, 位置)
        for 名稱, 參數, 位置 in 呼叫[合併在第幾筆[0] + 1 :]
        if 位置.resolve() != 專案.resolve()
    ]
    assert 站錯地方的 == [], (
        f"合併之後有指令不是站在主工作區 {專案} 跑的，站的是那棵隨時會消失的派工樹：\n"
        + "\n".join(f"  cwd={位置}：{名稱} {' '.join(參數)}" for 名稱, 參數, 位置 in 站錯地方的)
    )


def test_人從樹裡面跑收_收把自己站的cwd刪掉之後照樣收0(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """人真正的跑法是 `cd <樹> && nova 收`：程序自己的 cwd 就在那棵要被收掉的樹裡。

    上面那支整趟的測試是從 pytest 的 cwd 跑的，`--工作目錄` 指進樹裡——收掉樹的
    那一刻，程序自己站的地方沒有消失。人不是這樣跑的：人 `cd` 進去才跑，樹一收掉，
    這個程序的 cwd 就是一個已經不存在的 inode。從那一秒起 `os.getcwd()` 會炸、
    任何拿相對路徑去解的動作會炸、任何沒有明講 cwd 的 subprocess 會炸。

    所以這一格釘的是「merge 之後不准有任何東西依賴 `根`／依賴當下的 cwd」：收場
    每一道指令的 cwd 只准是主工作區。這條路壞掉的樣子特別難查——樹收掉了、分支
    刪掉了、PR 也合併了，事情其實都做完了，卻回一個非零，而人看到非零的第一反應是
    再跑一次 `收`，那時樹已經不在，連 `cd` 都進不去（票 05／07 的接續也踩同一格）。
    """
    專案, _origin, 起點commit = _造專案與origin(tmp_path)
    _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    樹 = 開一個工作樹(
        專案,
        落點=tmp_path / f"nova-wt-{分支名.rsplit('/', maxsplit=1)[-1]}",
        起點commit=起點commit,
        分支=分支名,
    )
    (樹 / "分支的產出.txt").write_text("這一條線做完的事\n", encoding="utf-8")
    閘放行()

    monkeypatch.chdir(樹)
    try:
        碼 = 主程式(_收尾參數(樹))
    finally:
        # 樹已經不在了，這個程序沒有一個活著的 cwd——先站回主工作區再做斷言，
        # 不然紅的會是 pytest 自己的收尾，不是這一支要測的那件事。
        os.chdir(專案)

    輸出 = capsys.readouterr()
    assert 碼 == 放行, (
        f"人站在樹裡跑，收尾把樹收掉之後回了 {碼}：事情做完了卻回非零，"
        f"人只會再跑一次 `收`，而那時連 cd 都進不去\n{輸出.out}\n{輸出.err}"
    )
    assert not 樹.exists(), f"人站在樹裡跑的時候這棵樹就沒收掉：{樹}"
    留著的分支 = _跑git(專案, "branch", "--list", 分支名).stdout.strip()
    assert 留著的分支 == "", f"本地分支 {分支名} 還在：{留著的分支!r}"


def test_派工樹收不掉時停在一並且明講不要重跑merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """PR 合併了、樹卻收不掉：回 1、指名那條分支、明講不要重跑 merge，且不重跑。

    這是這條路上唯一一種「已經動過遠端、卻沒收完」的狀態，訊息要照著它寫：merge
    是冪等不了的那一步（重按只會拿到一句「已經合併過了」），真正沒做完的是清現場
    那一段——所以人要拿到的指示是「清掉樹之後手動刪本地分支 <分支>」，而不是一句
    含糊的失敗。分支名一定要出現在訊息裡：樹沒收掉時本地那條分支還在，沒有名字人
    就不知道要去刪什麼（`docs/負控紀錄/0010`）。

    同時釘死「`gh pr merge` 恰好一次」：收不掉樹不准變成一條會回頭重跑 merge 的
    路。假 git 只攔 `worktree remove` 這一道，其餘全委派真的 git——攔多了，紅的
    原因就不是這一支要測的那件事。
    """
    專案, _origin, 起點commit = _造專案與origin(tmp_path)
    紀錄 = _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    樹 = 開一個工作樹(
        專案,
        落點=tmp_path / f"nova-wt-{分支名.rsplit('/', maxsplit=1)[-1]}",
        起點commit=起點commit,
        分支=分支名,
    )
    (樹 / "分支的產出.txt").write_text("這一條線做完的事\n", encoding="utf-8")
    monkeypatch.setenv("NOVA_收推收不掉樹", "1")
    閘放行()

    碼 = 主程式(_收尾參數(樹))

    輸出 = capsys.readouterr()
    assert 碼 == 閘紅, f"樹沒收掉就不是收乾淨了，不准回 {碼}"
    assert 樹.exists(), "假 git 讓 `worktree remove` 失敗了，樹卻不見了：這一支測的現場沒造出來"
    assert 分支名 in 輸出.err, f"沒指名要手動刪哪條本地分支：{輸出.err!r}"
    assert "不要重跑 merge" in 輸出.err, (
        f"沒擋掉「再按一次 merge」這個直覺反應，而 merge 已經做過了：{輸出.err!r}"
    )
    assert 收不掉樹時git的抱怨 in 輸出.err, f"git 自己的抱怨沒端出來，人查不下去：{輸出.err!r}"
    合併過的次數 = sum(
        1 for 名稱, 參數 in _讀呼叫(紀錄) if 名稱 == "gh" and 參數[:2] == ["pr", "merge"]
    )
    assert 合併過的次數 == 1, f"`gh pr merge` 該恰好發生一次，實際 {合併過的次數} 次"


def test_問不出分支時不准謊報也不准推(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """`git symbolic-ref` 沒問成（rc 128）不等於 HEAD 沒有分支：不准套那句話。

    這棵樹是 `派工` 開的形狀，好端端掛在 `分支名` 上——壞的是查詢本身。把「非放行」
    一律當 detached 的話，人拿到的是一句「這棵樹不是派工開的形狀，請用 nova 派工
    重開」：**照著做會重開一棵一樣壞的樹**，而真正的原因（git 自己那句 fatal）被吞
    在回傳值裡沒人看得到。所以第三態要把 git 的抱怨原樣交出去。

    停下來與不推照樣釘住：診斷變誠實不代表可以開始推。
    """
    專案, origin, 起點commit = _造專案與origin(tmp_path)
    原有分支 = _origin上的分支(origin)
    樹 = 開一個工作樹(專案, 落點=tmp_path / "nova-wt-問不出", 起點commit=起點commit, 分支=分支名)
    (樹 / "分支的產出.txt").write_text("這一條線做完的事\n", encoding="utf-8")
    紀錄 = _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    monkeypatch.setenv("NOVA_收推答不出分支", "1")
    閘放行()

    碼 = 主程式(_收尾參數(樹))

    輸出 = capsys.readouterr()
    訊息 = 輸出.out + 輸出.err
    assert 碼 == 閘紅, f"查分支這一道 git 都壞了還往下走，收到的是 {碼}"
    assert _推的那幾次(紀錄) == [], f"分支都問不出來了還發了 push：{_推的那幾次(紀錄)}"
    assert _origin上的分支(origin) == 原有分支, "origin 被推出了不該存在的分支"
    assert "不是派工開的形狀" not in 訊息, (
        f"這棵樹掛在 {分支名} 上，壞的是查詢；照這句話「用 nova 派工 重開」只會再壞一次：{訊息!r}"
    )
    assert 問不出時git的抱怨 in 訊息, (
        f"git 自己說了原因，`收` 把它吞了——人手上沒有任何線索可以查：{訊息!r}"
    )


def test_相同分支名開第二棵樹要撞名且第一棵不受影響(tmp_path: Path) -> None:
    """一條分支開兩棵樹是壞形狀，`worktree add -b` 撞名正是該擋的地方。

    不做 `-B`、不加後綴、不退回 detached：擋下來之後第一棵樹要毫髮無傷。
    """
    專案, _origin, 起點commit = _造專案與origin(tmp_path)
    第一棵 = 開一個工作樹(專案, 落點=tmp_path / "樹一", 起點commit=起點commit, 分支=分支名)
    (第一棵 / "第一棵的產出.txt").write_text("先來的那條線\n", encoding="utf-8")

    with pytest.raises(OSError, match="開不出工作樹"):
        開一個工作樹(專案, 落點=tmp_path / "樹二", 起點commit=起點commit, 分支=分支名)

    assert not (tmp_path / "樹二").exists(), "撞名之後不該留下半棵樹"
    assert _跑git(第一棵, "symbolic-ref", "--short", "HEAD").stdout.strip() == 分支名, (
        "第一棵樹的分支被第二棵搶走了"
    )
    assert (第一棵 / "第一棵的產出.txt").read_text(encoding="utf-8") == "先來的那條線\n"


def test_對detached的樹跑收_退出碼一且一次push都不發(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, 閘放行: Callable[[], None]
) -> None:
    """HEAD 是 detached 就代表這棵樹不是派工開的形狀：當場收 1，不猜名字、不推。

    分支是在 commit 之前問的，所以停下來的時候現場要一動也沒動：樹裡那個檔案還是
    未追蹤的、HEAD 還停在起點。否則人得從一顆孤兒 commit 上把工作挖回來。
    """
    專案, origin, 起點commit = _造專案與origin(tmp_path)
    原有分支 = _origin上的分支(origin)
    樹 = tmp_path / "野生的樹"
    assert _跑git(專案, "worktree", "add", "--detach", str(樹), 起點commit).returncode == 0
    (樹 / "誰開的都不知道.txt").write_text("手動開的樹\n", encoding="utf-8")
    紀錄 = _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    閘放行()

    碼 = 主程式(_收尾參數(樹))

    assert 碼 == 閘紅, f"detached 的樹要收 1，收到的是 {碼}"
    assert _推的那幾次(紀錄) == [], "detached 的樹一次 push 都不准發，不准讓 git 去擋"
    assert _origin上的分支(origin) == 原有分支, "origin 被推出了不該存在的分支"
    assert _跑git(樹, "rev-parse", "HEAD").stdout.strip() == 起點commit, (
        "分支要在 commit 之前問：停在 detached 上卻已經 commit，工作被埋進孤兒 commit 裡"
    )
    # `-z` 才不會把中文檔名轉成八進位跳脫，斷言看的是檔名本身。
    現場 = [條目 for 條目 in _跑git(樹, "status", "--porcelain", "-z").stdout.split("\0") if 條目]
    assert 現場 == ["?? 誰開的都不知道.txt"], (
        f"現場被動過了——這一趟該在任何 git 寫入之前就停住：{現場}"
    )


def test_對detached的樹跑收_訊息要指出真因(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """收 1 還不夠：訊息要指出真因，不然人看到的是一句 git 的 refname 抱怨。

    測試函式名裡刻意不帶那句話——`tmp_path` 會把函式名放進路徑，而 git 的錯誤
    訊息會把路徑印出來，那樣這支測試會用自己的名字餵飽自己的斷言。
    """
    專案, _origin, 起點commit = _造專案與origin(tmp_path)
    樹 = tmp_path / "野生的樹"
    assert _跑git(專案, "worktree", "add", "--detach", str(樹), 起點commit).returncode == 0
    _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    閘放行()

    主程式(_收尾參數(樹))

    輸出 = capsys.readouterr()
    assert "不是派工開的形狀" in (輸出.out + 輸出.err), (
        f"要說清楚是「這棵樹不是派工開的形狀」，不是丟 git 的 refname 錯給人猜：{輸出}"
    )

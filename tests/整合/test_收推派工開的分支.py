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

from nova.契約.退出碼 import 放行, 未知, 閘紅
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

#: 提交閘在指令紀錄裡的「程式名」。閘不是 PATH 上的執行檔，是 `閘放行` fixture 記
#: 進同一份紀錄的一筆——這樣「閘跑在哪兩道 git 指令之間」才有辦法比。
閘的程式名 = "nova閘"

#: 假 git 在「收不掉樹」模式下吐的那句話。真的 git 這時吐的是英文（樹髒、被佔用
#: 之類），這裡同樣換成認得出來的字。
收不掉樹時git的抱怨 = "fatal: 假 git 今天收不掉這棵樹"

#: 假 gh 在「PR 已經存在」模式（`NOVA_收推已有PR`）下要交出來的那一筆。欄位照
#: `收尾現場._要的欄位` 給齊：少任何一欄，`查收尾現場` 就落未知碼 3，紅的原因
#: 就不是那一支要測的那件事。`headRefOid` 是固定值——這一階問的是「PR 在不在」，
#: 「PR 指著哪顆 SHA」歸鎖 SHA 那張票。
已存在的PR: dict[str, object] = {
    "number": 260,
    "url": "https://example.invalid/nova/pull/260",
    "headRefName": 分支名,
    "headRefOid": "0" * 40,
    "baseRefName": "main",
    "mergeStateStatus": "CLEAN",
}

#: 真的 `gh pr list` 不帶 `--limit` 時只吐 30 筆。假 gh 照這個數字截，測試才問得出
#: 「查詢有沒有指名分支」——這個 repo 上隨時有幾十個開著的 PR，目標那一筆排在別人
#: 後面時，一份不篩分支的清單根本比不到它。
gh清單預設上限 = 30

#: 清單上那些**不是目標**的 PR：欄位齊、分支名各不相同，所以它們每一筆都讀得成，
#: 只是都不掛在 `分支名` 上。滿 30 筆是刻意的——目標那一筆接在它們後面，查詢少了
#: `--head <分支>` 就會落在截斷線外，被讀成「這條分支沒有 PR」而去 `gh pr create`。
清單上的雜訊PR們: list[dict[str, object]] = [
    {
        "number": 100 + 序,
        "url": f"https://example.invalid/nova/pull/{100 + 序}",
        "headRefName": f"nova/20260902T0415{序:02d}Z-aaa{序:03d}",
        "headRefOid": f"{序:040d}",
        "baseRefName": "main",
        "mergeStateStatus": "CLEAN",
    }
    for 序 in range(gh清單預設上限)
]

#: 「這條分支上有沒有 PR」答不出來的那幾種原樣輸出（掛 `NOVA_收推PR清單原樣` 開）。
#: 每一種都**不是**「零筆」：拿它們冒充「沒有 PR」就會多開一個 PR，或在遠端已經
#: 動過的現場上再撞一次 already exists。
沒有PR的空清單 = "[]"
答不出PR的原樣輸出 = {
    # gh 掛掉／被 401 擋下來時就是這副樣子：一個字都沒有。**空輸出不是空清單。**
    "空輸出": "",
    # 半截 JSON（連線中途斷、輸出被截）：讀不成就是讀不成，不准當零筆。
    "壞JSON": '[{"number": 260,',
    # 清單非空，但那一筆讀不成 PR（缺 `headRefName`）：這份清單裡有什麼分支根本
    # 比不出來，所以「這條分支沒有 PR」也證明不了。
    "清單裡混著讀不成PR的項目": '[{"number": 260, "url": "https://example.invalid/260"}]',
    # 同一條分支上比到兩筆：指不出唯一目標，不猜要跟哪一個。
    "同一條分支比到兩筆": json.dumps(
        [已存在的PR, {**已存在的PR, "number": 261}], ensure_ascii=False
    ),
    # 一份合法、非空、每一筆都讀得成的清單，只是上面**一筆都不掛在這條分支上**。
    # 這證明不了「這條分支沒有 PR」：查詢帶了 `--head <分支>` 卻回一堆別條分支的
    # PR，代表這份清單根本沒照分支篩（或被別的東西截過），它答的不是我們問的問題。
    # 真正的「沒有 PR」只有一種長相——**原樣就是空清單**。零筆匹配跟零筆清單不是
    # 同一件事，把前者讀成後者就會在已經開著 PR 的分支上再 `gh pr create` 一次。
    "清單非空但一筆都不掛這條分支": json.dumps(清單上的雜訊PR們, ensure_ascii=False),
}


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
    # 「PR 在不在」是用查的，所以假 gh 一定要答得出 `pr list`／`pr view`：預設答
    # **空清單**（＝沒有 PR，維持既有那條「新建」路徑），掛上 `NOVA_收推已有PR`
    # 才答恰好一筆。空 stdout 不是這裡的預設值——空輸出的語意是「不知道」，
    # 拿它冒充「沒有 PR」正是要被擋掉的那種 fail-open。
    # 「答不出來」那幾種現場：`gh pr list` 原樣吐環境變數裡那串（可以是空字串）並
    # 回 0——真的 gh 掛在 401／輸出被截時就是這樣，退出碼不會替人把話講清楚。
    答不出PR = (
        "if sys.argv[1:3] == ['pr', 'list'] and 'NOVA_收推PR清單原樣' in os.environ:\n"
        "    sys.stdout.write(os.environ['NOVA_收推PR清單原樣'])\n"
        "    sys.exit(0)\n"
    )
    # `pr list` 這一道照真的 gh 的兩個行為走：**吃 `--head` 篩分支**、**不指名
    # `--limit` 就只吐前 30 筆**。清單上永遠先擺滿 30 筆別條分支的 PR，目標那一筆
    # 排在最後——查詢沒篩分支就比不到它。少了這兩個行為，「查詢有沒有指名分支」
    # 這件事在測試裡看不出差別，拿掉篩選照樣全綠。
    查PR = (
        "if sys.argv[1:3] in (['pr', 'list'], ['pr', 'view']):\n"
        f"    雜訊 = {json.dumps(清單上的雜訊PR們, ensure_ascii=False)}\n"
        f"    那筆PR = {json.dumps(已存在的PR, ensure_ascii=False)}\n"
        "    if not os.environ.get('NOVA_收推已有PR'):\n"
        "        那筆PR = None\n"
        "    def 旗標(名稱):\n"
        "        for 序, 段 in enumerate(sys.argv):\n"
        "            if 段 == 名稱 and 序 + 1 < len(sys.argv):\n"
        "                return sys.argv[序 + 1]\n"
        "            if 段.startswith(名稱 + '='):\n"
        "                return 段.split('=', 1)[1]\n"
        "        return None\n"
        "    if sys.argv[2] == 'list':\n"
        "        清單 = [*雜訊, *([那筆PR] if 那筆PR else [])]\n"
        "        要哪條 = 旗標('--head')\n"
        "        if 要哪條 is not None:\n"
        "            清單 = [pr for pr in 清單 if pr['headRefName'] == 要哪條]\n"
        f"        上限 = int(旗標('--limit') or {gh清單預設上限})\n"
        "        json.dump(清單[:上限], sys.stdout, ensure_ascii=False)\n"
        "    elif 那筆PR and sys.argv[3:4] == [str(那筆PR['number'])]:\n"
        "        json.dump(那筆PR, sys.stdout, ensure_ascii=False)\n"
        "    sys.exit(0)\n"
    )
    (執行檔目錄 / "gh").write_text(f"{共同開頭}{答不出PR}{查PR}", encoding="utf-8")
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


def _第一次出現(紀錄: Path, 程式: str, *開頭: str) -> int | None:
    """回傳這道指令**第一次**出現在紀錄裡的序號；沒出現過回 None。

    序號拿來比先後：「fetch 在 push 之前」這種順序關係，只有序號說得出來。
    """
    for 序, (名稱, 參數) in enumerate(_讀呼叫(紀錄)):
        if 名稱 == 程式 and 參數[: len(開頭)] == list(開頭):
            return 序
    return None


def _斷言fetch在push之前(紀錄: Path) -> None:
    """`git fetch` 要在第一次 push 之前發過：先問清楚遠端，再決定推不推。"""
    fetch在 = _第一次出現(紀錄, "git", "fetch")
    push在 = _第一次出現(紀錄, "git", "push")
    assert fetch在 is not None, (
        f"整趟一次 `git fetch` 都沒發，遠端長什麼樣是用猜的：{_讀呼叫(紀錄)}"
    )
    assert push在 is not None, f"一次 push 都沒發：{_讀呼叫(紀錄)}"
    assert fetch在 < push在, (
        f"fetch 排在 push 後面，等於推出去之後才問遠端：fetch 第 {fetch在} 筆、push 第 {push在} 筆"
    )


def _origin上的subject(origin: Path, 分支: str) -> list[str]:
    輸出 = _跑git(origin, "log", "--format=%s", f"refs/heads/{分支}").stdout
    return [行.strip() for 行 in 輸出.splitlines() if 行.strip()]


def _從另一個clone往那條分支推一顆(暫存根: Path, origin: Path, 主題: str) -> None:
    """在 origin 的那條分支上推一顆本地不知道的 commit（＝`gh pr update-branch` 的效果）。

    一定要在裝上記錄用 git 之前跑：這是測試自己造現場，不是 `收` 發的指令。
    """
    另一個 = 暫存根 / "另一個clone"
    assert _跑git(暫存根, "clone", "-q", str(origin), str(另一個)).returncode == 0
    for 指令 in (
        ("config", "user.email", "測試@例子"),
        ("config", "user.name", "測試"),
        ("config", "commit.gpgsign", "false"),
        ("checkout", "-q", "-b", 分支名),
    ):
        assert _跑git(另一個, *指令).returncode == 0
    (另一個 / "遠端那顆的產出.txt").write_text("別人在遠端那條分支上加的\n", encoding="utf-8")
    assert _跑git(另一個, "add", "-A").returncode == 0
    assert _跑git(另一個, "commit", "-q", "-m", 主題).returncode == 0
    assert _跑git(另一個, "push", "-q", "origin", f"HEAD:refs/heads/{分支名}").returncode == 0


def _斷言有gh指令(紀錄: Path, *開頭: str) -> list[str]:
    """斷言假 `gh` 收到過以 `開頭` 起首的一道指令，並回傳那次的 argv。"""
    for 名稱, 參數 in _讀呼叫(紀錄):
        if 名稱 == "gh" and 參數[: len(開頭)] == list(開頭):
            return 參數
    訊息 = f"找不到 gh {' '.join(開頭)}：{_讀呼叫(紀錄)}"
    raise AssertionError(訊息)


def _旗標值(參數: list[str], 旗標: str) -> str | None:
    """回傳 argv 裡這個旗標帶的值（`--x 值` 與 `--x=值` 兩種寫法都認）；沒帶回 None。"""
    for 序, 段 in enumerate(參數):
        if 段 == 旗標 and 序 + 1 < len(參數):
            return 參數[序 + 1]
        if 段.startswith(f"{旗標}="):
            return 段.split("=", 1)[1]
    return None


def _origin上的分支(origin: Path) -> set[str]:
    輸出 = _跑git(origin, "for-each-ref", "--format=%(refname)", "refs/heads/").stdout
    return {行.strip() for 行 in 輸出.splitlines() if 行.strip()}


def _收尾參數(工作目錄: Path) -> list[str]:
    return ["收", "--工作目錄", str(工作目錄), "--不記帳", "--訊息", "測試收尾"]


@pytest.fixture
def 閘放行(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """把提交閘設成放行，並把**每一次**跑閘記進同一份指令紀錄裡。

    這一支釘的是閘之後的那一步，不是閘本身——但「閘跑過幾次、第幾次跑在哪一道
    git 指令之間」是要斷言的事實：併回動過樹之後不重跑閘就 push，等於把沒驗過的
    那棵樹推出去。只答 `放行` 的閘樁記不得自己被叫過，這件事在紀錄上就完全看不見。
    閘跟 git／gh 記在同一份紀錄裡，先後關係才比得出來。
    """

    def 設定() -> None:
        def 記一筆放行(*參數: object) -> int:
            紀錄路徑 = os.environ.get("NOVA_收推分支紀錄")
            if 紀錄路徑:
                目標 = str(參數[-1]) if 參數 else ""
                with Path(紀錄路徑).open("a", encoding="utf-8") as 檔:
                    json.dump(
                        {"程式": 閘的程式名, "argv": [目標], "cwd": str(Path.cwd())},
                        檔,
                        ensure_ascii=False,
                    )
                    檔.write("\n")
            return 放行

        monkeypatch.setattr(收模組, "_收尾閘", 記一筆放行)

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


def test_遠端分支比本地多一顆時收要先併回再推(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """origin 上那條分支跟本地分岔時，`收` 要先併回遠端再推：兩邊那兩顆都要留在 origin 上。

    這是 `gh pr update-branch` 之後的常態現場：遠端那條分支比本地多一顆 merge
    commit，本地又還有沒推上去的工作。收尾能不能走完，看的是它有沒有先問過遠端；
    「推之前先 fetch，照 `origin/<分支>` 與 HEAD 的關係決定要不要併回」是這一格
    唯一能同時保住兩邊工作的走法——推不上去就換人手工接完，那正是這條線要消滅的。

    併回只准用 merge：rebase 會把遠端那顆的雜湊重寫掉，PR 上原本的那顆就成了孤兒，
    而下一次 push 非得 force 不可。併回之後那棵樹已經不是閘綠過的那一棵了，所以
    push 之前**一定要再跑一次提交閘**——閘對 A 樹綠，推出去的是 B 樹，中間那一格
    沒人驗過。

    這棵樹的 `merge.ff` 鎖成 `only`：**併回不准靠 git 的預設設定站著**。有人的
    `~/.gitconfig` 就是這樣寫的，而 `merge.ff=only` 等同替每一道 `git merge` 補上
    `--ff-only`——分岔的兩顆一碰就被拒，收尾當場停在併回、重跑閘與 push 一步都不發，
    人的個人設定就這樣決定了收尾走不走得完。併回這一道要自己把 fast-forward 政策
    講明（`--ff`／`--no-ff`），這一格才跟誰的機器無關。
    """
    專案, origin, 起點commit = _造專案與origin(tmp_path)
    # worktree 跟主工作區共用同一份 repo local config，所以設在專案上就等於設在樹上。
    assert _跑git(專案, "config", "merge.ff", "only").returncode == 0
    樹 = 開一個工作樹(
        專案,
        落點=tmp_path / f"nova-wt-{分支名.rsplit('/', maxsplit=1)[-1]}",
        起點commit=起點commit,
        分支=分支名,
    )
    (樹 / "分支的產出.txt").write_text("這一條線做完的事\n", encoding="utf-8")
    遠端那顆 = "遠端先落地的那顆"
    _從另一個clone往那條分支推一顆(tmp_path, origin, 遠端那顆)
    紀錄 = _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    閘放行()

    碼 = 主程式(_收尾參數(樹))

    輸出 = capsys.readouterr()
    assert 碼 == 放行, (
        f"遠端那條分支比本地多一顆是 update-branch 之後的常態，不是失敗：收到 {碼}\n"
        f"{輸出.out}\n{輸出.err}"
    )
    _斷言fetch在push之前(紀錄)
    subject們 = _origin上的subject(origin, 分支名)
    assert 遠端那顆 in subject們, (
        f"origin 上那條分支的歷史裡沒有遠端先落地那一顆——它被蓋掉了：{subject們}"
    )
    assert "測試收尾" in subject們, (
        f"這棵樹這一趟做的工作沒推上去，origin 還停在遠端那一顆：{subject們}"
    )
    呼叫 = _讀呼叫(紀錄)
    重寫歷史的 = [
        參數 for 名稱, 參數 in 呼叫 if 名稱 == "git" and 參數[:1] in (["rebase"], ["cherry-pick"])
    ]
    assert 重寫歷史的 == [], (
        f"併回遠端只准 merge：{重寫歷史的} 會把遠端那顆的雜湊重寫掉，"
        "PR 上原本那顆變孤兒，而且下一次 push 非 force 不可"
    )
    併回在 = _第一次出現(紀錄, "git", "merge")
    assert 併回在 is not None, f"分岔了卻一次 merge 都沒發，這一趟是怎麼推上去的：{呼叫}"
    assert any("origin" in 段 for 段 in 呼叫[併回在][1]), (
        f"merge 併的不是 origin 上那條分支：{呼叫[併回在][1]}"
    )
    push在 = _第一次出現(紀錄, "git", "push")
    assert push在 is not None
    閘跑在 = [序 for 序, (名稱, _參數) in enumerate(呼叫) if 名稱 == 閘的程式名]
    assert any(併回在 < 序 < push在 for 序 in 閘跑在), (
        f"併回動了樹卻沒重跑提交閘就推出去：閘跑在第 {閘跑在} 筆、"
        f"merge 第 {併回在} 筆、push 第 {push在} 筆。"
        "閘是對併回前那棵樹綠的，推出去的是併回後那棵"
    )


def test_PR已經存在時收不呼叫create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """這條分支上已經有一個開著的 PR 時，`收` 走更新路徑：不建 PR，照樣等 CI、照樣合併。

    「PR 在不在」要用查的（`收尾現場.查收尾現場` 依分支名唯一比對），不是拿
    `gh pr create` 去撞——撞到的是一句 `a pull request … already exists` 加非零，
    而那時 push 已經做完，收尾就停在一個「遠端動過、PR 沒合併」的半截現場。
    查到恰好一筆就是「有」：跳過建立、直接往等 CI 與合併走。

    「有」的門檻不是「`pr list` 比到了一行」，是**那一筆的身分欄位齊了**：清單只
    比得到分支名，編號、網址、head SHA 要 `gh pr view` 那一道才拿得到。所以這裡
    連 `pr list → pr view` 這條查詢路徑一起釘住——它就是 `收尾現場.查收尾現場`
    對外的形狀。少了 view 那一道，`收.py` 等於自己重寫了一份只看分支名的查詢，
    欄位不齊的那筆就會被當成「有 PR」直接往合併走。

    查詢還得**指名這條分支**（`--head <分支>`）：真的 `gh pr list` 不帶 `--limit`
    只吐前 30 筆，而這個 repo 上隨時有幾十個開著的 PR。一份不篩分支的清單比不到
    排在後面的目標，於是「有」被讀成「沒有」，`gh pr create` 照發。

    「PR 已經存在」不等於「這一趟沒事做」：PR 在，這條分支早就在遠端上，而這棵樹
    這一趟的工作還在本地。跳過建立的是 `gh pr create` 那一道，不是 commit／push——
    先查 PR 再整段跳過推送，PR 上看到的就是一份沒有這一趟工作的 diff。
    """
    專案, origin, 起點commit = _造專案與origin(tmp_path)
    樹 = 開一個工作樹(
        專案,
        落點=tmp_path / f"nova-wt-{分支名.rsplit('/', maxsplit=1)[-1]}",
        起點commit=起點commit,
        分支=分支名,
    )
    # PR 已經存在，代表這條分支早就推上去過：origin 上先有它，停在起點那一顆。
    assert _跑git(樹, "push", "-q", "origin", f"HEAD:refs/heads/{分支名}").returncode == 0
    (樹 / "分支的產出.txt").write_text("這一條線做完的事\n", encoding="utf-8")
    紀錄 = _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    monkeypatch.setenv("NOVA_收推已有PR", "1")
    閘放行()

    碼 = 主程式(_收尾參數(樹))

    輸出 = capsys.readouterr()
    建過PR = [參數 for 名稱, 參數 in _讀呼叫(紀錄) if 名稱 == "gh" and 參數[:2] == ["pr", "create"]]
    assert 建過PR == [], (
        f"這條分支上的 PR 已經存在，`收` 還是去建了一個：{建過PR}。"
        "撞出來的 already exists 會把收尾停在 push 之後、合併之前"
    )
    查清單 = _斷言有gh指令(紀錄, "pr", "list")
    assert "--json" in 查清單, f"`gh pr list` 沒指名要哪些欄位，回來的東西沒法比對：{查清單}"
    assert _旗標值(查清單, "--head") == 分支名, (
        f"`gh pr list` 沒指名要哪條分支：{查清單}。不帶 --limit 的清單只有前 30 筆，"
        f"目標排在別人後面就比不到，於是「有」被讀成「沒有」"
    )
    查那筆 = _斷言有gh指令(紀錄, "pr", "view")
    assert "--json" in 查那筆 and str(已存在的PR["number"]) in 查那筆, (
        f"沒有拿比到的那個編號去 `gh pr view` 把身分欄位取齊：{查那筆}。"
        "只憑清單上的分支名就宣稱「有 PR」，欄位不齊的那筆也會被讀成有"
    )
    查那筆在 = _第一次出現(紀錄, "gh", "pr", "view")
    合併在 = _第一次出現(紀錄, "gh", "pr", "merge")
    assert 查那筆在 is not None and 合併在 is not None and 查那筆在 < 合併在, (
        f"查在合併後面等於先合了再問：view 第 {查那筆在} 筆、merge 第 {合併在} 筆"
    )
    等CI = _斷言有gh指令(紀錄, "pr", "checks")
    assert 等CI[:5] == ["pr", "checks", "--required", "--watch"], (
        f"沒有 PR 要建不代表可以少等 CI：{等CI}"
    )
    合併 = _斷言有gh指令(紀錄, "pr", "merge")
    assert "--squash" in 合併, f"合併政策沒變：一律 squash：{合併}"
    _斷言fetch在push之前(紀錄)
    assert "測試收尾" in _origin上的subject(origin, 分支名), (
        f"PR 在不在只決定建不建 PR，這一趟的 commit 照樣要推上去："
        f"origin 上那條分支還停在舊 SHA：{_origin上的subject(origin, 分支名)}"
    )
    產出 = _跑git(origin, "show", f"refs/heads/{分支名}:分支的產出.txt")
    assert 產出.returncode == 0 and "這一條線做完的事" in 產出.stdout, (
        "origin 上那條分支的樹裡沒有這一趟做的東西——查到 PR 之後就把 commit／push "
        f"整段跳過了，PR 上是一份沒有這一趟工作的 diff：{產出.returncode} {產出.stderr}"
    )
    assert 碼 == 放行, f"PR 早就在了、CI 過了、也合併了，這一趟該收 0：收到 {碼}\n{輸出.err}"


@pytest.mark.parametrize("現場", sorted(答不出PR的原樣輸出))
def test_問不出這條分支有沒有PR時收停在未知不建也不合併(
    現場: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """「PR 在不在」問不出唯一答案時，`收` 停在未知碼 3：不建 PR、不合併、講明不要重跑。

    「有幾筆」有三種答案，不是兩種：**原樣的空清單**是「沒有」、身分欄位齊的恰好
    一筆是「有」，其餘全是「不知道」。空輸出、讀不成的 JSON、清單裡混著讀不成 PR
    的項目、同一條分支比到兩筆、清單合法非空卻一筆都不掛在這條分支上（＝查詢的
    `--head` 沒生效，答的不是我們問的問題）——這幾種都證明不了「沒有 PR」，把它們
    讀成零筆就是 fail-open：
    `收` 會去 `gh pr create`，撞出 already exists 而停在「遠端動過、PR 沒合併」的
    半截現場，或者更糟，在別人已經開好的 PR 旁邊再開一個。

    未知不是失敗：碼是 3 而不是 1，因為外圈不准拿它去重跑——遠端這時可能已經被
    push 動過了。現場原封留給人，訊息要自己說得出「不要重跑」。
    """
    專案, _origin, 起點commit = _造專案與origin(tmp_path)
    樹 = 開一個工作樹(
        專案,
        落點=tmp_path / f"nova-wt-{分支名.rsplit('/', maxsplit=1)[-1]}",
        起點commit=起點commit,
        分支=分支名,
    )
    (樹 / "分支的產出.txt").write_text("這一條線做完的事\n", encoding="utf-8")
    紀錄 = _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    monkeypatch.setenv("NOVA_收推PR清單原樣", 答不出PR的原樣輸出[現場])
    閘放行()

    碼 = 主程式(_收尾參數(樹))

    輸出 = capsys.readouterr()
    建過PR = [參數 for 名稱, 參數 in _讀呼叫(紀錄) if 名稱 == "gh" and 參數[:2] == ["pr", "create"]]
    assert 建過PR == [], (
        f"「{現場}」證明不了這條分支上沒有 PR，`收` 還是拿它當零筆去建了一個：{建過PR}"
    )
    合併過 = [參數 for 名稱, 參數 in _讀呼叫(紀錄) if 名稱 == "gh" and 參數[:2] == ["pr", "merge"]]
    assert 合併過 == [], f"連 PR 在不在都問不出來，卻走到了合併：{合併過}"
    assert 碼 == 未知, (
        f"「{現場}」是「不知道」，不是「沒有 PR」也不是確定失敗，該收 3：收到 {碼}\n"
        f"{輸出.out}\n{輸出.err}"
    )
    assert "重跑" in 輸出.err, f"收在 3 卻沒告訴人不要重跑，外圈只會再跑一次同一趟：{輸出.err!r}"


def test_乾淨樹且遠端落後時收照樣把本地HEAD推上去(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """線自己已經 commit 過、樹是乾淨的：`收` 不發 commit，但要把本地 HEAD 推上去。

    乾淨樹不是「沒事做」——它只代表沒有新東西要提交，不代表遠端跟本地同一顆。
    這一格的收場只有一個能算數：收完之後 origin 上那條分支的 SHA 就是本地 HEAD。
    把乾淨樹當成失敗（commit 回非零就停）或當成完成（不 push），遠端都會停在舊
    SHA，而 PR 上看到的是一份沒有這一趟工作的 diff。
    """
    專案, origin, 起點commit = _造專案與origin(tmp_path)
    樹 = 開一個工作樹(
        專案,
        落點=tmp_path / f"nova-wt-{分支名.rsplit('/', maxsplit=1)[-1]}",
        起點commit=起點commit,
        分支=分支名,
    )
    # 先把這棵樹推一次，origin 上那條分支才會**存在但停在父 commit**；少了這一步，
    # 收走的是「遠端沒這條分支」那一列，SHA 比對就測不到東西。
    assert _跑git(樹, "push", "-q", "origin", f"HEAD:refs/heads/{分支名}").returncode == 0
    (樹 / "分支的產出.txt").write_text("這一條線做完的事\n", encoding="utf-8")
    assert _跑git(樹, "add", "-A").returncode == 0
    assert _跑git(樹, "commit", "-q", "-m", "線自己先提交的那顆").returncode == 0
    本地HEAD = _跑git(樹, "rev-parse", "HEAD").stdout.strip()
    assert _跑git(樹, "status", "--porcelain").stdout.strip() == "", (
        "這一支要的現場是**乾淨樹**，樹裡還有沒提交的東西就走成別條路了"
    )
    紀錄 = _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    閘放行()

    碼 = 主程式(_收尾參數(樹))

    輸出 = capsys.readouterr()
    提交過的 = [參數 for 名稱, 參數 in _讀呼叫(紀錄) if 名稱 == "git" and 參數[:1] == ["commit"]]
    assert 提交過的 == [], (
        f"樹是乾淨的，`收` 還是發了 commit——那一道只會回非零，收尾就停在這裡：{提交過的}"
    )
    _斷言fetch在push之前(紀錄)
    assert _跑git(origin, "rev-parse", f"refs/heads/{分支名}").stdout.strip() == 本地HEAD, (
        "收完了，origin 上那條分支還停在舊 SHA：這一趟的 commit 沒推上去，"
        "PR 上看到的是一份沒有這些工作的 diff"
    )
    assert 碼 == 放行, f"沒東西可提交不是失敗，這一趟該收 0：收到 {碼}\n{輸出.out}\n{輸出.err}"


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

"""nova 收子命令：確定性收尾閉包（閘 → commit → push → PR → required CI → merge）。"""

import argparse
import enum
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, assert_never

from nova.契約.退出碼 import 放行, 未知, 閘紅
from nova.載體 import 收尾現場
from nova.載體.工作樹 import 主工作區, 收掉工作樹
from nova.載體.規則表 import 建規則表
from nova.載體.閘 import 跑閘

#: GitHub `createPullRequest` 的標題上限，收在提交閘前擋下超長標題。
標題上限 = 256

#: push 等遠端回話的上限（秒）。超過就是「結果不明」：回未知碼 3，不是紅、也不准重跑。
推送逾時秒 = 300.0

__all__ = [
    "子命令_收",
    "_收尾閘",
    "_跑並印收尾指令",
    "_跑收尾指令",
]


def _跑收尾指令(根目錄: Path, *指令: str, 逾時秒: float | None = None) -> tuple[int, str]:
    """在專案裡跑一個收尾指令，回傳 nova 退出碼與輸出。"""
    try:
        結果 = subprocess.run(  # noqa: S603 —— 收尾指令由這個節點固定組出
            list(指令),
            cwd=根目錄,
            capture_output=True,
            text=True,
            check=False,
            timeout=逾時秒,
        )
    except subprocess.TimeoutExpired:
        return 未知, f"指令等不到結果（{' '.join(指令)}）"
    except OSError as 錯:
        return 閘紅, f"指令跑不起來（{' '.join(指令)}）：{錯}"
    輸出 = (結果.stdout + 結果.stderr).strip()
    if 結果.returncode:
        return 閘紅, 輸出 or f"指令退出碼 {結果.returncode}：{' '.join(指令)}"
    return 放行, 輸出


def _跑並印收尾指令(根目錄: Path, *指令: str, 逾時秒: float | None = None) -> int:
    """跑一個收尾指令並印出它的輸出。"""
    碼, 輸出 = _跑收尾指令(根目錄, *指令, 逾時秒=逾時秒)
    if 輸出:
        sys.stdout.write(f"{輸出}\n")
    return 碼


def _收尾閘(參數: argparse.Namespace, 根目錄: Path) -> int:
    """只跑提交閘；閘紅時不碰 git 與 gh。"""
    from nova.載體 import 命令列  # noqa: PLC0415 —— 延遲匯入避免循環依賴

    try:
        with 命令列._開帳(參數) as 帳:  # noqa: SLF001 —— 借用命令列共用開帳
            結果表 = 跑閘("提交", 建規則表(根目錄), 提前停止=True, 帳=帳)
    except (OSError, ValueError) as 錯:
        sys.stderr.write(f"{錯}\n")
        return 閘紅
    return 命令列._印結果(結果表)  # noqa: SLF001 —— 借用命令列共用印結果


def 子命令_收(參數: argparse.Namespace) -> int:
    """確定性收尾：閘 → commit → fetch 對齊 → push → PR → required CI → merge。"""
    from nova.載體 import 命令列  # noqa: PLC0415 —— 延遲匯入避免循環依賴

    根目錄 = 命令列._專案脈絡(參數).根目錄  # noqa: SLF001 —— 借用命令列共用專案脈絡

    訊息 = 參數.訊息 or " ".join(參數.提交訊息) or "nova：收尾"
    收尾訊息 = _切收尾訊息(訊息)
    if (碼 := _動手之前的檢查(參數, 根目錄, 標題=收尾訊息.標題)) != 放行:
        return 碼

    現場, 現場碼 = _開工前問清楚現場(根目錄)
    if 現場 is None:
        return 現場碼
    分支 = 現場.分支
    主區 = 現場.主區
    是派工樹 = 現場.是派工樹

    if (碼 := _提交推送並開PR(參數, 根目錄, 收尾訊息=收尾訊息, 分支=分支)) != 放行:
        return 碼

    if (
        碼 := _跑並印收尾指令(
            根目錄, "gh", "pr", "checks", "--required", "--watch", 逾時秒=參數.等CI秒
        )
    ) != 放行:
        return 碼

    if (碼 := _合併這個PR(根目錄, 刪遠端分支=not 是派工樹)) != 放行:
        return 碼

    return _合併之後收乾淨(根目錄, 主區=主區, 分支=分支, 是派工樹=是派工樹)


class _收尾現場(NamedTuple):
    """`收` 開工前問到的拓撲：這棵樹掛哪條分支、主工作區在哪、它自己是不是派工樹。"""

    分支: str
    主區: Path
    是派工樹: bool


def _開工前問清楚現場(根目錄: Path) -> tuple[_收尾現場 | None, int]:
    """在**第一個 git 寫入之前**把拓撲問清楚：回 (現場, 碼)，問不出來時現場是 None。

    問不出來就停在這裡，`收` 一個 commit、一次 push 都還沒發。查不到主工作區不准
    猜成「當它不是派工樹」——猜錯的下場是 `gh pr merge --delete-branch` 在 merge
    做完之後才回 128，樹與分支照樣留著（`docs/負控紀錄/0010`）。
    """
    分支, 抱怨 = _這棵樹的分支(根目錄)
    if 分支 is None:
        return None, _回報沒有分支可以推(抱怨)
    try:
        主區 = 主工作區(根目錄)
    except OSError as 錯:
        sys.stderr.write(f"問不出這棵樹的主工作區在哪，不 commit 不 push：{錯}\n")
        return None, 閘紅
    # macOS 的 `/var` 是 `/private/var` 的 symlink，兩邊都要 resolve 才比得出來。
    是派工樹 = 主區.resolve() != 根目錄.resolve()
    return _收尾現場(分支=分支, 主區=主區, 是派工樹=是派工樹), 放行


def _合併之後收乾淨(根目錄: Path, *, 主區: Path, 分支: str, 是派工樹: bool) -> int:
    """PR 合併之後把現場收乾淨：派工樹連它的本地分支一起走，再查證分支真的不在了。

    merge 之後 `根目錄` 隨時會不見（派工樹被自己收掉），所以這之後每一道指令的
    cwd 只准是主區。收不掉是「merge 已經發生過」的狀態，訊息要明講不要重跑
    merge——重跑只會拿到一句「已經合併過了」，真正沒做完的是清現場那一段。
    """
    if 是派工樹:
        try:
            收掉工作樹(根目錄)
        except OSError as 錯:
            sys.stderr.write(
                f"PR 已合併，但這棵樹沒收乾淨：{錯}。"
                f"不要重跑 merge；清掉樹之後手動刪本地分支 {分支}\n"
            )
            return 閘紅
        sys.stdout.write(f"樹已收掉，回主工作區：{主區}\n")
    return _查證本地分支已刪(主區, 分支)


def _這棵樹的分支(根目錄: Path) -> tuple[str | None, str]:
    """讀這棵樹掛在哪條分支上，**不猜名字**；回 (分支, git 沒問成時的抱怨)。

    `git symbolic-ref -q --short HEAD` 是三態：rc 0 是分支名、rc 1 是 detached、
    其他非零是「這道查詢自己壞了」。把後兩者併起來，人拿到的會是一句「這棵樹
    不是派工開的形狀，請用 nova 派工 重開」——照著做只會重開一棵一樣壞的樹。
    """
    結果 = subprocess.run(  # noqa: S603 —— 收尾指令由這個節點固定組出
        ["git", "symbolic-ref", "-q", "--short", "HEAD"],  # noqa: S607
        cwd=根目錄,
        capture_output=True,
        text=True,
        check=False,
    )
    if 結果.returncode == 0:
        return (結果.stdout.strip() or None), ""
    if 結果.returncode == 1:
        return None, ""
    抱怨 = (結果.stdout + 結果.stderr).strip()
    return None, 抱怨 or f"git symbolic-ref 退出碼 {結果.returncode}"


def _回報沒有分支可以推(抱怨: str) -> int:
    """沒問出分支就停在這裡：不猜分支名，也不讓後面的 commit／push 開始。

    兩種情形要分開講，不然人拿到的建議會是錯的：`抱怨` 非空是「這道查詢自己
    壞了」，git 那句話要原樣交出去；空的才是 detached，那才叫「這棵樹不是派工
    開的形狀」、重開一棵才有用。
    """
    if 抱怨:
        sys.stderr.write(
            f"問不出這棵樹掛在哪條分支上，收尾停在這裡（沒有 commit、沒有 push）。\n"
            f"git 說：{抱怨}\n"
        )
    else:
        sys.stderr.write(
            "這棵樹不是派工開的形狀：HEAD 是 detached，沒有分支可以推。\n"
            "派工開的樹從第一秒就掛在 nova/<時戳>-<六碼> 上；"
            "這一棵請用 nova 派工 重開，不要猜名字硬推。\n"
        )
    return 閘紅


def _動手之前的檢查(參數: argparse.Namespace, 根目錄: Path, *, 標題: str) -> int:
    """git 與 gh 一個字都還沒發之前要過的兩關，貴的那關排後面。

    標題長度是看一眼字串就有答案的檢查，排在提交閘前面；提交閘本體實測 8.5 秒，
    完整測試套件約兩分鐘是驗證成本，不是 `收` 執行的提交閘成本。順序反過來的話，
    人得等閘全綠才被告知一個開跑前就看得出來的錯。
    """
    if (碼 := _擋掉過長的標題(標題)) != 放行:
        return 碼
    return _收尾閘(參數, 根目錄)


def _擋掉過長的標題(標題: str) -> int:
    """第一行超過 GitHub 上限就在這裡停，不讓後面的 git 與 gh 開始。"""
    if len(標題) <= 標題上限:
        return 放行
    sys.stderr.write(
        f"訊息第一行 {len(標題)} 字，PR 標題超過 {標題上限} 字上限，收尾停在這裡"
        f"（沒有跑閘、沒有 commit、沒有 push）。\n"
        f"把第一行縮到 {標題上限} 字以內，其餘寫進本文。\n"
    )
    return 閘紅


class _收尾訊息(NamedTuple):
    """一段收訊息的三種用法：commit 收全文，PR 標題收第一行，PR 本文收其餘。"""

    全文: str
    標題: str
    本文: str


def _切收尾訊息(全文: str) -> _收尾訊息:
    """照 git 慣例把收訊息切成「第一行標題」與「其餘本文」。

    PR 標題只收得下一行（GitHub 上限 256 字），本文才是放負控段那些的地方。開頭
    空白行會去掉，但本文第一行自己的縮排要原樣保留；沒有本文可切時退回第一行。
    """
    第一行, _, 其餘 = 全文.partition("\n")
    標題 = 第一行.strip()
    本文行 = 其餘.splitlines(keepends=True)
    while 本文行 and not 本文行[0].strip():
        本文行.pop(0)
    本文 = "".join(本文行)
    return _收尾訊息(全文=全文, 標題=標題, 本文=本文 or 標題)


def _停在未知(原因: str, 後果: str) -> int:
    """答不出來就停在未知碼 3 的共用出口：講清楚「為什麼答不出來」與「停在哪一步」。

    收尾前半段三道查詢（樹乾不乾淨、遠端與 HEAD 的關係、PR 在不在）共用這條
    fail-closed 出口：問不出來一律不猜，現場原封留著，訊息自己說得出不准重跑。
    """
    sys.stderr.write(f"{原因}\n{後果}\n")
    return 未知


def _樹是不是乾淨的(根目錄: Path) -> tuple[bool | None, str]:
    """問 `git status --porcelain` 這棵樹乾不乾淨；問不出來回 (None, 原因)，不准當成乾淨。"""
    結果 = 收尾現場.跑收尾指令(根目錄, "git", "status", "--porcelain")
    if 結果.退出碼 != 放行:
        抱怨 = (結果.stdout + 結果.stderr).strip()
        return None, f"問不出這棵樹乾不乾淨（git status）：{抱怨}"
    return not 結果.stdout.strip(), ""


def _有東西才提交(根目錄: Path, *, 收尾訊息: _收尾訊息) -> int:
    """樹乾淨就不發 commit（乾淨不是紅，是「沒東西可提交」）；問不出乾不乾淨回 3。"""
    乾淨, 原因 = _樹是不是乾淨的(根目錄)
    if 乾淨 is None:
        return _停在未知(原因, "沒有 commit、沒有 push；不要重跑。")
    if 乾淨:
        return 放行
    if (碼 := _跑並印收尾指令(根目錄, "git", "add", "-A")) != 放行:
        return 碼
    return _跑並印收尾指令(根目錄, "git", "commit", "-m", 收尾訊息.全文)


def _遠端追蹤ref(分支: str) -> str:
    """fetch 落地之後，origin 上那條分支在本地叫什麼 ref。"""
    return f"refs/remotes/origin/{分支}"


def _問一道git查詢(根目錄: Path, *指令: str) -> tuple[str | None, str]:
    """跑一道唯讀的 git 查詢，回 (輸出去頭尾空白, "")；查詢自己非零就回 (None, git 的抱怨)。

    只分辨「問到了」與「問不出來」：輸出是空字串對誰是什麼意思，由呼叫端自己講。
    """
    結果 = 收尾現場.跑收尾指令(根目錄, *指令)
    if 結果.退出碼 != 放行:
        return None, 結果.stderr.strip()
    return 結果.stdout.strip(), ""


def _fetch失敗之後再問一次(根目錄: Path, 分支: str, fetch抱怨: str) -> tuple[str | None, str]:
    """fetch 失敗時分辨兩件事：遠端真的沒這條分支，還是這次就是問不出來。

    回傳沿用 `_問origin上那條分支` 的三態：空字串是「遠端真的沒有這條分支」、
    None 是「問不出來」（原因寫在第二格）；這一格答不出 SHA。
    """
    列出, 抱怨 = _問一道git查詢(根目錄, "git", "ls-remote", "origin", f"refs/heads/{分支}")
    if 列出 is None:
        return None, f"fetch 失敗，也問不出 origin 上有沒有 {分支}：{抱怨}"
    if 列出:
        return None, f"origin 上有 {分支}，fetch 卻失敗：{fetch抱怨}"
    return "", ""


def _問origin上那條分支(根目錄: Path, 分支: str) -> tuple[str | None, str]:
    """先 `git fetch` 把 origin 上那條分支抓下來，再回它的 SHA。

    三態：SHA 是「遠端有這條分支」、空字串是「遠端真的沒有這條分支」、None 是
    「問不出來」——問不出來的那一格不准猜成新分支，猜錯就是拿 push 去撞遠端。
    """
    抓 = 收尾現場.跑收尾指令(
        根目錄, "git", "fetch", "origin", f"+refs/heads/{分支}:{_遠端追蹤ref(分支)}"
    )
    if 抓.退出碼 != 放行:
        return _fetch失敗之後再問一次(根目錄, 分支, 抓.stderr.strip())
    指到, 抱怨 = _問一道git查詢(根目錄, "git", "rev-parse", _遠端追蹤ref(分支))
    if 指到 is None:
        return None, f"fetch 成功卻讀不到 origin/{分支}：{抱怨}"
    return 指到, ""


class _遠端關係(enum.Enum):
    """`origin/<分支>` 與本地 HEAD 的拓撲關係；判不出來的那一格不入列，由呼叫端回未知碼。"""

    沒有 = "遠端沒有這條分支"
    相同 = "兩顆是同一顆"
    領先 = "本地領先遠端"
    落後 = "本地落後遠端"
    分岔 = "兩邊各有對方沒有的"


def _是不是祖先(根目錄: Path, 可能的祖先: str, 可能的後代: str) -> bool | None:
    """`git merge-base --is-ancestor`：0 是、1 不是、其餘是這道查詢自己壞了（回 None）。"""
    結果 = 收尾現場.跑收尾指令(根目錄, "git", "merge-base", "--is-ancestor", 可能的祖先, 可能的後代)
    if 結果.子程序退出碼 == 0:
        return True
    if 結果.子程序退出碼 == 1:
        return False
    return None


def _比祖先關係(根目錄: Path, 本地sha: str, 遠端sha: str) -> _遠端關係 | None:
    """比出相同／領先／落後／分岔；哪一道 `--is-ancestor` 自己壞了就回 None。"""
    if 本地sha == 遠端sha:
        return _遠端關係.相同
    遠端是祖先 = _是不是祖先(根目錄, 遠端sha, 本地sha)
    本地是祖先 = _是不是祖先(根目錄, 本地sha, 遠端sha)
    if 遠端是祖先 is None or 本地是祖先 is None:
        return None
    if 遠端是祖先:
        return _遠端關係.領先
    return _遠端關係.落後 if 本地是祖先 else _遠端關係.分岔


def _問遠端關係(根目錄: Path, 分支: str) -> tuple[_遠端關係 | None, str]:
    """fetch 之後回 `origin/<分支>` 與 HEAD 的關係；問不出來回 (None, 原因)。

    關係一律用 `git merge-base --is-ancestor` 判，不讀 `git status` 的自由文字。
    """
    遠端sha, 原因 = _問origin上那條分支(根目錄, 分支)
    if 遠端sha is None:
        return None, 原因
    if not 遠端sha:
        return _遠端關係.沒有, ""
    本地sha, 抱怨 = _問一道git查詢(根目錄, "git", "rev-parse", "HEAD")
    if 本地sha is None:
        return None, f"問不出本地 HEAD 是哪一顆：{抱怨}"
    關係 = _比祖先關係(根目錄, 本地sha, 遠端sha)
    if 關係 is None:
        return None, f"判不出 origin/{分支} 與 HEAD 的關係"
    return 關係, ""


def _併回遠端那條分支(參數: argparse.Namespace, 根目錄: Path, *, 分支: str) -> int:
    """分岔時併回遠端（merge，不 rebase——rebase 歸 DIRTY/BEHIND 修復交易那張票）。

    併回動過樹就重跑提交閘：閘是對併回前那棵樹綠的，推出去的是併回後那棵。

    fast-forward 政策自己講明（`--no-ff`）：使用者的 `merge.ff=only` 等同替每一道
    merge 補上 `--ff-only`，分岔的兩顆一碰就被拒，收尾會停在併回、push 一步都不發。
    收尾走不走得完不准由誰的 `~/.gitconfig` 決定。
    """
    併回 = ("git", "merge", "--no-ff", "--no-edit", _遠端追蹤ref(分支))
    if (碼 := _跑並印收尾指令(根目錄, *併回)) != 放行:
        sys.stderr.write(
            f"併回 origin/{分支} 撞了衝突，收尾停在這裡：沒有 push、沒有建 PR。\n"
            "現場原封留著給人解：不要 merge --abort 之後重試，也不要改推 rebase。\n"
        )
        return 碼
    if (碼 := _收尾閘(參數, 根目錄)) != 放行:
        sys.stderr.write(
            f"併回 origin/{分支} 之後重跑提交閘沒過，沒有 push：\n"
            "閘是對併回前那棵樹綠的，推出去的會是併回後那棵，沒驗過的東西不推。\n"
        )
        return 碼
    return 放行


def _快轉到遠端(根目錄: Path, *, 分支: str) -> int:
    """本地落後、自己沒有新東西：把遠端快轉進來就好，推上去也是空推。"""
    return _跑並印收尾指令(根目錄, "git", "merge", "--ff-only", _遠端追蹤ref(分支))


def _推之前先對齊遠端(參數: argparse.Namespace, 根目錄: Path, *, 分支: str) -> tuple[int, bool]:
    """fetch 之後照 `origin/<分支>` 與 HEAD 的關係決定推不推；回 (碼, 要不要 push)。"""
    關係, 原因 = _問遠端關係(根目錄, 分支)
    if 關係 is None:
        return _停在未知(原因, "沒有 push、沒有建 PR，現場留著；不要重跑。"), False
    match 關係:
        case _遠端關係.沒有 | _遠端關係.領先:
            # 遠端真的沒這條分支，或本地領先：都是乾淨的 fast-forward。
            return 放行, True
        case _遠端關係.相同:
            return 放行, False
        case _遠端關係.落後:
            # 本地沒有新東西，推上去也是空推：把遠端快轉進來就好。
            return _快轉到遠端(根目錄, 分支=分支), False
        case _遠端關係.分岔:
            # 併回成功才輪到 push：本地帶著遠端沒有的東西，非推不可。
            碼 = _併回遠端那條分支(參數, 根目錄, 分支=分支)
            return 碼, 碼 == 放行
        case _:  # pragma: no cover - 型別已窮盡
            assert_never(關係)


def _推上origin(根目錄: Path, *, 分支: str) -> int:
    """push 用完整 refspec `HEAD:refs/heads/<分支>`。

    只寫 `HEAD` 會被 git 回一句「not a full refname」，而那時閘已經全綠、commit 也
    成功了，整套白跑。

    等不到遠端回話時是未知碼 3，不是紅：遠端可能已經收下了，重跑會再推一次。
    """
    推送指令 = ("git", "push", "--set-upstream", "origin", f"HEAD:refs/heads/{分支}")
    碼 = _跑並印收尾指令(根目錄, *推送指令, 逾時秒=推送逾時秒)
    if 碼 == 未知:
        sys.stderr.write(
            f"push 到 origin/{分支} 等不到結果，遠端收下了沒有現在不知道：不要重跑。\n"
        )
    return 碼


def _讀出PR清單(根目錄: Path, 分支: str) -> tuple[list[dict[str, object]] | None, str]:
    """跑 `gh pr list --head <分支> --json` 並讀成一份 PR 清單；讀不成回 (None, 原因)＝「不知道」。

    一定要指名 `--head <分支>`：`gh pr list` 不帶 `--limit` 只吐前 30 筆，而這個 repo
    上隨時有幾十個開著的 PR。不篩分支的清單比不到排在後面的目標，「有」就被讀成
    「沒有」，`gh pr create` 照發。

    只有「解析得出一份清單、且每一筆都讀得成 PR」才算數：空輸出、壞 JSON、
    交出來的不是清單、清單裡混著讀不成 PR 的項目，全都讀不出「有幾筆」。
    把讀不成的那筆默默丟掉再宣稱「零筆」，下一步就是拿猜的去 `gh pr create`。
    """
    原始, 原因 = 收尾現場._查gh(  # noqa: SLF001 —— 借收尾現場那份查詢與解析，不另寫第二份
        根目錄,
        "gh",
        "pr",
        "list",
        "--head",
        分支,
        "--json",
        ",".join(收尾現場._要的欄位),  # noqa: SLF001 —— 同上，欄位表只有一份
        逾時秒=None,
        來源="gh pr list",
    )
    if 原因:
        return None, 原因
    if not isinstance(原始, list):
        return None, f"gh pr list 回的不是一份清單：{原始!r}"
    清單: list[dict[str, object]] = []
    for 項 in 原始:
        # 讀不讀得成，看的是「這一筆比不比得出它掛在哪條分支」：不是物件、或
        # `headRefName` 不是字串，這份清單就答不出「這條分支上有幾筆」。
        if not isinstance(項, dict) or not isinstance(項.get("headRefName"), str):
            return None, f"gh pr list 的清單裡有讀不成 PR 的項目：{原始!r}"
        清單.append(項)
    return 清單, ""


def _這條分支有沒有PR(根目錄: Path, 分支: str) -> tuple[bool | None, str]:
    """問 gh 這條分支上有沒有開著的 PR：**原樣的空清單**是「沒有」、身分欄位齊的一筆才是「有」。

    「有」的門檻不是清單上比到一行——清單只比得到分支名，編號、網址、head SHA 要
    `收尾現場.查收尾現場`（pr list → pr view）那一道才取得齊。清單讀不出來（見
    `_讀出PR清單`）、比到兩筆以上、身分欄位取不齊，一律回 None＝「不知道」——空輸出
    不准當成「沒有 PR」，那是拿 fail-open 去換一次 `gh pr create`，撞出來的是半截現場。

    「零筆匹配」也不是「沒有」：清單合法非空、卻一筆都不掛在這條分支上，證明的是
    `--head` 沒生效——答的不是我們問的問題，一樣回 None。
    """
    清單, 原因 = _讀出PR清單(根目錄, 分支)
    if 清單 is None:
        return None, 原因
    if not 清單:
        return False, ""
    匹配 = [pr for pr in 清單 if pr.get("headRefName") == 分支]
    if len(匹配) != 1:
        return None, (
            f"gh pr list 回了 {len(清單)} 筆，其中比到 {len(匹配)} 個掛在 {分支} 上的 PR，"
            f"不猜：{清單!r}"
        )
    編號 = 匹配[0].get("number")
    if not isinstance(編號, int):
        # 清單只比得到分支名。沒有編號就指不出目標，這是「不知道」，不是「有 PR」。
        return None, f"比到掛在 {分支} 上的一筆，但它沒有 number 欄位：{匹配[0]!r}"
    快照 = 收尾現場.查收尾現場(根目錄, 分支=分支, PR目標=編號)
    if 快照.退出碼 != 放行:
        # 身分欄位取不齊就證明不了目標；不建也不合併。
        return None, 快照.證據
    return True, ""


def _沒有PR才建(根目錄: Path, *, 收尾訊息: _收尾訊息, 分支: str) -> int:
    """PR 在不在用查的，不用 `gh pr create` 撞；查不出來回 3，不建也不合併。"""
    有PR, 原因 = _這條分支有沒有PR(根目錄, 分支)
    if 有PR is None:
        return _停在未知(原因, "不知道這條分支上有沒有 PR，不建也不合併；不要重跑。")
    if 有PR:
        sys.stdout.write(f"{分支} 上已經有開著的 PR，跳過建立，直接往等 CI 走。\n")
        return 放行
    return _跑並印收尾指令(
        根目錄, "gh", "pr", "create", "--title", 收尾訊息.標題, "--body", 收尾訊息.本文
    )


def _提交推送並開PR(
    參數: argparse.Namespace, 根目錄: Path, *, 收尾訊息: _收尾訊息, 分支: str
) -> int:
    """commit（有東西才發）→ fetch 對齊遠端 → push（該推才推）→ PR（沒有才建）。

    這四步不准同時假設「樹是髒的、遠端沒這條分支、PR 不存在」：`gh pr update-branch`
    之後遠端那條分支會比本地多一顆，三個假設一個都不成立。
    """
    if (碼 := _有東西才提交(根目錄, 收尾訊息=收尾訊息)) != 放行:
        return 碼
    碼, 要push = _推之前先對齊遠端(參數, 根目錄, 分支=分支)
    if 碼 != 放行:
        return 碼
    if 要push and (碼 := _推上origin(根目錄, 分支=分支)) != 放行:
        return 碼
    return _沒有PR才建(根目錄, 收尾訊息=收尾訊息, 分支=分支)


def _合併這個PR(根目錄: Path, *, 刪遠端分支: bool) -> int:
    """既有政策：一律 squash，絕不帶 `--admin`。

    `--delete-branch` 只給主工作區那條路。派工樹上它是有害的：gh 刪本地分支前會先
    `git checkout <base>`，而 base 被主工作區佔著，linked worktree 裡那道 checkout
    回 128——**merge 已經做完了才回非零**。遠端那條分支由 repo 的
    delete-branch-on-merge 刪。
    """
    指令 = ["gh", "pr", "merge", "--squash"]
    if 刪遠端分支:
        指令.append("--delete-branch")
    return _跑並印收尾指令(根目錄, *指令)


def _查證本地分支已刪(根目錄: Path, 頭分支: str) -> int:
    """`gh pr merge` 回 0 只代表 GitHub 那端；本地分支還在就是沒收乾淨。"""
    if not 頭分支:
        return 放行
    _, 殘留 = _跑收尾指令(根目錄, "git", "branch", "--list", 頭分支)
    if not 殘留.strip():
        return 放行
    sys.stderr.write(
        f"GitHub 已合併這個 PR，但本地分支 {頭分支} 沒刪乾淨（多半還被某棵 worktree 佔著）。\n"
        f"不要再跑一次 merge；先清掉佔用它的 worktree，再刪本地分支 {頭分支}。\n"
    )
    return 閘紅

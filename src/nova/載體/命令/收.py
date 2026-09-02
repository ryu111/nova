"""nova 收子命令：確定性收尾閉包（閘 → commit → push → PR → required CI → merge）。"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from nova.契約.退出碼 import 放行, 未知, 閘紅
from nova.載體.工作樹 import 主工作區, 收掉工作樹
from nova.載體.規則表 import 建規則表
from nova.載體.閘 import 跑閘

#: GitHub `createPullRequest` 的標題上限，收在提交閘前擋下超長標題。
標題上限 = 256

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
    """確定性收尾：閘 → commit → push → PR → required CI → merge。"""
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

    if (
        碼 := _提交推送並開PR(
            根目錄,
            收尾訊息=收尾訊息,
            分支=分支,
        )
    ) != 放行:
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


def _提交推送並開PR(根目錄: Path, *, 收尾訊息: _收尾訊息, 分支: str) -> int:
    """commit → push → 開 PR，其中一步不放行就停在那一步的退出碼。

    push 用完整 refspec `HEAD:refs/heads/<分支>`：只寫 `HEAD` 會被 git 回一句
    「not a full refname」，而那時閘已經全綠、commit 也成功了，整套白跑。
    """
    訊息 = 收尾訊息.全文
    for 指令 in (
        ("git", "add", "-A"),
        ("git", "commit", "-m", 訊息),
        ("git", "push", "--set-upstream", "origin", f"HEAD:refs/heads/{分支}"),
        ("gh", "pr", "create", "--title", 收尾訊息.標題, "--body", 收尾訊息.本文),
    ):
        if (碼 := _跑並印收尾指令(根目錄, *指令)) != 放行:
            return 碼
    return 放行


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

"""扇出開出來的樹誰收、收不掉的怎麼看得見、開不出來的那一顆怎麼跳過。

隔離本身由 `test_扇出開工作樹.py` 守；這裡守的是它的另一半——**留下來的樹**。
這台機器上二十幾棵 worktree 就是這一半沒人守的樣子：乾淨的樹沒回收，
有產出的樹留了現場卻沒有人講它在哪裡。

四支測試對到四件事：跑完乾淨的收掉、有產出的留現場並且出聲指向 `nova 線`、
落點被佔住的那一顆落成 `開不出工作樹` 而整批照跑、
**樹收掉了但它那條本地分支刪不掉時，出的聲要講分支**。
"""

import subprocess
import threading
from pathlib import Path

import pytest

from nova.契約.扇出 import 分支工作
from nova.契約.節點 import 分支識別碼, 節點上下文, 節點成功, 結果代碼
from nova.載體 import 工作樹 as 工作樹模組
from nova.載體.扇出工作樹 import 帶著工作樹扇出
from tests.整合.test_扇出開工作樹 import (
    _上下文,
    _工作,
    _換掉內容,
    _政策,
    _跑,
    _造一個commit的repo,
    共用檔名,
)


def _工作樹數(專案: Path) -> int:
    輸出 = _跑(專案, "worktree", "list", "--porcelain")
    assert 輸出.returncode == 0, 輸出.stderr
    return sum(1 for 行 in 輸出.stdout.splitlines() if 行.startswith("worktree "))


def test_乾淨的分支跑完不留樹(tmp_path: Path) -> None:
    """兩顆分支都不寫檔，跑完 `git worktree list` 要回到跑之前的樣子。

    這一條沒有測試背書的話，扇出就是一台每跑一次就多留兩棵樹的機器。
    """
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造一個commit的repo(專案)
    跑之前 = _工作樹數(專案)

    工作 = (_工作("甲"), _工作("乙"))

    def 執行一顆(工作項: 分支工作[str, None], 這顆上下文: 節點上下文) -> 節點成功[str]:
        assert 這顆上下文.任務.工作目錄 != 專案, "分支被派回主工作區，等於沒有隔離"
        return 節點成功(產出=_換掉內容(工作項.輸入, "什麼都沒寫"), 證據=(), 用量=None)

    結果 = 帶著工作樹扇出(
        工作,
        執行一顆=執行一顆,
        上下文=_上下文(專案),
        政策=_政策(frozenset(工作項.分支 for 工作項 in 工作)),
        專案=專案,
        樹根=tmp_path / "樹",
        起點commit=起點commit,
    )

    assert 結果.終局 is 結果代碼.成功, f"兩顆都該跑成，缺口：{結果.缺口}"
    assert _工作樹數(專案) == 跑之前, "跑完的乾淨工作樹沒收掉，扇出每跑一次就多留幾棵"
    留下的分支 = _跑(專案, "branch", "--list", "nova/扇出-*").stdout.strip()
    assert 留下的分支 == "", (
        f"樹收掉了、每棵樹掛的那條本地分支還在：扇出每跑一次就多積幾條 nova/扇出-*：{留下的分支}"
    )


def test_樹收掉了分支還在時出的聲要講分支不准說樹留著(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`收掉工作樹` 有兩個失敗階段，扇出這一層不准把它們講成同一句話。

    階段一是 `worktree remove` 失敗——樹還在、現場留著，指去 `nova 線`
    （它讀 `git worktree list`）找得到，那句話是對的。
    階段二是**樹已經收掉、只剩 `branch -D` 失敗**：現場早就不存在了，這時再說
    「留下一棵有產出的工作樹，用 `nova 線` 找它」，人照著去 `nova 線` 會看到空的，
    然後把這件事當成 nova 自己記錯了——真正殘留的那條 `nova/扇出-*` 分支沒有人講，
    每跑一次扇出就多積一條。所以這一階段出的聲要指名**分支**。

    假 git 只攔甲那條分支的 `branch -D`，其餘全部委派給真的 git（照
    `test_工作樹.py::test_收掉工作樹刪不掉分支要上拋` 的記錄器）：乙那棵要真的
    收乾淨，才證明出聲的是「刪不掉的那一條」而不是每棵樹都喊一次。
    """
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造一個commit的repo(專案)
    樹根 = tmp_path / "樹"
    甲的分支 = f"nova/扇出-{樹根.name}-甲"
    乙的分支 = f"nova/扇出-{樹根.name}-乙"

    真的跑git = 工作樹模組.跑git

    def 刪甲的分支就失敗(根目錄: Path, *參數: str) -> subprocess.CompletedProcess[str]:
        if 參數[:3] == ("branch", "-D", 甲的分支):
            return subprocess.CompletedProcess(
                ["git", *參數],
                returncode=1,
                stdout="",
                stderr=f"error: cannot delete branch '{甲的分支}'\n",
            )
        return 真的跑git(根目錄, *參數)

    monkeypatch.setattr(工作樹模組, "跑git", 刪甲的分支就失敗)

    工作 = (_工作("甲"), _工作("乙"))

    def 執行一顆(工作項: 分支工作[str, None], 這顆上下文: 節點上下文) -> 節點成功[str]:
        # 兩顆都不寫檔：樹是乾淨的，`worktree remove` 一定過得去，
        # 這支才咬得到「只有刪分支這一步失敗」那一格。
        assert 這顆上下文.任務.工作目錄 == 樹根 / str(工作項.分支), "分支沒在自己那棵樹裡跑"
        return 節點成功(產出=_換掉內容(工作項.輸入, "什麼都沒寫"), 證據=(), 用量=None)

    with pytest.warns(UserWarning) as 出的聲:
        結果 = 帶著工作樹扇出(
            工作,
            執行一顆=執行一顆,
            上下文=_上下文(專案),
            政策=_政策(frozenset(工作項.分支 for 工作項 in 工作)),
            專案=專案,
            樹根=樹根,
            起點commit=起點commit,
        )

    assert 結果.終局 is 結果代碼.成功, f"收樹沒收乾淨不該把跑成的兩顆弄成失敗：{結果.缺口}"
    assert not (樹根 / "甲").exists(), "這支要咬的是『樹收掉了、分支還在』那一格，樹卻還在"
    assert _跑(專案, "branch", "--list", 甲的分支).stdout.strip() != "", (
        "假 git 沒攔到甲的 `branch -D`，殘留的分支根本不存在，這支測不到東西"
    )
    assert _跑(專案, "branch", "--list", 乙的分支).stdout.strip() == "", "乙那條沒攔，該收乾淨"

    講的話 = [str(一則.message) for 一則 in 出的聲]
    assert len(講的話) == 1, f"只有甲刪不掉分支，該只出一次聲：{講的話}"
    只此一句 = 講的話[0]
    assert 甲的分支 in 只此一句, (
        f"沒指名殘留的是哪條分支，人不知道要 `git branch -D` 什麼：{只此一句}"
    )
    assert "分支" in 只此一句, f"出的聲沒講這是分支沒收掉，會被當成樹的問題：{只此一句}"
    assert "工作樹" not in 只此一句.replace(str(樹根 / "甲"), ""), (
        f"樹早就收掉了還說留了一棵工作樹，人去找會找到空的：{只此一句}"
    )
    assert "nova 線" not in 只此一句, (
        f"`nova 線` 讀的是 `git worktree list`，樹已經不在了，指過去是死路：{只此一句}"
    )

    assert _跑(專案, "branch", "-D", 甲的分支).returncode == 0  # 測試自己留下的殘骸要收乾淨


def test_有產出的樹留現場而且出聲指向nova線(tmp_path: Path) -> None:
    """寫過檔的樹收不掉是刻意的；但它必須出聲，而且講得出去哪裡找。

    `--force` 過去會把失敗現場銷毀，所以留著。留著又不出聲的話，
    殘骸就只在檔案系統裡，沒有人知道它存在。
    """
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造一個commit的repo(專案)
    樹根 = tmp_path / "樹"

    工作 = (_工作("甲"), _工作("乙"))

    def 執行一顆(工作項: 分支工作[str, None], 這顆上下文: 節點上下文) -> 節點成功[str]:
        (這顆上下文.任務.工作目錄 / 共用檔名).write_text("寫過了", encoding="utf-8")
        return 節點成功(產出=_換掉內容(工作項.輸入, "寫過了"), 證據=(), 用量=None)

    with pytest.warns(UserWarning, match="nova 線") as 出的聲:
        帶著工作樹扇出(
            工作,
            執行一顆=執行一顆,
            上下文=_上下文(專案),
            政策=_政策(frozenset(工作項.分支 for 工作項 in 工作)),
            專案=專案,
            樹根=樹根,
            起點commit=起點commit,
        )

    # **只數指向 `nova 線` 的那些。** `pytest.warns(...) as` 收的是區塊裡**全部**的
    # warning，不是只有 match 到的——CI 上 git 多吐兩則（「contains modified or
    # untracked files」那條）就變成 4，而那跟這支要驗的東西無關。
    # 實測 2026-09-01：本機 2、CI 4，同一份程式碼。
    指向線的 = [一則 for 一則 in 出的聲 if "nova 線" in str(一則.message)]
    assert len(指向線的) == 2, (
        f"兩棵有產出的樹都該出聲指向 `nova 線`，實際 {len(指向線的)} 次"
        f"（區塊裡全部的 warning 共 {len(出的聲)} 則）"
    )
    留下的 = [樹根 / "甲", 樹根 / "乙"]
    for 一棵 in 留下的:
        assert 一棵.is_dir(), f"有產出的樹被收掉了，現場沒了：{一棵}"
        assert str(一棵) in "".join(str(一聲.message) for 一聲 in 出的聲), (
            f"出聲了但沒講路徑，找不回來：{一棵}"
        )

    for 一棵 in 留下的:  # 測試自己留下的殘骸要收乾淨，不能讓 worktree 越跑越多
        assert _跑(專案, "worktree", "remove", "--force", str(一棵)).returncode == 0


def test_落點被佔住的分支開不出樹而整批照跑(tmp_path: Path) -> None:
    """`OSError → 開不出工作樹` 這條轉換要真的走得到，用真的 git 佔住落點來走。

    墊片塞一個 `開不出工作樹` 進 runner 只證明 runner 會跳掉它，
    證明不了「開樹失敗時真的會落成那一格」——一棵開不出來的樹不准弄掛整批。
    """
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造一個commit的repo(專案)
    樹根 = tmp_path / "樹"
    佔住的落點 = 樹根 / "甲"
    佔住的落點.mkdir(parents=True)
    (佔住的落點 / "早就有人在這裡.txt").write_text("別人的東西", encoding="utf-8")
    跑之前 = _工作樹數(專案)

    工作 = (_工作("甲"), _工作("乙"))
    派過誰: list[分支識別碼] = []
    鎖 = threading.Lock()

    def 執行一顆(工作項: 分支工作[str, None], 這顆上下文: 節點上下文) -> 節點成功[str]:
        with 鎖:
            派過誰.append(工作項.分支)
        assert 這顆上下文.任務.工作目錄 == 樹根 / "乙", "乙該在自己那棵樹裡跑"
        return 節點成功(產出=_換掉內容(工作項.輸入, "跑過了"), 證據=(), 用量=None)

    結果 = 帶著工作樹扇出(
        工作,
        執行一顆=執行一顆,
        上下文=_上下文(專案),
        政策=_政策(frozenset(工作項.分支 for 工作項 in 工作)),
        專案=專案,
        樹根=樹根,
        起點commit=起點commit,
    )

    assert 派過誰 == [分支識別碼("乙")], f"開不出樹的那顆不准派，也不准整批掛掉：{派過誰}"
    assert [項.分支 for 項 in 結果.分支結果] == [分支識別碼("乙")]
    assert 分支識別碼("甲") in 結果.缺口, "沒跑的分支要留在缺口裡才看得見"
    assert 結果.終局 is 結果代碼.護欄, "必要分支開不出樹是未知，不是確定失敗"
    assert (佔住的落點 / "早就有人在這裡.txt").exists(), "開樹失敗不准動別人佔住的目錄"
    assert _工作樹數(專案) == 跑之前, "乙那棵乾淨的樹沒收掉"

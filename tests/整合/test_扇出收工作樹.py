"""扇出開出來的樹誰收、收不掉的怎麼看得見、開不出來的那一顆怎麼跳過。

隔離本身由 `test_扇出開工作樹.py` 守；這裡守的是它的另一半——**留下來的樹**。
這台機器上二十幾棵 worktree 就是這一半沒人守的樣子：乾淨的樹沒回收，
有產出的樹留了現場卻沒有人講它在哪裡。

三支測試對到三件事：跑完乾淨的收掉、有產出的留現場並且出聲指向 `nova 線`、
落點被佔住的那一顆落成 `開不出工作樹` 而整批照跑。
"""

import threading
from pathlib import Path

import pytest

from nova.契約.扇出 import 分支工作
from nova.契約.節點 import 分支識別碼, 節點上下文, 節點成功, 結果代碼
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

    assert len(出的聲) == 2, f"兩棵有產出的樹都該出聲，實際 {len(出的聲)} 次"
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

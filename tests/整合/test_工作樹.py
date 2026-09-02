"""工作樹隔離：並行的分支各自在自己的 git worktree 裡跑，互相看不到。

住整合層不住單元層：這裡真的會 fork git，開一個 worktree 是檔案系統操作。

這一支釘的是最核心的形狀——**開在指定的 commit 上、掛在自己那條分支上、
不影響主工作區**。
起點是 commit 不是 HEAD，這樣它跟成果帳的 `rollback_point` 是同一個值；
分支跑完要回頭看「它從哪裡長出來的」時，兩邊對得起來。
"""

import subprocess
from pathlib import Path

import pytest

from nova.載體 import 工作樹 as 工作樹模組
from nova.載體.工作樹 import 收掉工作樹, 收集證據, 開一個工作樹


def _跑(根: Path, *參數: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *參數], cwd=根, capture_output=True, text=True, check=False)


def _造有兩個commit的repo(根: Path) -> str:
    """造一個 repo：第一版 → 第二版。回傳**第一版**的完整 sha。

    刻意讓 HEAD 停在第二版：起點若被實作寫死成 HEAD，測試會當場看到第二版的內容。
    """
    for 指令 in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "測試@例子"),
        ("config", "user.name", "測試"),
    ):
        assert _跑(根, *指令).returncode == 0

    (根 / "共用.txt").write_text("第一版\n", encoding="utf-8")
    assert _跑(根, "add", "-A").returncode == 0
    assert _跑(根, "commit", "-q", "-m", "第一版").returncode == 0
    起點 = _跑(根, "rev-parse", "HEAD").stdout.strip()

    (根 / "共用.txt").write_text("第二版\n", encoding="utf-8")
    assert _跑(根, "add", "-A").returncode == 0
    assert _跑(根, "commit", "-q", "-m", "第二版").returncode == 0
    return 起點


def test_開一個工作樹_停在起點commit且不動主工作區(tmp_path: Path) -> None:
    """開出來的工作樹是起點 commit 那一版、掛在自己那條分支上、寫它不會弄髒主工作區。"""
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    落點 = tmp_path / "工作樹" / "分支甲"

    回傳 = 開一個工作樹(專案, 落點=落點, 起點commit=起點commit, 分支="nova/測試-甲")

    assert 回傳 == 落點, "要回傳落點本身，呼叫端才知道那個分支該在哪裡跑"
    assert (落點 / "共用.txt").read_text(encoding="utf-8") == "第一版\n", (
        "工作樹要停在指定的起點 commit，不是 HEAD——起點跟成果帳的 rollback_point 是同一個值"
    )
    assert _跑(落點, "rev-parse", "HEAD").stdout.strip() == 起點commit

    # 有名字的分支：收尾要推的 `HEAD:refs/heads/<分支>` 從第一秒就得有家。
    assert _跑(落點, "symbolic-ref", "--short", "HEAD").stdout.strip() == "nova/測試-甲", (
        "工作樹必須掛在派工給的那條分支上，detached 的樹推不出去"
    )

    # 隔離：在工作樹裡寫的東西，主工作區看不到。
    (落點 / "只有分支甲看得到.txt").write_text("甲的產出\n", encoding="utf-8")
    assert not (專案 / "只有分支甲看得到.txt").exists(), "工作樹的產出漏回主工作區了，等於沒隔離"
    assert (專案 / "共用.txt").read_text(encoding="utf-8") == "第二版\n", "主工作區被工作樹動到了"


def test_開工作樹一定要把建分支參數交給git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """直接釘 `-b <分支>` 這個參數本身：撞名時要靠它失敗，不是靠事後補救。

    記錄器仍然委派給真的 git：這支測的是實作怎麼叫 git，不是拿假 git 自問自答。
    """
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    真的跑git = 工作樹模組.跑git
    記錄: list[tuple[str, ...]] = []

    def 記錄器(根目錄: Path, *參數: str) -> subprocess.CompletedProcess[str]:
        記錄.append(參數)
        return 真的跑git(根目錄, *參數)

    monkeypatch.setattr(工作樹模組, "跑git", 記錄器)

    落點 = tmp_path / "工作樹" / "分支己"

    開一個工作樹(專案, 落點=落點, 起點commit=起點commit, 分支="nova/測試-己")

    assert ("worktree", "add", "-b", "nova/測試-己", str(落點), 起點commit) in 記錄, (
        f"沒有把 `-b <分支>` 交給 git，工作樹會開成 detached，收尾推不出去：{記錄}"
    )


def test_開不出工作樹就raise_不准退回主工作區(tmp_path: Path) -> None:
    """起點指不到 commit 時要當場 raise。把這個拒絕改成 fallback，這支就紅。"""
    專案 = tmp_path / "專案"
    專案.mkdir()
    _造有兩個commit的repo(專案)
    落點 = tmp_path / "工作樹" / "開不起來"

    with pytest.raises(OSError, match="開不出工作樹"):
        開一個工作樹(專案, 落點=落點, 起點commit="不存在的commit", 分支="nova/測試-開不起來")

    assert not 落點.exists(), "開不出來就不該留下半個工作樹"
    # 靜默 fallback 成共用主工作區是假隔離，比沒隔離更糟——它看起來像有。
    assert not (專案 / "工作樹").exists()


def test_主工作區沒提交的檔案在工作樹裡看不到(tmp_path: Path) -> None:
    """這是隔離在做事，不是 bug：分支只看得到已提交的狀態。

    釘住它是因為「任務依賴未提交的檔案」會神祕失敗，要讓人一眼看到原因。
    """
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    (專案 / "還沒提交.txt").write_text("主工作區的草稿\n", encoding="utf-8")

    落點 = 開一個工作樹(
        專案, 落點=tmp_path / "工作樹" / "分支乙", 起點commit=起點commit, 分支="nova/測試-乙"
    )

    assert not (落點 / "還沒提交.txt").exists(), (
        "主工作區沒提交的檔案跑進工作樹了，那就不是從 commit 長出來的"
    )


def test_收集證據要含未追蹤的新檔(tmp_path: Path) -> None:
    """TDD 的產出整包都是新增檔案，`git diff` 看不到——漏了等於成果憑空消失。"""
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    落點 = 開一個工作樹(
        專案, 落點=tmp_path / "工作樹" / "分支丙", 起點commit=起點commit, 分支="nova/測試-丙"
    )

    (落點 / "新增的測試.py").write_text("def test_甲(): pass\n", encoding="utf-8")
    (落點 / "共用.txt").write_text("分支丙改的\n", encoding="utf-8")

    證據 = 收集證據(落點)

    assert "新增的測試.py" in 證據, "未追蹤的新檔沒進證據，那個分支的產出會整包不見"
    assert "def test_甲(): pass" in 證據
    assert "分支丙改的" in 證據, "改動過的舊檔也要在證據裡"


def test_收掉乾淨的工作樹(tmp_path: Path) -> None:
    """跑完而且乾淨的工作樹要收得掉，不然磁碟上會越積越多。

    樹掛的那條本地分支要跟樹一起收：誰開的誰收。留著的話每跑一次扇出就多積
    幾條沒人用的 `nova/*`，而且下一次同名派工會撞在上面。
    """
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    落點 = 開一個工作樹(
        專案, 落點=tmp_path / "工作樹" / "分支丁", 起點commit=起點commit, 分支="nova/測試-丁"
    )

    收掉工作樹(落點)

    assert not 落點.exists()
    assert "分支丁" not in _跑(專案, "worktree", "list").stdout
    assert _跑(專案, "branch", "--list", "nova/測試-丁").stdout.strip() == "", (
        "樹收掉了分支還在：下一次同名派工會撞在一條沒人用的分支上"
    )


def test_問不出這棵樹掛哪條分支就不准動樹(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """查分支這一道 git 壞掉（rc 128）要當場 raise，而且**樹一根寒毛都不准動**。

    `git symbolic-ref -q --short HEAD` 有三態：rc 0 是分支名、rc 1 是 detached
    （`-q` 讓它靜默）、其他非零是「這道 git 根本沒問成」（壞路徑實測 128）。
    把後兩者混成同一件事的後果是：問不出來就當 detached、樹照收、分支不刪，
    留下一條沒人知道存在的 `nova/*`——而且現場已經被收掉了，沒有東西可查。

    所以 raise 要發生在 `worktree remove` **之前**：查不出來就整件事不做，
    樹留著給人看。這支同時釘住這個順序（紀錄裡不准出現 `worktree remove`）。

    假 git 只攔 `symbolic-ref`，其餘全部委派給真的 git。攔的是**前綴**不是整串
    參數：`--short HEAD` 跟 `-q --short HEAD` 都要攔得到，否則實作改了旗標之後
    這支會變成「真 git 回 0、沒 raise」——紅的原因就不是它要測的那件事了。
    """
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    落點 = tmp_path / "工作樹" / "分支辛"
    # 這棵樹刻意用真的 git 直接開，不走 `開一個工作樹`：這支釘的是 `收掉工作樹`
    # 怎麼處理「查分支失敗」，用不著把開樹那一半也綁進來當前提。
    assert _跑(專案, "worktree", "add", "-b", "nova/測試-辛", str(落點), 起點commit).returncode == 0

    真的跑git = 工作樹模組.跑git
    紀錄: list[tuple[str, ...]] = []

    def 問分支就壞掉(根目錄: Path, *參數: str) -> subprocess.CompletedProcess[str]:
        紀錄.append(參數)
        if 參數[:1] == ("symbolic-ref",):
            return subprocess.CompletedProcess(
                ["git", *參數],
                returncode=128,
                stdout="",
                stderr="fatal: not a git repository: '.git'\n",
            )
        return 真的跑git(根目錄, *參數)

    monkeypatch.setattr(工作樹模組, "跑git", 問分支就壞掉)

    with pytest.raises(OSError) as 例外:
        收掉工作樹(落點)

    assert not any(參數[:2] == ("worktree", "remove") for 參數 in 紀錄), (
        f"分支都問不出來了還是把樹收掉了，現場沒了也沒人知道分支還在：{紀錄}"
    )
    assert 落點.exists(), "raise 之前樹就被動過了：查分支失敗時什麼都不該做"
    assert str(落點) in str(例外.value), "例外沒指名是哪棵樹，人不知道要去看哪個現場"


def test_收掉工作樹刪不掉分支要上拋(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """樹收掉了但分支刪不掉，要當場 raise，不准靜默吞掉。

    吞掉的後果是「看起來收乾淨了，其實分支還在」：下一次同名派工會撞在一條沒人
    用的分支上，而人手上沒有任何線索知道要去刪它。例外訊息要同時指名分支與樹，
    收不乾淨的現場才找得到。

    假 git 只攔 `branch -D` 那一道，其餘全部委派給真的 git（照
    `test_問不出這棵樹掛哪條分支就不准動樹` 的記錄器）：這支測的是實作怎麼處理
    git 的失敗，不是拿假 git 自問自答。
    """
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    落點 = 開一個工作樹(
        專案, 落點=tmp_path / "工作樹" / "分支庚", 起點commit=起點commit, 分支="nova/測試-庚"
    )

    真的跑git = 工作樹模組.跑git
    攔到的: list[tuple[str, ...]] = []

    def 刪分支就失敗(根目錄: Path, *參數: str) -> subprocess.CompletedProcess[str]:
        if 參數[:2] == ("branch", "-D"):
            攔到的.append(參數)
            return subprocess.CompletedProcess(
                ["git", *參數],
                returncode=1,
                stdout="",
                stderr="error: cannot delete branch 'nova/測試-庚'\n",
            )
        return 真的跑git(根目錄, *參數)

    monkeypatch.setattr(工作樹模組, "跑git", 刪分支就失敗)

    with pytest.raises(OSError, match="分支") as 例外:
        收掉工作樹(落點)

    assert 攔到的 == [("branch", "-D", "nova/測試-庚")], (
        f"沒有去刪這棵樹掛的分支，或刪的不是它：{攔到的}"
    )
    assert "nova/測試-庚" in str(例外.value), "例外沒指名刪不掉的是哪條分支，人不知道要去刪什麼"
    assert str(落點) in str(例外.value), "例外沒指名是哪棵樹，收不乾淨的現場找不到"


def test_失敗的工作樹不准收掉_路徑留在例外裡(tmp_path: Path) -> None:
    """髒的工作樹收不掉是特性不是障礙：現場要留著給人看，不准 `--force` 硬過。"""
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    落點 = 開一個工作樹(
        專案, 落點=tmp_path / "工作樹" / "分支戊", 起點commit=起點commit, 分支="nova/測試-戊"
    )
    (落點 / "失敗現場.txt").write_text("跑到一半死掉\n", encoding="utf-8")

    with pytest.raises(OSError, match="失敗現場|收不掉工作樹") as 例外:
        收掉工作樹(落點)

    assert str(落點) in str(例外.value), "收不掉時要把路徑講出來，不然沒人找得到現場"
    assert (落點 / "失敗現場.txt").exists(), "失敗現場被 --force 銷毀了"

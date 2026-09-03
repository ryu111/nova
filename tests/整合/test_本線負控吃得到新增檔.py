"""本線負控選到的那幾把刀，從 git 清單一路到 pytest 收集都要對。

**真的叫 git，所以住整合層不住單元層**——`tests/單元` 是提交閘唯一的測試規則，
混一支 fork 進去就是每次 commit 都付那個錢。

守的是本票最貴的那個假綠：新增一把刀＝新增一個 `登記們/<主題>.py`，
而新檔**不會出現在 `git diff` 裡**。只看 diff 的話「新增刀」這個最常見的情形
會選到 0 把、一路綠到 CI——比原本那個紅更難看出來。改既有那把刀是另一種形狀
（在 diff 裡、不在未追蹤清單裡），兩個來源缺一都是同一種假綠。

第二支往下守一格：清單算對了，`--登記檔` 也要真的接上 pytest 的收集才會少跑刀。
掛鉤沒接上的症狀是「全部照跑」或「全部被丟掉」，兩種都不會有人當場發現。

第三支守「清單算不出來」那一格：查基準的 git 指令自己失敗（`origin/main` 還沒 fetch、
淺 clone、遠端名字不叫 origin）時，空的 stdout 跟「本線真的沒動過登記檔」長得一模一樣。
把前者當成後者就是閘綠而一把刀都沒跑——本票要消掉的那個紅，換成一個更難看出來的綠。
這一支走 `建規則表` 登記的那條 `registered-mutation-diff` 的 `檢查`，不是自己重接一份，
所以那個 `檢查` 被換成恆綠的 no-op 時它也會紅。

第四支守登記模組的認法：package 標記只有 `__init__.py` 這一個檔名（`tests/負控/登記.py`
的收集就是這樣認的）。載體那側認得比它寬的話，合法檔名會在本線被靜靜漏掉、只有 CI 才紅，
而兩側各認一套的症狀永遠是假綠。

第五支守**清單非空那條正路**：前面幾支只穿得過「git 失敗就提前返回」與純函式那兩格，
所以「算出清單之後真的去跑刀」那兩行被換成恆綠的 no-op 時，這個檔照樣全綠。
那正是本票整張票要防的形狀——閘綠、一把刀都沒跑。這一支釘的是：清單非空時
runner 真的被叫起來、拿到的是那幾個檔，而且它的判定就是閘的判定，不准被吞掉。
"""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from nova.載體 import 規則表 as _規則表模組
from nova.載體.規則表 import 動過的登記檔們, 建規則表, 負控檔們
from tests.負控.登記們.本線負控 import 登記 as _本檔登記的刀們

_登記們 = "tests/負控/登記們"
_專案根 = Path(__file__).resolve().parents[2]
#: 每把刀都是這一支測試的一個參數化案例；收集得到哪幾把就是篩選的結果。
_刀那支測試 = "tests/負控/test_登記的變異會被殺.py"
_刀的節點前綴 = "::test_登記的變異會被殺["
#: 暫時 repo 裡沒有 user 設定，`commit` 會當場拒絕，所以每次都帶著身分跑。
_跑git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


def _解掉pytest的轉義(識別: str) -> str:
    r"""pytest 把非 ASCII 的參數 id 轉義成 `\uXXXX`，這裡解回中文。

    這一手只活在測試裡：載體那側正是為了不必複製這份轉義規則，
    才走 `--登記檔` 這個選項而不是 nodeid（票 24）。
    """
    return 識別.encode("utf-8").decode("unicode_escape")


def _收集到的刀識別(*額外參數: str) -> frozenset[str]:
    """真的跑一次 pytest 收集，回收集得到的刀（`識別`）。"""
    結果 = subprocess.run(  # noqa: S603
        (
            "uv",
            "run",
            "pytest",
            _刀那支測試,
            "--collect-only",
            "-q",
            "-p",
            "no:randomly",
            *額外參數,
        ),
        cwd=_專案根,
        capture_output=True,
        text=True,
        check=False,
    )
    assert 結果.returncode == 0, (
        f"收集本身就失敗了（參數 {額外參數}）：\n{結果.stdout[-2000:]}\n{結果.stderr[-2000:]}"
    )
    return frozenset(
        _解掉pytest的轉義(行[行.index("[") + 1 : 行.rindex("]")])
        for 行 in 結果.stdout.splitlines()
        if _刀的節點前綴 in 行 and 行.endswith("]")
    )


def _建一個有origin_main的repo(在: Path) -> None:
    """建一個已經有 `登記們/本來就有的.py` 的 repo，並讓 `origin/main` 指到那一筆。

    沒有真的遠端：遠端追蹤 ref 直接 `update-ref` 出來，比起一個真的 remote，
    這裡要的只是「`origin/main` 解得開」。
    """
    subprocess.run([*_跑git, "init", "-q", "-b", "main"], cwd=在, check=True)
    目錄 = 在 / _登記們
    目錄.mkdir(parents=True)
    (目錄 / "本來就有的.py").write_text("登記 = ()\n", encoding="utf-8")
    (目錄 / "改過的.py").write_text("登記 = ()\n", encoding="utf-8")
    subprocess.run([*_跑git, "add", "."], cwd=在, check=True)
    subprocess.run([*_跑git, "commit", "-qm", "起頭"], cwd=在, check=True)
    subprocess.run([*_跑git, "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=在, check=True)


def test_還沒add的新登記檔也算本線動過(tmp_path: Path) -> None:
    """兩個來源都要算進清單，而這條線沒動過的登記檔不准混進來。

    兩個來源缺一都是假綠：未 add 的新檔不在 `git diff` 裡（新增一把刀就是這種形狀），
    改過又提交的檔不在 `git ls-files --others` 裡（改既有那把刀就是這種形狀）。
    最後那半同樣要釘：回一整個 `登記們/` 也會讓前面兩半綠，
    但那就是把 CI 的全量 220 把搬進每一次判準，正是這條線不做的事。
    """
    _建一個有origin_main的repo(tmp_path)
    (tmp_path / _登記們 / "新的.py").write_text("登記 = ()\n", encoding="utf-8")
    (tmp_path / _登記們 / "改過的.py").write_text("登記 = ()  # 改了一手\n", encoding="utf-8")
    subprocess.run([*_跑git, "commit", "-qam", "改一把既有的刀"], cwd=tmp_path, check=True)

    清單 = 動過的登記檔們(tmp_path)

    assert f"{_登記們}/新的.py" in 清單, (
        f"新增但還沒 add 的登記檔沒被算成本線動過（`git diff` 看不到新檔）：{list(清單)}"
    )
    assert f"{_登記們}/改過的.py" in 清單, (
        f"改過又提交的登記檔沒被算成本線動過（`git ls-files --others` 看不到已追蹤的檔）："
        f"{list(清單)}"
    )
    assert f"{_登記們}/本來就有的.py" not in 清單, (
        f"這條線沒動過的登記檔也被算進來了，本線負控會退化成全量：{list(清單)}"
    )


def test_登記檔選項真的把別檔的刀deselect掉() -> None:
    """`--登記檔` 掛上 pytest 的收集之後，只留下那個模組登記的刀，別檔的刀要被 deselect。

    這一格走**真的 pytest 收集**（本 repo、`--collect-only`），不是直接呼叫那兩個純函式：
    單元層那支驗的是篩選邏輯本身，掛鉤有沒有真的接上（`pytest_addoption` 寫錯位置、
    `pytest_collection_modifyitems` 認不出刀）只有跑一次收集才看得出來，
    而那種壞法的症狀是**全部照跑**或**全部被丟掉**，兩種都不會有人當場發現。

    同時釘反面：不下選項時收集不准變窄——CI 那條全量 220 把靠的就是「沒有選項」。
    """
    這個檔 = f"{_登記們}/本線負控.py"
    本檔的刀們 = frozenset(一筆.識別 for 一筆 in _本檔登記的刀們)
    assert 本檔的刀們, f"{這個檔} 一把刀都沒登記，這支測試在測空氣"

    全部 = _收集到的刀識別()
    指名這個檔 = _收集到的刀識別("--登記檔", 這個檔)

    assert 指名這個檔 == 本檔的刀們, (
        f"指名 {這個檔} 之後收集到的刀不是那個檔登記的那幾把："
        f"多了 {sorted(指名這個檔 - 本檔的刀們)}、少了 {sorted(本檔的刀們 - 指名這個檔)}"
    )
    assert 本檔的刀們 < 全部, (
        f"不下 `--登記檔` 時收集到的刀不比指名一個檔時多，收集被意外縮窄了"
        f"（CI 的全量靠的就是沒有選項）：{len(全部)} 把"
    )


def test_查不到基準時閘要紅而不是當成本線沒動過(tmp_path: Path) -> None:
    """查基準的 git 指令失敗時，`registered-mutation-diff` 要紅，而且證據指名查不到什麼。

    「git 失敗」與「本線真的沒動過登記檔」在 stdout 上都是空的，分不出來就只能 fail-closed：
    前者當成後者的話，閘綠、一把刀都沒跑，比原本那個 CI 紅更難看出來。
    證據要講出是哪個基準解不開，不然看到紅的人不知道要去 fetch 什麼。
    """
    subprocess.run([*_跑git, "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    目錄 = tmp_path / _登記們
    目錄.mkdir(parents=True)
    (目錄 / "本來就有的.py").write_text("登記 = ()\n", encoding="utf-8")
    subprocess.run([*_跑git, "add", "."], cwd=tmp_path, check=True)
    subprocess.run([*_跑git, "commit", "-qm", "起頭"], cwd=tmp_path, check=True)
    # 刻意不 `update-ref refs/remotes/origin/main`：這就是「基準解不開」那個現場。
    # 也刻意不留未追蹤的檔——留了就換成另一條路徑（清單非空），驗不到這一格。

    這條規則 = {一條.代碼: 一條 for 一條 in 建規則表(tmp_path)}["registered-mutation-diff"]
    通過, 證據 = 這條規則.檢查()

    assert not 通過, f"`origin/main` 解不開卻讓閘綠了，這是一把刀都沒跑的假綠：{證據!r}"
    assert "origin/main" in 證據, (
        f"證據沒指名解不開的是哪個基準，看到紅的人不知道要 fetch 什麼：{證據!r}"
    )


def test_清單非空時真的去跑那幾個檔的刀_而且跑出來的判定就是閘的判定(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """動過的登記檔非空時，閘要把那幾個檔交給 runner 跑，並照著 runner 的判定回報。

    清單算對了、選項也接上了，中間那一段仍然可以整段不跑：直接回綠就是閘綠而
    一把刀都沒跑，跟本票原本要消掉的那個 CI 紅比起來更難看出來，而且前面幾支
    只穿得過「git 失敗」那條提前返回，不會有人當場發現。

    所以這裡釘三件事：runner 真的被叫起來一次、它拿到的是這條線動過的那幾個檔
    （不是整個 `登記們/`、也不是空的），以及它說紅時閘就是紅、它的話進得了證據
    ——證據被吞掉的話，看到紅的人不知道是哪一把刀死了。
    """
    _建一個有origin_main的repo(tmp_path)
    新的那把 = f"{_登記們}/新的.py"
    (tmp_path / 新的那把).write_text("登記 = ()\n", encoding="utf-8")
    # 規則表先建起來再換掉 runner：別條規則是在建表當下就把指令包好的，
    # 換早了會連它們一起換掉，這一支就看不出是誰叫的。
    這條規則 = {一條.代碼: 一條 for 一條 in 建規則表(tmp_path)}["registered-mutation-diff"]

    叫過的指令們: list[tuple[str, ...]] = []
    刀說的話 = "[registered-mutation] SURVIVED：檢查結果上的等待數字寫死成零"

    def 假的外部指令(根目錄: Path, *指令: str) -> Callable[[], tuple[bool, str]]:
        def 跑() -> tuple[bool, str]:
            叫過的指令們.append((str(根目錄), *指令))
            return False, 刀說的話

        return 跑

    monkeypatch.setattr(_規則表模組, "_外部指令", 假的外部指令)

    通過, 證據 = 這條規則.檢查()

    assert len(叫過的指令們) == 1, (
        f"動過的登記檔非空，runner 卻沒被叫起來（或被叫了不只一次）：{叫過的指令們}"
        "——閘綠而一把刀都沒跑就是本票要消掉的那個假綠"
    )
    根, 工具, *參數 = 叫過的指令們[0]
    assert 根 == str(tmp_path), f"刀跑在別的根目錄上，選到的檔對不上：{根}"
    assert 工具 == "pytest", f"跑刀的不是 pytest：{工具}"
    assert all(檔 in 參數 for 檔 in 負控檔們), (
        f"指令裡沒有負控檔（`負控檔們` 是唯一來源），刀那支測試根本不會被收集到：{參數}"
    )
    相鄰的兩個 = set(zip(參數, 參數[1:], strict=False))
    assert ("--登記檔", 新的那把) in 相鄰的兩個, (
        f"這條線新增的登記檔沒被指名給 pytest，選到的會是 0 把或全量：{參數}"
    )
    assert ("--登記檔", f"{_登記們}/本來就有的.py") not in 相鄰的兩個, (
        f"這條線沒動過的登記檔也被指名了，本線負控退化成全量：{參數}"
    )
    assert 通過 is False, f"runner 說刀紅了，閘卻是綠的：{證據!r}"
    assert 刀說的話 in 證據, f"runner 的話沒進到證據裡，看到紅的人不知道是哪一把刀死了：{證據!r}"


def test_檔名裡帶__init__的登記檔不准被當成package標記漏掉(tmp_path: Path) -> None:
    """package 標記只有 `__init__.py` 這一個檔名，別的檔名帶著 `__init__` 也是登記模組。

    收集那側（`tests/負控/登記.py`）認的就是精確檔名，載體這側認得比它寬的話，
    CI 收得到、跑得到的刀在本線被靜靜跳過——兩側對登記模組的認法必須是同一套。
    """
    _建一個有origin_main的repo(tmp_path)
    合法檔名 = "主題__init__檢查.py"
    (tmp_path / _登記們 / 合法檔名).write_text("登記 = ()\n", encoding="utf-8")
    (tmp_path / _登記們 / "__init__.py").write_text("", encoding="utf-8")

    清單 = 動過的登記檔們(tmp_path)

    assert f"{_登記們}/{合法檔名}" in 清單, (
        f"檔名裡帶 `__init__` 的登記檔被當成 package 標記漏掉了，"
        f"CI 跑得到它、本線跑不到：{list(清單)}"
    )
    assert f"{_登記們}/__init__.py" not in 清單, (
        f"`__init__.py` 是 package 標記、沒有 `登記` 屬性，餵給刀會當場炸：{list(清單)}"
    )

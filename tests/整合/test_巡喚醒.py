"""守「巡發射之前先證明自己不站在主工作區裡」與「配額由現在在跑幾條算出來」。

巡是那個**定期醒來、在別人的樹上叫醒接續票**的程序。它最危險的失敗不是漏叫，
是**站錯地方**：如果醒來的那個 nova 就是主工作區裡的那一份，它會拿主工作區當
工作目錄發射，把人正在編輯的樹交給一條工作流。所以三道自檢擺在最前面，
任何一道不過就是 `阻擋`（2），而且**一條都不准發射**。

第二件事是配額。本地腦一條 3.8 GB、並行上限 4 條，所以「這一輪能叫幾條」不是
一個固定數字，而是 `最多同時線數 − 現在在跑幾條`，再跟「一次最多喚醒」取小的。
只看「一次最多喚醒」的話，四條都在跑時巡照樣再疊兩條上去——那是把上限當成
下限用。

## 這幾支測試對 `巡.py` 要求的接縫

發射不准真的發生（覆蓋率也追不到子程序），所以下面這幾個名字要是
**`巡.py` 的模組層名字**，測試才拉得住：

- `發射背景程序`：從 `命令列` 轉公開的那一份，喚醒走它（**不是 `_背景起一條線`**）。
- `查並行現況`：配額的分母。
- `巡一輪`：23-1 的判定，在自檢這幾格裡它一次都不該被叫到。

自檢 (c)（巡自己的樹乾不乾淨）**不留假接縫**：測試自己開一棵 tmp 的 git 樹
再 chdir 進去，乾淨那格就是真的沒有未提交的檔案、不乾淨那格就是真的多了一個
沒進 git 的檔。把它換成一個永遠回 True 的替身，(c) 整條被拿掉也不會有人紅。

另外兩個名字被固定負控吊著錨點（`tests/負控/登記們/巡喚醒.py`），
所以簽名那一行要照樣長出來：`def 載體不在專案底下(專案: Path) -> bool:`
（自檢 (a)）與 `def 這次的配額(專案: Path) -> int:`（`最多同時線數` 減掉
在跑的線數，再跟 `一次最多喚醒` 取小）。
"""

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import nova
from nova.契約.線觀測 import 線現況
from nova.契約.退出碼 import 放行, 阻擋
from nova.載體 import 巡 as 巡模組
from nova.載體.命令列 import 主程式
from nova.載體.巡 import 一次最多喚醒, 一輪判定, 候選票, 最多同時線數

#: 這個 nova 的原始碼倉庫根（`src/nova/__init__.py` 往上三層）。
#: 自檢 (a) 說的「載體就在 `--專案` 底下」就是拿這裡跟 `--專案` 比。
_載體所在的倉庫 = Path(nova.__file__).resolve().parents[2]


def _一條線(名字: str, *, 在跑嗎: bool | None) -> 線現況:
    """配額只數 `在跑嗎 is True`，所以其餘欄位一律留空，不拿 0 頂替。"""
    return 線現況(
        名字=名字,
        在跑嗎=在跑嗎,
        跑多久=None,
        啟動時間=None,
        目前階段=None,
        上一次=None,
        護欄原因=None,
        未提交檔案數=None,
        基底落後數=None,
    )


def _到期一張(根: Path, 序: int) -> 候選票:
    """一張到期票加上它自己的樹。檔名第一段是時戳——巡照它排序。"""
    樹 = 根 / f"nova-wt-{序}"
    (樹 / "收件匣").mkdir(parents=True, exist_ok=True)
    票 = 樹 / "收件匣" / f"2026090{序}T040000Z-接續-第{序}張.md"
    票.write_text(f"# 第{序}張\n", encoding="utf-8")
    return 候選票(票=票, 樹=樹)


def _同樹裡更早的孤兒(一張: 候選票) -> 候選票:
    """在到期票**自己那棵樹**的收件匣裡，再擺一張時戳更早的孤兒票。

    一棵樹只放一張票的話，「叫錯票」這件事根本沒有形狀：不管巡選中的是哪一張，
    子程序在那棵樹裡都只找得到同一張。真實的樹是接續票疊接續票的，而收件匣
    照檔名拿最前面那一件——所以更早的那張要是判定說「不准叫」的孤兒，巡就得
    在發射的時候說得出「我要的是後面那一張」。
    """
    孤兒 = 一張.樹 / "收件匣" / "20260101T000000Z-孤兒-沒人接的那張.md"
    孤兒.write_text("# 孤兒\n", encoding="utf-8")
    return 候選票(票=孤兒, 樹=一張.樹)


@pytest.fixture
def 假發射器(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """把發射攔下來記帳。

    **測試裡不准真的生出子程序**：那條路覆蓋率追不到，而且失手的那次會在
    別人的工作樹上叫醒一顆模型。
    """
    發射了: list[dict[str, Any]] = []

    def 記下來不發射(參: list[str], **其餘: Any) -> None:
        發射了.append({"參": list(參), **其餘})

    monkeypatch.setattr(巡模組, "發射背景程序", 記下來不發射)
    return 發射了


@pytest.fixture
def 狀態根(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """單例鎖與巡自己的 `狀態.json` 都住狀態根，測試裡不准落到真的 `~/.local`。"""
    根 = tmp_path / "state"
    根.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(根))
    return 根 / "nova"


@pytest.fixture
def daemon站的地方(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """巡自己站的那棵樹：乾淨、有 HEAD，而且**不在任何受測專案底下**。"""
    樹 = tmp_path / "daemon的樹"
    樹.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=樹, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=巡",
            "-c",
            "user.email=巡@例",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "起點",
        ],
        cwd=樹,
        check=True,
    )
    monkeypatch.chdir(樹)
    return 樹


@pytest.fixture
def 判定不准被叫到(monkeypatch: pytest.MonkeyPatch) -> None:
    """三道自檢是**開跑前**的事：擋得下來的那幾格，判定一次都不該跑起來。"""

    def 不准判定(*_: object, **__: object) -> 一輪判定:
        pytest.fail("自檢沒擋住：巡已經開始算這一輪要叫誰了")

    monkeypatch.setattr(巡模組, "巡一輪", 不准判定)


def _只給這些線(monkeypatch: pytest.MonkeyPatch, 線們: tuple[線現況, ...]) -> None:
    """配額的分母固定成這幾條，不去問真的機器上現在有誰在跑。"""

    def 假清查(_: Path) -> tuple[線現況, ...]:
        return 線們

    monkeypatch.setattr(巡模組, "查並行現況", 假清查)


def _到期就這幾張(
    monkeypatch: pytest.MonkeyPatch,
    到期: tuple[候選票, ...],
    *,
    孤兒: tuple[候選票, ...] = (),
) -> None:
    """判定是 23-1 的地盤，這裡只固定它的輸出，測發射那一段。"""
    判定 = 一輪判定(到期=到期, 孤兒=孤兒, 首輪票=(), 殘骸=(), 訊息們=())

    def 假判定(*_: object, **__: object) -> 一輪判定:
        return 判定

    monkeypatch.setattr(巡模組, "巡一輪", 假判定)


@pytest.mark.usefixtures("狀態根", "判定不准被叫到", "daemon站的地方")
@pytest.mark.parametrize("哪一格", ["載體就在專案底下", "現在就站在專案裡", "巡自己的樹不乾淨"])
def test_在主工作區底下跑就回2而且一條都不發射(
    哪一格: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    假發射器: list[dict[str, Any]],
) -> None:
    """三道自檢各一格：任一格中了就回 `阻擋`，而且發射器零次呼叫。

    三格擋的是同一件事的三個面向——**執行的那份 nova 是主工作區的那一份**、
    **醒來的人就站在主工作區裡**、**巡自己的樹上還有沒提交的東西**。
    第三格不能少：巡是背景醒來的，它自己的樹髒著就代表有人正在手改 daemon，
    這時候發射出去的線跑的是半套程式碼。原因要說得出是哪個路徑害的，只印一句
    「不能在主工作區跑」的話，人看不出該去修 cwd 還是修這支 nova 是哪裡來的。
    """
    專案 = tmp_path / "主專案"
    專案.mkdir()
    要出現在原因裡 = str(專案)
    if 哪一格 == "載體就在專案底下":
        專案 = _載體所在的倉庫
        要出現在原因裡 = str(專案)
    elif 哪一格 == "現在就站在專案裡":
        (專案 / "子目錄").mkdir()
        monkeypatch.chdir(專案 / "子目錄")
    else:
        # 不是替身：真的在 daemon 自己那棵 git 樹（fixture 已經 chdir 進去了）
        # 留一個沒進 git 的檔。
        daemon的樹 = Path.cwd()
        (daemon的樹 / "改到一半.py").write_text("# 沒提交\n", encoding="utf-8")
        要出現在原因裡 = str(daemon的樹)
    monkeypatch.setattr(sys, "argv", ["nova", "巡", "--專案", str(專案)])

    碼 = 主程式(["巡", "--專案", str(專案)])

    輸出 = capsys.readouterr()
    全部 = 輸出.out + 輸出.err
    assert 碼 == 阻擋, (
        f"{哪一格} 應該回 {阻擋}，實際 {碼}。\nstdout: {輸出.out}\nstderr: {輸出.err}"
    )
    assert 假發射器 == [], f"自檢沒過還是發射了 {len(假發射器)} 條：{假發射器}"
    assert 要出現在原因裡 in 全部, (
        f"擋下來的原因要指名是哪個路徑害的（這一格是 {要出現在原因裡}），實際印的是：{全部!r}"
    )


@pytest.mark.usefixtures("狀態根")
def test_已經有三條在跑時這次最多只叫一條(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    daemon站的地方: Path,
    假發射器: list[dict[str, Any]],
) -> None:
    """配額取小、選中的那一張要被指名、發射的 argv 是 `工作流` 的形狀。

    配額是 `最多同時線數 − 現在在跑幾條`，跟 `一次最多喚醒` 取小的那個。
    在跑的只數 `在跑嗎 is True`：`None` 是「清查不到」，把它算成在跑會讓巡在
    清查失靈的那天一條都不敢叫。到期五張、四條線的上限、已經三條在跑，
    所以這一輪只准出去一條，而且是檔名時戳最早的那張。

    那棵樹裡還躺著一張**更早的孤兒票**——判定說它不准叫。發射時只交出樹、
    不交出票的話，子程序在那個收件匣裡照檔名拿到的會是孤兒那張，巡就跑了一張
    自己判定為「不准叫」的票。所以 argv 要說得出選中的是哪一張。

    形狀本身也一起守：子命令換成 `工作流`（只換子命令那一格，不是把 argv 裡
    每個值等於 `巡` 的字串都改掉，也不是往 argv 最前面塞一個 `工作流`）。
    daemon 醒來的那一行是 `nova --根目錄 <daemon的樹> 巡 --專案 <主工作區>`——
    `--根目錄` 是頂層旗標，legal 而且必須留在子命令**前面**：搬到 `工作流`
    後面的話正式剖析器不認得它，直接退出 2，票一張都不會被叫醒。
    其餘：`--專案`／`--演練` 剝乾淨、補 `--從收件匣`、
    `--工作目錄` 指到這棵樹**而且只有一份**（留著舊的那份，程序觀測會讀到第一份，
    把這條線算到別棵樹頭上，下一輪配額就會再叫它一次）、其餘旗標原樣轉交。
    """
    assert (最多同時線數, 一次最多喚醒) == (4, 2), (
        "這支測試的算術（4−3＝1，比 2 小所以 1 贏）吊在這兩個常數上；"
        f"實際是 最多同時線數={最多同時線數}、一次最多喚醒={一次最多喚醒}"
    )
    專案 = tmp_path / "主專案"
    專案.mkdir()
    到期 = tuple(_到期一張(tmp_path / "樹們", 序) for 序 in range(1, 6))
    孤兒 = _同樹裡更早的孤兒(到期[0])
    # 倒著交出去：排序是巡的責任，不是呼叫端剛好給對了順序。
    _到期就這幾張(monkeypatch, tuple(reversed(到期)), 孤兒=(孤兒,))
    _只給這些線(
        monkeypatch,
        (
            _一條線("主工作區", 在跑嗎=False),
            _一條線("線甲", 在跑嗎=True),
            _一條線("線乙", 在跑嗎=True),
            _一條線("線丙", 在跑嗎=True),
            _一條線("清查不到的那條", 在跑嗎=None),
        ),
    )
    別人的樹 = tmp_path / "上一輪留在 argv 裡的樹"
    原argv = [
        "nova",
        # 頂層旗標，`巡` 不在第一格：daemon 真的是這樣被叫醒的。
        "--根目錄",
        str(daemon站的地方),
        "巡",
        "--專案",
        str(專案),
        "--喚醒來源",
        "schedule",
        "--工作目錄",
        str(別人的樹),
        # 值剛好就是「巡」這兩個字：換子命令不准把它一起換掉。
        "--帳本目錄",
        "巡",
        "--最多步數",
        "7",
    ]
    monkeypatch.setattr(sys, "argv", 原argv)

    碼 = 主程式(原argv[1:])

    assert 碼 == 放行, f"叫得動就是 {放行}，實際 {碼}"
    assert len(假發射器) == 1, f"配額 4−3＝1，卻發射了 {len(假發射器)} 條：{假發射器}"
    assert 假發射器[0]["在哪跑"] == 到期[0].樹, (
        f"該叫的是檔名最早的 {到期[0].票.name}（樹 {到期[0].樹}），"
        f"實際叫的是 {假發射器[0]['在哪跑']}"
    )

    參: list[str] = 假發射器[0]["參"]
    assert 參[:2] == ["--根目錄", str(daemon站的地方)], (
        f"`巡` 前面的頂層旗標要原樣留在子命令前面，實際 argv 開頭是 {參[:4]}"
    )
    assert 參[2] == "工作流", (
        f"換掉的是真正的子命令那一格，不是在 argv 最前面塞一個 `工作流`，實際 argv 開頭是 {參[:4]}"
    )
    assert 參.count("工作流") == 1, f"`工作流` 只准有一格：{參}"
    assert "巡" not in 參[:3], f"子命令那一格已經換成 `工作流`，不該還留著 `巡`：{參}"
    assert "--專案" not in 參 and not any(格.startswith("--專案=") for 格 in 參), (
        f"`--專案` 只有巡認得，要剝掉：{參}"
    )
    assert "--演練" not in 參, f"`--演練` 只有巡認得，要剝掉：{參}"
    assert "--從收件匣" in 參, f"喚醒是從那棵樹的收件匣接票：{參}"
    assert 參.count("--工作目錄") == 1, f"`--工作目錄` 只准有一份，實際：{參}"
    assert 參[參.index("--工作目錄") + 1] == str(到期[0].樹), (
        f"`--工作目錄` 要指到票自己那棵樹 {到期[0].樹}，實際：{參}"
    )
    assert 參[參.index("--喚醒來源") + 1] == "schedule", f"`--喚醒來源` 要原樣帶過去：{參}"
    assert 參[參.index("--帳本目錄") + 1] == "巡", (
        f"只換子命令那一格；值剛好叫「巡」的旗標不准被改成「工作流」：{參}"
    )
    assert 參[參.index("--最多步數") + 1] == "7", f"一輪的旗標要原樣轉給那條線：{參}"
    assert 到期[0].票.name in " ".join(參), (
        f"發射的 argv 要指名選中的那張票 {到期[0].票.name}，"
        f"不然那棵樹的收件匣照檔名先拿到的是孤兒 {孤兒.票.name}：{參}"
    )
    assert 孤兒.票.name not in " ".join(參), (
        f"孤兒 {孤兒.票.name} 判定說不准叫，不該出現在發射的 argv 裡：{參}"
    )


@pytest.mark.usefixtures("狀態根", "daemon站的地方")
def test_演練模式一條都不發射只印會叫誰(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    假發射器: list[dict[str, Any]],
) -> None:
    """`--演練` 只印這一輪**真的會叫的那幾張**，一條都不發射。

    印出來的名單要跟真的跑一輪一致：沒在跑的線是零條、配額 4−0＝4，
    跟 `一次最多喚醒 = 2` 取小的是 2，所以三張到期裡只有前兩張會被叫。
    連第三張也印出來的話，演練就在說一件跑起來不會發生的事。
    """
    專案 = tmp_path / "主專案"
    專案.mkdir()
    到期 = tuple(_到期一張(tmp_path / "樹們", 序) for 序 in range(1, 4))
    _到期就這幾張(monkeypatch, 到期)
    _只給這些線(monkeypatch, (_一條線("主工作區", 在跑嗎=False),))
    monkeypatch.setattr(sys, "argv", ["nova", "巡", "--專案", str(專案), "--演練"])

    碼 = 主程式(["巡", "--專案", str(專案), "--演練"])

    印的 = capsys.readouterr().out
    assert 碼 == 放行, f"演練跑完就是 {放行}，實際 {碼}"
    assert 假發射器 == [], f"--演練 一條都不准發射，實際發了 {len(假發射器)} 條：{假發射器}"
    assert "會叫" in 印的, f"演練要印「會叫：…」，實際印的是：{印的!r}"
    for 一張 in 到期[:2]:
        assert 一張.票.name in 印的, f"會叫的名單裡少了 {一張.票.name}：{印的!r}"
    assert 到期[2].票.name not in 印的, (
        f"配額只有 2，第三張這一輪不會被叫，不該出現在名單裡：{印的!r}"
    )

"""規則表：閘的 context（規格 §2.2 第一問）。

一條規則登記在這裡，才會有任何執行點跑它。想加規則就加在這裡，
不要在 `.pre-commit-config.yaml`／`gates.yml`／hook 設定裡塞邏輯——
那些地方的程式碼沒辦法測試，等於沒有保證。
"""

import hashlib
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from pathlib import Path, PurePosixPath

from nova.載體 import 機器額度
from nova.載體.serial佔比 import 檢查serial佔比
from nova.載體.本線負控 import 判定選到的刀
from nova.載體.架構閘 import 檢查架構落點
from nova.載體.機密 import 檢查機密
from nova.載體.測試數 import 檢查測試數
from nova.載體.程序 import 具名啟動
from nova.載體.規範落點 import 檢查規範落點
from nova.載體.語言 import 檢查繁體中文
from nova.載體.豁免登記 import 檢查ruff豁免
from nova.載體.閘 import 型別, 抽乾整池, 測試, 規則, 靜態

# CI 要跟 base branch 比，本機 commit 前跟 HEAD 比。用環境變數傳遞，
# 讓 .github/workflows/gates.yml 只放一個常數字串、不放判斷邏輯（薄轉接、厚 nova）。
# 變數名用 ASCII：CLAUDE.md 的 shell 變數名例外。
基準環境變數 = "NOVA_TEST_COUNT_BASE"

#: CPU 額度政策住在 `機器額度`（一個誰都能依賴的中立模組），這裡借過來用。
#: **名字留在規則表**：政策搬家是為了拆掉「閘鎖 → 規則表 → 閘 → 閘鎖」那個環，
#: 不該順便逼每個呼叫端改 import。
平行度 = 機器額度.平行度

#: 登記負控檔的**唯一來源**：`registered-mutation` 跑的就是這些檔。
#:
#: 所有「別再跑一次這些檔」的地方都從這裡推出來（見下面的 `負控檔排除參數`），
#: 所以新增負控檔只要加在這一行，那幾處會同時看到它，
#: 不會出現「負控跑了、別處忘了排除」而重複跑一次的分岔。
負控檔們: tuple[str, ...] = ("tests/負控/test_登記的變異會被殺.py",)

#: 排掉負控檔用的 `--ignore` 參數，由 `負控檔們` 推出來。
#: 用的地方：`pytest-parallel`（CI）與 `載體/判準.py` 的 `預設判準指令`。
#:
#: 負控檔歸 `registered-mutation` 跑，別處再收一次是同一件事做兩遍：
#: 實測拿掉 `pytest-parallel` 那次重複，61.97 → 17.62 秒。
#: 標成 `serial` 不能代替——那只是把重複的帳從平行換到序列，重複本身還在。
負控檔排除參數 = tuple(f"--ignore={檔}" for 檔 in 負控檔們)

#: 每把登記負控刀住的目錄。`registered-mutation-diff` 只跑這條 diff 動過的那幾個模組。
登記們目錄 = "tests/負控/登記們"


class 查不出動過哪些登記檔(Exception):
    """算清單用的 git 指令自己失敗了，所以「動過哪幾個登記檔」這個問題沒有答案。

    **不准退化成空清單**：`origin/main` 還沒 fetch、淺 clone、遠端不叫 origin 時
    stdout 一樣是空的，跟「本線真的沒動過登記檔」長得一模一樣。當成後者的話閘會綠、
    而一把刀都沒跑——比原本那個 CI 紅更難看出來。
    """


def _是登記模組(檔: str) -> bool:
    """`登記們/` 底下真的登記了刀的模組。`__init__.py` 只是 package 標記，不登記任何刀。

    比的是**精確檔名**，跟收集那側（`tests/負控/登記.py` 的 `_不是登記模組`）同一套認法：
    用子字串排 `__init__` 的話，`主題__init__檢查.py` 這種合法檔名 CI 收得到、本線卻漏掉。
    """
    return 檔.endswith(".py") and PurePosixPath(檔).name != "__init__.py"


def _git吐出的路徑們(根目錄: Path, *參數: str) -> tuple[str, ...]:
    """跑一條唸路徑的 git 指令，把非空的每一行當一個路徑收回來。指令失敗就丟例外。"""
    # `-c core.quotepath=false`：預設 git 會把非 ASCII 路徑印成 `"tests/\350..."`，
    # 而這個 repo 的路徑全是中文——不關掉的話每一行都對不上任何檔名，清單靜靜變空。
    結果 = subprocess.run(  # noqa: S603 —— 指令由本表寫死，不吃外部輸入
        ("git", "-c", "core.quotepath=false", *參數),  # noqa: S607 —— git 就從 PATH 找
        cwd=根目錄,
        capture_output=True,
        text=True,
        check=False,
    )
    if 結果.returncode != 0:
        壞消息 = f"`git {' '.join(參數)}` 退出碼 {結果.returncode}：{結果.stderr.strip()}"
        raise 查不出動過哪些登記檔(壞消息)
    return tuple(行.strip() for 行 in 結果.stdout.splitlines() if 行.strip())


def 動過的登記檔們(根目錄: Path) -> tuple[str, ...]:
    """這條 diff 動過的登記模組（相對 repo 根的路徑），排序去重。

    **兩個來源缺一不可。** `git diff` 只看得到改過而且已提交的檔（`--diff-filter=d`
    排掉刪掉的——刀刪了就不該再跑）；**新增而還沒 `git add` 的檔不在 diff 裡**，
    而「新增一把刀」正是最常見的情形，漏掉它就會選到 0 把、一路綠到 CI。
    本地 `origin/main` 落後只會讓集合變大（多跑幾把），是安全方向。

    任何一條 git 失敗就丟 `查不出動過哪些登記檔`——沒有答案跟「答案是空的」不是同一件事。
    """
    改過又提交的 = _git吐出的路徑們(
        根目錄, "diff", "--name-only", "--diff-filter=d", "origin/main", "--", 登記們目錄
    )
    新增還沒add的 = _git吐出的路徑們(
        根目錄, "ls-files", "--others", "--exclude-standard", "--", 登記們目錄
    )
    return tuple(sorted({檔 for 檔 in (*改過又提交的, *新增還沒add的) if _是登記模組(檔)}))


def 決定基準(環境: Mapping[str, str]) -> str:
    """測試數要跟哪個 ref 比。環境當參數收進來，測試才不必去動真的 os.environ。"""
    return 環境.get(基準環境變數, "HEAD")


def _丟掉pycache(根目錄: Path) -> None:
    """把 `src/` 與 `tests/` 底下的 `__pycache__` 清掉。**跑測試前一定要做。**

    **Python 的快取鍵也不含內容**：`.pyc` 檔頭記的是 source 的 `size` ＋
    **整數秒** `mtime`。同一秒內改兩次而長度剛好一樣，下一次 import 就吃到
    舊的那份——而「一個字元換一個字元」（`open("x")` ↔ `open("a")`）
    正是長度不變的改法，做負控時是常態。

    這一條比 ruff 與 mypy 那兩條嚴重：它不是「靜態檢查放行了」，
    是**跑起來的根本不是你剛寫的那份程式碼**，而且 `inspect.getsource()`
    讀的是 `.py`，印出來完全正常，從原始碼一輩子看不出問題。

    **`PYTHONDONTWRITEBYTECODE=1` 不能代替**：它只擋寫、不擋讀。

    只掃 `src/` 與 `tests/`——`.venv` 底下有上萬個 `__pycache__`，
    清它們只會讓下一次 import 變慢，擋不到任何東西。

    實測代價：`pytest tests/單元` 有 pyc 0.86 秒、冷編 1.02 秒。
    """
    for 頂層 in ("src", "tests"):
        for 目錄 in (根目錄 / 頂層).rglob("__pycache__"):
            shutil.rmtree(目錄, ignore_errors=True)


#: 一條規則的證據最多留幾個字元。閘紅會整段落進收件票，沒有上限的話
#: 一份幾萬行的 pytest 輸出會把票灌爆。
預設證據上限 = 20_000


def _截斷註記(原長: int) -> str:
    """截斷時附在證據尾巴的自白：原本多長、留下來的是哪一段。靜默截斷等於騙人。

    只寫原長、不寫保留長度：保留長度得先知道註記多長才算得出來，而註記長度又
    隨保留長度的位數變動——寫進去就變成自我參照，得反覆迭代才收斂，
    而且收斂不了的時候會**悄悄超過硬上限**。原長是現成的，一次就算完。
    """
    return f"\n……（證據已截斷：原本 {原長} 字元，只留開頭那一段輸出）"


def _截斷證據(輸出: str, 上限: int) -> str:
    """超過上限就砍尾巴，**留開頭那一段輸出**，並在證據裡明講截了。

    砍尾巴不是隨便挑的：pytest 的尾巴是 `short test summary info` 與
    `N failed in ...`，那是整份輸出裡資訊量最低的一段——它只說了幾支紅，
    沒說為什麼紅。開頭的 FAILURES 段才是下一輪的模型唯一看得到的現場。

    上限小到連註記都塞不下時，留下來的就只有註記本身：註記可以是唯一剩下的
    東西，但不能被砍成半句——連「截了」都說不清楚的證據比空的還糟。
    """
    if len(輸出) <= 上限:
        return 輸出

    註記 = _截斷註記(原長=len(輸出))
    保留長度 = max(0, 上限 - len(註記))
    return 輸出[:保留長度] + 註記


def _外部指令(
    根目錄: Path, *指令: str, 證據上限: int = 預設證據上限
) -> Callable[[], tuple[bool, str]]:
    """把一條外部指令包成檢查函式。

    執行檔從 `sys.executable` 旁邊找——nova 跑在哪個 venv，就用哪個 venv 的
    ruff／mypy／pytest，不看 PATH。PATH 會讓本地與 CI 跑到不同版本。
    """
    工具目錄 = Path(sys.executable).parent

    # ruff 帶 `--no-cache`、mypy 帶 `--no-incremental`、pytest 之前清 pycache，
    # 理由不是潔癖：
    # **兩家的快取鍵都不含內容**。ruff 是（路徑、大小、mtime 奈秒）；
    # mypy 是（路徑、大小、**整數秒** mtime）——mypy 只在 mtime 對不上時才去比
    # 內容雜湊，所以「同一秒內改兩次、長度剛好一樣」直接吃到上一次的結論。
    # 那個「剛好」比想像中常見：`已遮罩文字` 換成 `str` 的兩處破壞長度完全相同，
    # 2026-08-30 跑遮罩型別化的負控時當場踩到——**指名的那一格沒紅、別的格紅了**。
    # 人手改檔碰不到，腳本或 agent 連續改檔一定碰得到。
    # 代價：ruff 95 個檔 26→27 毫秒；mypy 146 個檔 0.07→1.09 秒。
    # 買到的那 1 秒，賣掉的是「閘綠等於 CI 綠」。
    # 由 tests/整合/test_閘不准吃快取.py 背書。

    def 檢查() -> tuple[bool, str]:
        執行檔 = 工具目錄 / 指令[0]
        if 指令[0] == "pytest":
            _丟掉pycache(根目錄)
        # pytest 與 mypy 是 python shebang 腳本，直接跑會在活動監視器上顯示成
        # python3.13，跟其他每一支 python 程序分不開。角色就用工具自己的名字。
        完整, 角色標記 = 具名啟動(執行檔 if 執行檔.exists() else Path(指令[0]), 指令[1:])
        結果 = subprocess.run(  # noqa: S603 —— 指令由本表寫死，不吃外部輸入
            完整,
            cwd=根目錄,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "APP_ROLE": 角色標記},
        )
        原始輸出 = (結果.stdout + 結果.stderr).strip()
        return 結果.returncode == 0, _截斷證據(原始輸出, 上限=證據上限)

    return 檢查


def _指名這幾個登記檔(檔們: Sequence[str]) -> tuple[str, ...]:
    """攤成 `--登記檔 甲 --登記檔 乙`：那個選項是可重複的，一個檔給一次。"""
    return tuple(項 for 檔 in 檔們 for 項 in ("--登記檔", 檔))


def _本線登記負控(根目錄: Path) -> Callable[[], tuple[bool, str]]:
    """只跑這條 diff 動過的登記檔裡的那幾把刀。

    篩選走 `--登記檔` 這個 pytest 選項（`tests/conftest.py`），不走 nodeid 也不走 `-k`：
    pytest 會把非 ASCII 的參數 id 轉義成十六進位，點名要載體自己複製一份轉義規則。
    載體只算得出「哪幾個檔案路徑」，「那些檔裡有哪幾把刀」是 `tests/` 自己的知識。

    這條線沒動過登記檔就直接綠——沒有刀可跑不是紅。反過來，動過的檔非空卻一把都選不到
    是 fail-closed 的紅，那一格由 conftest 在收集當下判定。
    """

    def 檢查() -> tuple[bool, str]:
        try:
            檔們 = 動過的登記檔們(根目錄)
        except 查不出動過哪些登記檔 as 原因:
            # 清單算不出來就 fail-closed：當成「沒動過」會讓閘綠而一把刀都沒跑。
            # 證據帶著失敗的那條 git 指令，看到紅的人才知道要去 fetch 哪個基準。
            return False, f"[本線負控] 算不出這條 diff 動過哪些登記檔：{原因}"
        if not 檔們:
            # 沒動過登記檔就沒有刀可跑，那是綠的。證據那句話跟 conftest 共用同一份判定，
            # 兩邊各寫一份的話會慢慢對不起來，而症狀是假綠。
            return 判定選到的刀(檔們, 選到=())
        跑這幾個檔的刀 = _外部指令(根目錄, "pytest", *負控檔們, "-q", *_指名這幾個登記檔(檔們))
        return 跑這幾個檔的刀()

    return 檢查


def 建規則表(根目錄: Path) -> list[規則]:
    """建出這個 repo 的完整規則表。建表本身不碰硬碟，跑的時候才碰。

    階段安排就是資源排程：靜態檢查（秒級）先跑，型別次之，測試最後。
    一次只跑一條，避免 ruff 與 pytest 同時吃滿 CPU 讓對時間敏感的檢查無故變紅。
    """
    提交與CI = frozenset({"提交", "ci"})
    規則們 = [
        規則(
            代碼="lang-traditional",
            名稱="繁體中文（不准簡體字與日文新字體）",
            閘點=提交與CI,
            負責層="載體",
            檢查=lambda: 檢查繁體中文(根目錄),
            階段=靜態,
        ),
        規則(
            代碼="layer-boundaries",
            名稱="三層落點（契約 ← 迴圈 ← 載體，箭頭不准反過來）",
            閘點=提交與CI,
            負責層="載體",
            檢查=lambda: 檢查架構落點(根目錄),
            階段=靜態,
        ),
        規則(
            代碼="no-secrets",
            名稱="機密不進版控",
            閘點=提交與CI,
            負責層="載體",
            檢查=lambda: 檢查機密(根目錄),
            階段=靜態,
        ),
        規則(
            代碼="test-count",
            名稱="測試數不准減少",
            閘點=提交與CI,
            負責層="載體",
            檢查=lambda: 檢查測試數(根目錄, 基準=決定基準(os.environ)),
            階段=靜態,
        ),
        規則(
            代碼="ruff-check",
            名稱="ruff 靜態檢查",
            閘點=提交與CI,
            負責層="載體",
            檢查=_外部指令(根目錄, "ruff", "check", "--no-cache", "."),
            階段=靜態,
        ),
        規則(
            代碼="ruff-format",
            名稱="ruff 格式",
            閘點=提交與CI,
            負責層="載體",
            檢查=_外部指令(根目錄, "ruff", "format", "--check", "--no-cache", "."),
            階段=靜態,
        ),
        規則(
            代碼="ruff-exemptions",
            名稱="ruff 豁免登記",
            閘點=frozenset({"ci"}),
            負責層="載體",
            檢查=partial(檢查ruff豁免, 根目錄),
            階段=靜態,
        ),
        規則(
            代碼="mypy",
            名稱="型別（strict）",
            閘點=提交與CI,
            負責層="載體",
            檢查=_外部指令(根目錄, "mypy", "--no-incremental"),
            階段=型別,
        ),
        規則(
            代碼="pytest-unit",
            名稱="單元測試（序列、秒級）",
            閘點=frozenset({"提交"}),
            負責層="載體",
            檢查=_外部指令(根目錄, "pytest", "tests/單元", "-q"),
            階段=測試,
            涵蓋於="pytest-parallel",  # CI 跑全測試時會包含 tests/單元
        ),
        規則(
            代碼="docs-facts",
            名稱="文件宣稱存在的東西要真的在",
            閘點=frozenset({"提交"}),
            負責層="載體",
            檢查=_外部指令(根目錄, "pytest", "tests/驗收/test_文件即事實.py", "-q"),
            階段=測試,
            涵蓋於="pytest-parallel",  # CI 跑全測試時會包含它
        ),
        規則(
            代碼="pytest-parallel",
            名稱="全測試（平行，不含 serial）",
            閘點=frozenset({"ci"}),
            負責層="載體",
            檢查=_外部指令(
                根目錄,
                "pytest",
                "-m",
                "not serial and not 真cli and not 真端點",
                "-n",
                str(平行度()),
                "--dist",
                "worksteal",
                "-q",
                *負控檔排除參數,
            ),
            階段=測試,
            # 它自己就開這麼多 worker，額度照它實際開的算。
            要幾個token=平行度(),
        ),
        規則(
            代碼="pytest-serial",
            名稱="序列測試（會搶資源、不可平行）",
            閘點=frozenset({"ci"}),
            負責層="載體",
            檢查=_外部指令(
                根目錄,
                "pytest",
                "-m",
                "serial and not 真cli and not 真端點",
                "-q",
                "-p",
                "no:randomly",
            ),
            階段=測試,
        ),
        規則(
            代碼="registered-mutation",
            名稱="登記負控（精確變異）",
            閘點=frozenset({"ci"}),
            負責層="測試",
            檢查=_外部指令(根目錄, "pytest", *負控檔們, "-q"),
            階段=測試,
            # 每把刀的 `最多秒` 是**牆鐘**：機器上多一個鄰居就可能把好測試殺成
            # 假紅（見 `載體/閘鎖.py`）。只有這一條要整台機器。
            要幾個token=抽乾整池,
        ),
        規則(
            代碼="registered-mutation-diff",
            名稱="本線登記負控（只跑這條 diff 動過的登記檔）",
            閘點=frozenset({"本線"}),
            負責層="測試",
            檢查=_本線登記負控(根目錄),
            階段=測試,
            # 跟 `registered-mutation` 同一份知識：每把刀的 `最多秒` 是**牆鐘**，
            # 鄰居線同時在跑測試就會把好刀殺成假紅。它跑的把數少，要的機器一樣多。
            要幾個token=抽乾整池,
        ),
        規則(
            代碼="serial-ratio",
            名稱="serial 測試佔比（阿姆達爾定律門禁）",
            閘點=frozenset({"ci"}),
            負責層="載體",
            檢查=lambda: 檢查serial佔比(根目錄),
            階段=靜態,
        ),
    ]

    def 檢查規範() -> tuple[bool, str]:
        通過, 摘要 = 檢查規範落點(根目錄, {條.代碼 for 條 in 規則們})
        if 通過:
            sys.stdout.write(f"{摘要}\n")
        return 通過, 摘要

    規則們.append(
        規則(
            代碼="claude-location",
            名稱="CLAUDE.md 規範落點",
            閘點=frozenset({"ci"}),
            負責層="載體",
            檢查=檢查規範,
            階段=靜態,
        )
    )
    return 規則們


def 版本(規則表檔: Path | None = None) -> str:
    """這一版規則表的內容指紋，落在成果帳的 `policy_version`。

    **走內容雜湊，不走 git 的 commit**：閘是照**工作區那份**規則表跑的，
    不是照 HEAD 那份跑的。改了還沒提交就跑一次的話，走 git 會給出上一版的
    答案——那比沒有答案更糟，因為它看起來像個答案。

    雜湊不是為了防篡改，只是為了比對，所以取前 16 個十六進位字元就夠
    （跟 `載體/重構護欄.py` 同一招）。

    路徑收成參數是為了測得動「內容變了答案就不同」；呼叫端不必知道
    規則表住哪個檔，那是規則表自己的知識。
    """
    檔 = 規則表檔 if 規則表檔 is not None else Path(__file__)
    return hashlib.sha256(檔.read_bytes()).hexdigest()[:16]

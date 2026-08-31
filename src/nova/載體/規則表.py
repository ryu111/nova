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
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

from nova.載體.serial佔比 import 檢查serial佔比
from nova.載體.機密 import 檢查機密
from nova.載體.測試數 import 檢查測試數
from nova.載體.程序 import 具名啟動
from nova.載體.規範落點 import 檢查規範落點
from nova.載體.語言 import 檢查繁體中文
from nova.載體.豁免登記 import 檢查ruff豁免
from nova.載體.閘 import 型別, 測試, 規則, 靜態

# CI 要跟 base branch 比，本機 commit 前跟 HEAD 比。用環境變數傳遞，
# 讓 .github/workflows/gates.yml 只放一個常數字串、不放判斷邏輯（薄轉接、厚 nova）。
# 變數名用 ASCII：CLAUDE.md 的 shell 變數名例外。
基準環境變數 = "NOVA_TEST_COUNT_BASE"


#: 平行測試吃掉幾成的核心。留 1/4 給作業系統與 pytest 主控。
平行成數 = 0.75
#: worker 數的**上限**，跟核心數無關。
#:
#: 這套測試序列跑 5.8 秒，開到 12 個 worker 反而比 4 個慢 1.1 秒
#: （實測見 `平行度` 的表）。**核心多不代表該開多。**
#:
#: **變慢是量到的，原因還沒量到。** 這裡原本寫「因為每個 worker 都要自己
#: import 整套測試」——那條推理有漏洞：worker 是各自的程序，import 是同時發生的，
#: 不是一筆一筆加上去的。候選解釋與怎麼驗寫在
#: `docs/設計/05-測試怎麼跑最快.md`。**4 是這台機器調出來的數字，不是通則。**
#:
#: 什麼時候該重量：**序列時間超過 ~15 秒**。那時每個 worker 分到的工作量
#: 才攤得掉自己的啟動成本，上限就該往上調。在那之前調高只是多付啟動費。
最多worker = 4


def 平行度(核心數: int | None = None) -> int:
    """平行測試要開幾個 worker。**不吃滿。**

    實測（這台 16 核，同一套測試各跑兩次取平均。2026-08-29 重量，
    在「假 CLI 改成整個 session 共用」之後——舊的一組數字是那次優化之前的）：

    | `-n` | 秒 | 優化前 |
    |---|---|---|
    | 序列 | 7.19 | 9.91 |
    | 4 | **3.44** | **5.60** |
    | 8 | 3.87 | 5.66 |
    | 12（現在這個） | 4.02 | 5.79 |
    | 16（吃滿） | 4.25 | 6.00 |

    **worker 越多越慢**，因為這套測試不是 CPU-bound（全程只用到 213% CPU）——
    瓶頸是子程序啟動與 I/O 等待，而 worker 自己的啟動成本隨數量增加。
    單獨跑 0.04 秒的測試，在吃滿核心時會變成 1.4 秒，那多出來的是競爭不是工作。

    **2026-08-29 重量之後改了結論。** 原本寫「調低是拿這台機器的最佳值換掉在別台
    機器也合理，所以留在 3/4」。那個推論有洞：慢下來的原因不是「這台機器」，
    是**每個 worker 都要重新 import 整套測試**，那筆成本在任何機器上都存在。
    所以正確的旋鈕不是成數，是**上限**（`最多worker`）——它只會往下壓，
    4 核的 CI 算出來還是 3，一點都沒變。

    再量一次（3 次取中位數，同一台 16 核）：序列 5.81／`-n 2` 3.52／
    **`-n 4` 2.34**／`-n 8` 2.79／`-n 12` 3.43／`-n 16` 3.69。

    真正該修的是測試本身的子程序成本，不是這個旋鈕——**而那條路已經走過一次**：
    假 CLI 改成整個 session 共用（不再每支測試重寫一份執行檔）之後，
    每一格都快了三分之一以上。旋鈕沒動，數字自己就下來了。
    """
    核心 = 核心數 or os.cpu_count() or 1
    # 兩條規則疊起來：不吃滿（3/4），而且不超過套件攤得掉的 worker 數。
    # 上限只會往下壓，不會把小機器補上去——CI 是 4 核，算出來還是 3。
    return max(1, min(最多worker, int(核心 * 平行成數)))


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


def _外部指令(根目錄: Path, *指令: str) -> Callable[[], tuple[bool, str]]:
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
        輸出 = (結果.stdout + 結果.stderr).strip()
        return 結果.returncode == 0, 輸出

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
            ),
            階段=測試,
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
            檢查=_外部指令(根目錄, "pytest", "tests/負控/test_登記的變異會被殺.py", "-q"),
            階段=測試,
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

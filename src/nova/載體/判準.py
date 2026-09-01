"""機械判準：跑一條指令，看它綠不綠。

**不是模型。** 硬規則 4 禁止同一個模型自寫自評；驗收權不在執行者手上。
判準只有一個判斷依據：退出碼。模型講什麼都不算數。
"""

import shlex
import subprocess
import sys
from collections.abc import Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from nova.契約.工作流 import 任務, 判準, 判準終局, 判準逾時證據標記
from nova.載體.規則表 import 建規則表, 負控檔排除參數
from nova.載體.閘 import 規則
from nova.載體.閘鎖 import 佔不到, 佔住

#: TDD 內圈的判準就是測試本身。
#:
#: **排掉負控檔。** 判準回答的是「這一輪的行為對不對」；負控刀驗的是
#: 「測試守不守得住」，那是 CI 的 `registered-mutation` 的工作，
#: 每個判準階段再跑一次是同一件事做很多遍（量測見 `docs/設計/14-閘慢在哪.md`）。
#: 清單從 `規則表.負控檔們` 推導，不在這裡抄檔名。
#:
#: **只准往後面接 `--ignore`**：不動 `pyproject.toml` 的 `testpaths`，
#: 也不加任何會少收集的旗標——排太多會讓判準「更快變綠」，長得像改善。
預設判準指令 = ("uv", "run", "pytest", "-q", *負控檔排除參數)

#: 判準要涵蓋的閘點。提交閘那幾條（ruff／mypy／繁中／機密／文件事實……）
#: 原本一條都不跑，於是工作流宣布全綠、人一 commit 就被擋下來，整輪重做。
_判準涵蓋的閘點 = "提交"

#: 跑提交閘的指令。**不寫死規則清單**——清單從 `規則表` 現算（見 `預設判準步驟們`）。
_提交閘指令 = ("uv", "run", "nova", "閘", "提交")

#: `nova 閘` 佔不到機器鎖時回 3（結果未知）。**3 不是紅**：閘根本沒跑，
#: 當紅回報的話工作流會退回實作重做一輪，而它一件事都沒驗過。
_閘的未知退出碼 = frozenset({3})

#: CI 上跑全測試的那條規則。提交閘上標了 `涵蓋於=這條` 的規則，
#: 就是「判準這份全跑已經涵蓋掉」的那些。
_CI全跑規則代碼 = "pytest-parallel"
_證據上限 = 4000

#: **跟 `nova 閘` 同一把鎖。** 判準跟閘搶的是同一份 CPU，各拿各的話兩邊照樣
#: 同時跑滿，卻長得像有鎖。名稱一致是「同一把」的唯一依據。
#:
#: **判準要的是「別搶 CPU」，不是「一次只准一條」。** 現在這把全域互斥鎖
#: 把並行度壓成 1。實際解是計數式的鎖（同時最多 N 條），但那是新機制、
#: 要有自己的測試，所以鎖的形狀另開一張票，這一格不動鎖。
_機器鎖名稱 = "閘"

#: pytest 自己的退出碼裡，**「根本沒驗到」**的那兩個。
#:
#: 原本的分界線劃在「Python 端有沒有丟例外」——那條線只抓得到指令不存在。
#: pytest 好端端地跑起來、卻回報「一支測試都沒收集到」時 Python 端沒有例外，
#: 於是判準說紅、工作流回去「再實作一次」，每一輪夾一個模型階段。
#: exit 5 正是「研究題誤進 TDD 工作流」的準確形狀：沒有測試檔，永遠收集不到。
_pytest沒驗到 = {
    5: "pytest 沒收集到任何測試（exit 5）",
    4: "pytest 用法錯誤，旗標打錯或路徑不存在（exit 4）",
}

排除目錄前綴: tuple[str, ...] = ("tests/負控/登記們/",)
排除相對路徑: tuple[str, ...] = (
    "tests/負控/登記.py",
    "tests/負控/執行器.py",
)
排除檔名: tuple[str, ...] = (
    "conftest.py",
    "__init__.py",
)


def 可作指定pytest目標(路徑: str) -> bool:
    """排除負控登記資料、執行器、conftest 等無法作為指定 pytest 目標的非測試檔。"""
    if any(路徑.startswith(前綴) or f"/{前綴}" in 路徑 for 前綴 in 排除目錄前綴):
        return False  #: 負控登記們
    if any(路徑 == 排除 or 路徑.endswith(f"/{排除}") for 排除 in 排除相對路徑):
        return False
    檔名 = 路徑.rsplit("/", 1)[-1]
    return 檔名 not in 排除檔名


def _像pytest(指令: Sequence[str]) -> bool:
    """**退出碼語意是各程式自己的知識，不是通用常識。**

    nova 自己的 4 是「護欄生效」而不是「用法錯誤」。無條件把 4／5 翻成
    跑不起來，等於把別人給的回饋偽裝成環境問題——正好是 `判準終局.跑不起來`
    存在理由的鏡像錯誤。所以這個映射綁在 pytest 上；認不出來（例如自寫的
    包裝腳本）就退回當紅，降級方向是安全的。
    """
    return any("pytest" in 段 for 段 in 指令)


def _佔住機器跑(
    指令: Sequence[str], *, 工作目錄: Path, 逾時秒: float, 佔機器: bool = True
) -> subprocess.CompletedProcess[str]:
    """在機器鎖底下跑子程序。

    **鎖只圈住這一段。** 圈大一點（整個判準階段）就等於一次只能跑一條工作流，
    而工作流大部分時間是在等模型，那幾分鐘不該排隊。

    `佔機器=False` 只給**子程序自己會佔同一把鎖**的指令用（`nova 閘`）：
    在這裡先佔住，子程序就會卡在同一個鎖檔上等到上限——那是自己鎖死自己。
    鎖還是同一把，只是由子程序去佔。
    """
    機器鎖: AbstractContextManager[None] = 佔住(_機器鎖名稱) if 佔機器 else nullcontext()
    with 機器鎖:
        return subprocess.run(  # noqa: S603 —— 指令由呼叫端明確給定
            list(指令),
            cwd=工作目錄,
            capture_output=True,
            text=True,
            timeout=逾時秒,
            check=False,
        )


def _判讀退出碼(
    結果: subprocess.CompletedProcess[str],
    指令: Sequence[str],
    未知退出碼: frozenset[int] = frozenset(),
) -> tuple[判準終局, str]:
    """指令跑完了，看退出碼決定收場。"""
    輸出 = (結果.stdout + 結果.stderr).strip()[-_證據上限:]
    if 結果.returncode == 0:
        return 判準終局.綠, 輸出
    if 結果.returncode in 未知退出碼:
        # **這條指令自己說「不知道做了沒」。** 例如 `nova 閘` 佔不到鎖回 3。
        return 判準終局.跑不起來, f"判準沒跑（結果未知，不是測試沒過）：\n{輸出}"
    沒驗到 = _pytest沒驗到.get(結果.returncode) if _像pytest(指令) else None
    if 沒驗到 is not None:
        # **沒驗到不等於驗不過。** 跟 OSError 那格同一個道理：這是環境／設定，
        # 重跑一百次還是同一個結果，而每次重跑中間都夾著一個模型階段。
        return 判準終局.跑不起來, f"判準跑不起來（環境問題，不是測試沒過）：{沒驗到}\n{輸出}"
    return 判準終局.紅, 輸出


def 建判準(
    指令: Sequence[str] = 預設判準指令,
    *,
    逾時秒: float = 600.0,
    佔機器: bool = True,
    未知退出碼: frozenset[int] = frozenset(),
) -> 判準:
    """做一個判準：在任務的工作目錄跑這條指令，退出碼 0 就是綠。

    指令是**選填**（有真正的預設值）。逾時當紅處理——判準跑不完就是沒通過，
    不能因為「不知道」而放行（fail-closed）；連續逾時由 `卡住了` 的逾時專屬計數收。

    `佔機器=False` 留給自己會佔同一把機器鎖的子程序（見 `_佔住機器跑`）。
    `未知退出碼` 是這條指令用來說「不知道做了沒」的那幾個碼，判成跑不起來而不是紅。
    """

    def 跑(任: 任務) -> tuple[判準終局, str]:
        try:
            結果 = _佔住機器跑(指令, 工作目錄=任.工作目錄, 逾時秒=逾時秒, 佔機器=佔機器)
        except 佔不到 as 錯:
            # **佔不到鎖不是紅。** 判準根本沒跑，回紅的話工作流會回去
            # 「再實作一次」，叫一顆模型去改一份沒問題的程式碼。
            # 跟 `_子命令_閘` 佔不到時回 3（結果未知）同一個判斷。
            return 判準終局.跑不起來, f"判準沒跑（機器忙，不是測試沒過）：{錯}"
        except subprocess.TimeoutExpired:
            # **逾時刻意留在「紅」，跟上面的 `佔不到`（跑不起來）分開。**
            # 兩者都是「不知道做了沒」，但 `佔不到` 確定一行測試都沒跑到，
            # 逾時卻可能是測試真的卡死在自己的死迴圈上——放行等於漏掉真的紅，
            # 所以 fail-closed 當紅。代價（每次紅都退回實作、一路燒 token）
            # 由 `迴圈.狀態機.卡住了` 的**逾時專屬計數**收：連續兩次逾時就收護欄，
            # 而且**不看工作區雜湊**（逾時不是回饋，改 code 改變不了機器過載）。
            return 判準終局.紅, f"{判準逾時證據標記} {逾時秒} 秒沒跑完（當紅處理）"
        except OSError as 錯:
            # **跑不起來不是紅。** 指令不存在、沒有執行權限、路徑不是目錄——
            # 那是環境（診斷順序第一條），重跑一百次還是同一個環境。
            # 當紅回報的話工作流會回去「再實作一次」，而實作要叫模型。
            # 實測 2026-08-30：launchd 的 PATH 沒有 uv，單次燒掉 997,031 token。
            return 判準終局.跑不起來, f"判準指令跑不起來（環境問題，不是測試沒過）：{錯}"
        return _判讀退出碼(結果, 指令, 未知退出碼)

    return 跑


@dataclass(frozen=True)
class 判準步驟:
    """預設判準的一步：跑哪條指令、它擋得下規則表上的哪幾條。

    `涵蓋規則` 是**現算的**（見 `預設判準步驟們`），不是手抄的清單——
    手抄的話新增一條閘規則時判準不會跟上，而那個洞會靜靜長回來。
    """

    名稱: str
    指令: tuple[str, ...]
    #: 這一步的**涵蓋宣告**：跑的時候不讀它，是拿去跟規則表對帳的
    #: （`test_判準涵蓋提交閘`），漏掉一條就當場紅。
    涵蓋規則: tuple[str, ...] = ()
    #: 子程序自己會佔同一把機器鎖時要關掉，不然是自己鎖死自己。
    佔機器: bool = True
    未知退出碼: frozenset[int] = frozenset()


def _提交閘上的規則代碼(規則表: Sequence[規則]) -> tuple[str, ...]:
    """掛在提交閘上的規則代碼。**現算，不手抄。**"""
    return tuple(sorted(條.代碼 for 條 in 規則表 if _判準涵蓋的閘點 in 條.閘點))


def _被全跑涵蓋的規則代碼(規則表: Sequence[規則]) -> tuple[str, ...]:
    """標了「CI 那條全跑會涵蓋我」的規則代碼——判準這份全跑一樣涵蓋得到。"""
    return tuple(sorted(條.代碼 for 條 in 規則表 if 條.涵蓋於 == _CI全跑規則代碼))


def 預設判準步驟們(根目錄: Path) -> tuple[判準步驟, ...]:
    """預設判準跑哪幾步。**提交閘 ∪ 全測試，不是二選一。**

    直接換成 `nova 閘 提交` 就收工的話，測試涵蓋會從「全部」縮成
    「只有 `tests/單元`」（`pytest-unit` 標了 `涵蓋於=pytest-parallel`，
    全測試由 CI 那條負責）——而縮水的症狀是**變綠變快**，看起來像改善。
    所以那條全跑的指令必須原樣留著。
    """
    規則表 = 建規則表(根目錄)
    return (
        判準步驟(
            名稱="全測試",
            指令=預設判準指令,
            涵蓋規則=_被全跑涵蓋的規則代碼(規則表),
        ),
        判準步驟(
            名稱="提交閘",
            指令=_提交閘指令,
            涵蓋規則=_提交閘上的規則代碼(規則表),
            佔機器=False,  # `nova 閘` 自己會佔同一把鎖
            未知退出碼=_閘的未知退出碼,
        ),
    )


def 建預設判準() -> 判準:
    """三個判準階段用的判準：全測試 ＋ 提交閘。

    **第一個非綠就停。** 後面那步在同一份紅上不會給出新資訊，而每一步都吃機器。
    """

    def 跑(任: 任務) -> tuple[判準終局, str]:
        證據們: list[str] = []
        for 步 in 預設判準步驟們(任.工作目錄):
            跑這步 = 建判準(步.指令, 佔機器=步.佔機器, 未知退出碼=步.未知退出碼)
            收場, 證據 = 跑這步(任)
            證據們.append(f"[{步.名稱}] {證據}")
            if 收場 is not 判準終局.綠:
                return 收場, "\n".join(證據們)
        return 判準終局.綠, "\n".join(證據們)

    return 跑


def 建重構判準() -> 判準:
    """建出重構結束時使用的 lint 與格式判準。

    **跟提交閘的 `ruff-check`／`ruff-format` 是同兩條，刻意分開。**
    這裡跑的是重構階段的秒級回饋（只有 ruff），提交閘那份還要 mypy 與整套測試；
    重構剛動完格式就等一次完整閘，回饋圈會從幾秒變成幾分鐘。
    合併的前提是閘先變快（`docs/設計/14` 的甲、乙），那條線正在另一邊做。
    """
    ruff = str(Path(sys.executable).parent / "ruff")
    檢查們 = (
        ("ruff-check", 建判準((ruff, "check", "--no-cache", "."))),
        ("ruff-format", 建判準((ruff, "format", "--check", "--no-cache", "."))),
    )

    def 跑(任: 任務) -> tuple[判準終局, str]:
        收場們: list[判準終局] = []
        證據們: list[str] = []
        for 名稱, 檢查 in 檢查們:
            收場, 證據 = 檢查(任)
            收場們.append(收場)
            證據們.append(f"[{名稱}] {證據}")
        if any(收場 is 判準終局.跑不起來 for 收場 in 收場們):
            return 判準終局.跑不起來, "\n".join(證據們)
        收場 = 判準終局.綠 if all(項 is 判準終局.綠 for 項 in 收場們) else 判準終局.紅
        return 收場, "\n".join(證據們)

    return 跑


def 判準指令(文字: str | None) -> tuple[str, ...]:
    """把使用者給的字串切成指令。沒給就用預設。"""
    if not 文字 or not 文字.strip():
        return 預設判準指令
    return tuple(shlex.split(文字))


def 在哪跑(工作目錄: str | None) -> Path:
    """判準與角色共用的工作目錄。沒給就是現在這個目錄。"""
    return Path(工作目錄).resolve() if 工作目錄 else Path.cwd()

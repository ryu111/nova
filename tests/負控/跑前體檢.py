"""登記的**跑前體檢**：不套用變異，只驗錨點與覆蓋。

同樣的兩道判定（錨點恰好一次、`該紅` 蓋得到被變異的那幾行）本來只在
`registered-mutation` 那條 CI 規則裡跑，一輪 158 秒；登記寫錯要推 PR 等 CI
幾分鐘才看得到 `WRONG_TEST`。這個檔把那兩道**提早**：

* 錨點只讀檔數字串，不開子程序。
* 覆蓋要真的跑一次 `該紅` 收覆蓋，但**同一支測試被多把刀指名時只跑一次**。
* 一次跑 121 把刀的「套用變異 → 跑測試」在這裡一次都不做。

判定本身沒有放寬：這裡紅了就是那一筆真的有問題，權威仍然是
`registered-mutation`（那條不准動）。

不 raise：一次要把全部登記看完，回傳每一筆有問題的登記各一則訊息，
**空 tuple ＝ 全部過**。
"""

import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

import coverage

from .執行器 import _環境, _錯, 要求覆蓋的行, 負控錯誤
from .登記 import 變異

#: coverage 跑起來比裸 pytest 慢，登記上的 `最多秒` 是給裸 pytest 的。
_覆蓋額外秒 = 30.0


class _待驗的(NamedTuple):
    """錨點那一關過了、還要往下驗覆蓋的一筆登記，連同算好的目標檔與必須覆蓋的行。"""

    一筆: 變異
    目標: Path
    必須覆蓋: frozenset[int]


def _讀覆蓋(資料檔: Path) -> dict[Path, set[int]]:
    """把一次 coverage run 的結果讀成 {檔案: 走到的行}。"""
    命中: dict[Path, set[int]] = {}
    for 檔名 in 資料檔.parent.glob(f"{資料檔.name}*"):
        if not 檔名.is_file():
            continue
        資料 = coverage.CoverageData(basename=str(檔名))
        資料.read()
        for 實際檔名 in 資料.measured_files():
            鍵 = Path(實際檔名).resolve()
            命中.setdefault(鍵, set()).update(資料.lines(實際檔名) or ())
    return 命中


def _跑一次收覆蓋(根目錄: Path, nodeid: str, 最多秒: float) -> dict[Path, set[int]]:
    """跑一支測試並收覆蓋。跑不起來就當場炸——靜默跳過等於那把刀永遠綠。"""
    指令 = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--parallel-mode",
        f"--source={根目錄}",
        "-m",
        "pytest",
    ]
    # **跟 CI 那一關同一個外掛。** 它讓 coverage 只在測試執行期開著，
    # 於是 import 時就跑完的行不會被算成「測試走到了」。
    # 假專案（單元測試用的那種）沒有這個外掛，所以要看得到才掛。
    if (根目錄 / "tests/負控/執行器.py").is_file():
        指令 += ["-p", "tests.負控.執行器"]
    指令 += ["-p", "no:randomly", "-q", nodeid]
    with tempfile.TemporaryDirectory(prefix="nova-體檢-") as 暫存:
        資料檔 = Path(暫存) / ".coverage"
        try:
            結果 = subprocess.run(
                指令,
                cwd=根目錄,
                capture_output=True,
                text=True,
                check=False,
                timeout=最多秒 + _覆蓋額外秒,
                env=_環境(根目錄, COVERAGE_FILE=str(資料檔)),
            )
        except (OSError, subprocess.TimeoutExpired) as 錯:
            _錯(f"RUN_ERROR：coverage 無法完成：{nodeid}", 來源=錯)
        if 結果.returncode != 0:
            輸出 = 結果.stdout + 結果.stderr
            _錯(f"RUN_ERROR：coverage 測試失敗：{nodeid}\n{輸出}")
        return _讀覆蓋(資料檔)


def _那幾行長什麼樣(目標: Path, 行們: Iterable[int]) -> str:
    """把行號連同**內容**一起印出來：只印行號還要人自己去翻第幾行是什麼。"""
    原始行們 = 目標.read_text(encoding="utf-8").splitlines()
    出 = []
    for 行 in sorted(行們):
        內容 = 原始行們[行 - 1] if 1 <= 行 <= len(原始行們) else "（超出檔案範圍）"
        出.append(f"    {行}: {內容}")
    return "\n".join(出)


def _驗錨點(一筆: 變異, 目標: Path) -> tuple[str | None, frozenset[int]]:
    """驗一筆的錨點，順便算出它要求的覆蓋行。訊息 `None` ＝ 這一關過了。"""
    if not 目標.is_file():
        return f"RUN_ERROR：{一筆.識別}：目標不存在：{一筆.目標檔}", frozenset()
    錨點 = 一筆.操作.錨點
    次數 = 目標.read_text(encoding="utf-8").count(錨點)
    if 次數 != 1:
        return f"RUN_ERROR：{一筆.識別}：錨點應恰好一次，實際 {次數}：{錨點!r}", frozenset()
    # 目標不是 Python 就沒有「執行行」可談，跟 runner 同一個理由跳過覆蓋這一關。
    if 目標.suffix != ".py":
        return None, frozenset()
    try:
        return None, 要求覆蓋的行(目標, 一筆)
    except 負控錯誤 as 錯:
        return f"{錯}：{一筆.識別}", frozenset()


def _驗每一筆的錨點(登記們: Iterable[變異], 根目錄: Path) -> tuple[list[str], list[_待驗的]]:
    """第一關：只讀檔數字串。回傳（問題訊息們, 還要往下驗覆蓋的那幾筆）。

    錨點就不對的那一筆到此為止——它連「要覆蓋哪幾行」都算不出來。
    """
    問題們: list[str] = []
    待驗們: list[_待驗的] = []
    for 一筆 in 登記們:
        目標 = 根目錄 / 一筆.目標檔
        訊息, 必須覆蓋 = _驗錨點(一筆, 目標)
        if 訊息 is not None:
            問題們.append(訊息)
        elif 必須覆蓋:
            待驗們.append(_待驗的(一筆, 目標, 必須覆蓋))
    return 問題們, 待驗們


def _收齊該紅的覆蓋(
    待驗們: Iterable[_待驗的], 根目錄: Path
) -> tuple[dict[str, dict[Path, set[int]]], dict[str, str]]:
    """第二關：跑 `該紅` 收覆蓋。回傳（每支測試走到的行, 跑不起來的那幾支的原因）。

    **同一支測試被多把刀指名時只跑一次**（143 筆登記裡有大量共用的 `該紅`）；
    共用時取最寬鬆的 `最多秒`，免得被最急的那把刀誤殺。
    """
    要跑的: dict[str, float] = {}
    for 待驗 in 待驗們:
        for nodeid in 待驗.一筆.該紅:
            要跑的[nodeid] = max(要跑的.get(nodeid, 0.0), 待驗.一筆.最多秒)

    覆蓋快取: dict[str, dict[Path, set[int]]] = {}
    跑不起來: dict[str, str] = {}
    for nodeid, 最多秒 in 要跑的.items():
        try:
            覆蓋快取[nodeid] = _跑一次收覆蓋(根目錄, nodeid, 最多秒)
        except 負控錯誤 as 錯:
            跑不起來[nodeid] = str(錯)
    return 覆蓋快取, 跑不起來


def _驗覆蓋(
    待驗: _待驗的,
    覆蓋快取: dict[str, dict[Path, set[int]]],
    跑不起來: dict[str, str],
) -> str | None:
    """第三關：`該紅` 那幾支測試有沒有真的走到被變異的那幾行。`None` ＝ 這一筆過了。"""
    一筆, 目標, 必須覆蓋 = 待驗
    for nodeid in 一筆.該紅:
        if nodeid in 跑不起來:
            return f"{跑不起來[nodeid]}：{一筆.識別}"
        命中 = 覆蓋快取[nodeid].get(目標.resolve(), set())
        缺少 = 必須覆蓋 - 命中
        if 缺少:
            return (
                f"WRONG_TEST：{一筆.識別} 的 {nodeid} "
                f"沒覆蓋 {一筆.目標檔} 的 {sorted(缺少)}：\n"
                f"{_那幾行長什麼樣(目標, 缺少)}"
            )
    return None


def 體檢登記(登記們: Iterable[變異], *, 根目錄: Path) -> tuple[str, ...]:
    """跑前體檢一批登記，回傳有問題那幾筆的訊息（空 tuple ＝ 全部過）。"""
    問題們, 待驗們 = _驗每一筆的錨點(登記們, 根目錄)
    覆蓋快取, 跑不起來 = _收齊該紅的覆蓋(待驗們, 根目錄)
    for 待驗 in 待驗們:
        訊息 = _驗覆蓋(待驗, 覆蓋快取, 跑不起來)
        if 訊息 is not None:
            問題們.append(訊息)
    return tuple(問題們)

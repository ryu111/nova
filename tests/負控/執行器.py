"""執行登記過的精確負控。"""

import ast
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import NoReturn

import coverage

from .登記 import 替換一次, 變異


class 負控錯誤(RuntimeError):
    """負控本身無法判定時的錯誤。"""


def _錯(訊息: str, *, 來源: Exception | None = None) -> NoReturn:
    例外 = 負控錯誤(訊息)
    if 來源 is not None:
        raise 例外 from 來源
    raise 例外


@cache
def _目前覆蓋率() -> coverage.Coverage:
    覆蓋率 = coverage.Coverage.current()
    if 覆蓋率 is None:
        _錯("coverage runner 沒有啟動")
    return 覆蓋率


def pytest_collection_finish() -> None:
    覆蓋率 = _目前覆蓋率()
    覆蓋率.stop()
    覆蓋率.save()


def pytest_runtest_call() -> None:
    _目前覆蓋率().start()


def pytest_runtest_teardown() -> None:
    覆蓋率 = _目前覆蓋率()
    覆蓋率.stop()
    覆蓋率.save()


def _雜湊(檔案: Path) -> str:
    return hashlib.sha256(檔案.read_bytes()).hexdigest()


def _忽略快取(_: str, 名字: list[str]) -> set[str]:
    return {名字 for 名字 in 名字 if 名字 == "__pycache__" or 名字.endswith(".pyc")}


def _複製專案(來源: Path, 目的: Path) -> None:
    """**`docs` 也要複製。**

    驗收層有測試把文件當成被驗收的對象（路線圖的態、文件宣稱存在的檔案），
    那些測試讀 `docs/`——不複製的話，以文件為目標檔的刀會在基線階段就
    `FileNotFoundError`，而那看起來像 runner 壞了，不像「這把刀沒複製到料」。

    成本可忽略：`docs` 792K，比 `src` 的 1.5M 還小。
    """
    目的.mkdir()
    for 名稱 in ("src", "tests", "docs"):
        shutil.copytree(來源 / 名稱, 目的 / 名稱, ignore=_忽略快取)
    for 名稱 in ("pyproject.toml", "README.md"):
        shutil.copy2(來源 / 名稱, 目的 / 名稱)


def _丟掉pycache(根目錄: Path) -> None:
    for 頂層 in ("src", "tests"):
        for 目錄 in (根目錄 / 頂層).rglob("__pycache__"):
            shutil.rmtree(目錄, ignore_errors=True)


def _環境(根目錄: Path, **額外: str) -> dict[str, str]:
    原本 = os.environ.get("PYTHONPATH", "")
    路徑 = os.pathsep.join(過 for 過 in (str(根目錄 / "src"), str(根目錄), 原本) if 過)
    return {**os.environ, "PYTHONPATH": 路徑, **額外}


def _pytest(根目錄: Path, *參數: str, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:randomly", "-q", *參數],
            cwd=根目錄,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=_環境(根目錄),
        )
    except subprocess.TimeoutExpired as 錯:
        _錯(f"RUN_ERROR：pytest 逾時：{參數[0]}", 來源=錯)
    except OSError as 錯:
        _錯(f"RUN_ERROR：pytest 無法啟動：{錯}", 來源=錯)


def _要求收集(根目錄: Path, nodeid: str, 最多秒: float) -> None:
    結果 = _pytest(根目錄, "--collect-only", nodeid, timeout=最多秒)
    if 結果.returncode != 0:
        _錯(f"RUN_ERROR：找不到或無法收集 {nodeid}\n{結果.stdout}{結果.stderr}")


def _跑基線(根目錄: Path, 一筆: 變異) -> None:
    for nodeid in 一筆.該紅:
        _要求收集(根目錄, nodeid, 一筆.最多秒)
        結果 = _pytest(根目錄, nodeid, timeout=一筆.最多秒)
        _判定基線(結果.returncode, nodeid, 結果.stdout + 結果.stderr)


def _判定基線(退出碼: int, nodeid: str, 輸出: str = "") -> None:
    if 退出碼 != 0:
        _錯(f"BASELINE_RED：{nodeid}\n{輸出}")


def _資料行(資料: coverage.CoverageData, 檔名: str, 上下文: str | None) -> set[int]:
    if 上下文 is None:
        return set(資料.lines(檔名) or ())
    return {行 for 行, 上下文們 in 資料.contexts_by_lineno(檔名).items() if 上下文 in 上下文們}


def _覆蓋的行(資料檔: Path, 目標: Path, 上下文: str | None = None) -> set[int]:
    命中: set[int] = set()
    for 檔名 in 資料檔.parent.glob(f"{資料檔.name}*"):
        if not 檔名.is_file():
            continue
        資料 = coverage.CoverageData(basename=str(檔名))
        try:
            資料.read()
        except coverage.CoverageException as 錯:
            _錯(f"RUN_ERROR：讀取 coverage 失敗：{錯}", 來源=錯)
        for 實際檔名 in 資料.measured_files():
            if Path(實際檔名).resolve() == 目標.resolve():
                命中.update(_資料行(資料, 實際檔名, 上下文))
    return 命中


def _可執行行(文字: str) -> set[int]:
    try:
        樹 = ast.parse(文字)
    except SyntaxError as 錯:
        _錯(f"RUN_ERROR：目標不是可剖析的 Python：{錯}", 來源=錯)
    文件字串行: set[int] = set()
    for 節點 in ast.walk(樹):
        if not isinstance(節點, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not 節點.body:
            continue
        第一個 = 節點.body[0]
        if (
            isinstance(第一個, ast.Expr)
            and isinstance(第一個.value, ast.Constant)
            and isinstance(第一個.value.value, str)
        ):
            文件字串行.update(range(第一個.lineno, (第一個.end_lineno or 第一個.lineno) + 1))
    可執行: set[int] = set()
    for 節點 in ast.walk(樹):
        行 = getattr(節點, "lineno", None)
        if isinstance(行, int) and 行 not in 文件字串行:
            可執行.add(行)
    return 可執行


def _推導破壞行(目標: Path, 一筆: 變異) -> frozenset[int]:
    """從操作錨點推導被破壞的所有原始碼行。"""
    try:
        錨點 = 一筆.操作.錨點
    except (AttributeError, TypeError) as 錯:
        _錯(f"RUN_ERROR：操作無法推導破壞行：{type(一筆.操作).__name__}", 來源=錯)
    if not isinstance(錨點, str) or not 錨點:
        _錯(f"RUN_ERROR：操作沒有可推導的文字錨點：{一筆.識別}")
    文字 = 目標.read_text(encoding="utf-8")
    if 文字.count(錨點) != 1:
        _錯(f"RUN_ERROR：錨點應恰好一次，實際 {文字.count(錨點)}：{錨點!r}")
    起點 = 文字.index(錨點)
    終點 = 起點 + len(錨點) - 1
    首行 = 文字.count("\n", 0, 起點) + 1
    末行 = 文字.count("\n", 0, 終點) + 1
    可執行行 = _可執行行(文字)
    要求 = frozenset(行 for 行 in range(首行, 末行 + 1) if 行 in 可執行行)
    if not 要求:
        # **多行字串的內容不是 executable 行，coverage 追不到。** 角色提示這類
        # 保證住在模組層的字串常數裡，錨點必然落在內容中間——一律炸的話，
        # 整類保證都不准登記。回空集合＝「沒有可追的覆蓋行，固定測試直接驗值」，
        # 跟顯式的 `必須覆蓋=frozenset()` 同一個語意。
        #
        # **只在模組層單一名稱的賦值時成立。** 函式內部推導不到行代表錨點打歪了，
        # 那要當場紅——否則刀看起來 KILLED，其實沒破壞到被測的東西。
        if _是模組層常數替換(文字, 一筆):
            return frozenset()
        _錯(f"RUN_ERROR：操作沒有可推導的 executable 行：{一筆.識別}")
    return 要求


def _是模組層常數替換(文字: str, 一筆: 變異) -> bool:
    """空覆蓋標記只准用在模組層單一名稱的替換。"""
    if not isinstance(一筆.操作, 替換一次):
        return False
    樹 = ast.parse(文字)
    起點 = 文字.count("\n", 0, 文字.index(一筆.操作.錨點)) + 1
    for 節點 in 樹.body:
        if isinstance(節點, ast.Assign):
            目標們 = 節點.targets
        elif isinstance(節點, ast.AnnAssign):
            目標們 = [節點.target]
        else:
            continue
        末行 = 節點.end_lineno or 節點.lineno
        if 節點.lineno <= 起點 <= 末行:
            return all(isinstance(目標, ast.Name) for 目標 in 目標們)
    return False


def _覆蓋率前置(根目錄: Path, 一筆: 變異) -> None:
    """**目標檔不是 Python 就跳過這一關。**

    這一關問的是「點名的測試有沒有真的走到被破壞的那一行」——
    那個問題只對可執行的程式碼成立。文件與資料檔（路線圖的 JSON、
    設計文件）沒有「執行行」，`ast.parse` 當場 `SyntaxError`，
    而那個錯看起來像 runner 壞了，不像「這種目標檔不適用這一關」。

    跳過的代價說清楚：資料檔的刀**分不出 `KILLED` 與 `WRONG_TEST`**——
    測試紅了，但可能是別的原因紅的。**所以資料檔的刀要挑「唯一會讓那支
    測試紅」的破壞**，例如把某個路徑換成另一個真的存在的路徑。
    """
    目標 = 根目錄 / 一筆.目標檔
    if 目標.suffix != ".py":
        return
    推導的行 = _推導破壞行(目標, 一筆)
    if 一筆.必須覆蓋 is None:
        必須覆蓋 = 推導的行
    elif not 一筆.必須覆蓋 and _是模組層常數替換(目標.read_text(encoding="utf-8"), 一筆):
        # 這個顯式空集合是「沒有可追 coverage 行」的標記，不是預設值。
        必須覆蓋 = frozenset()
    elif not 一筆.必須覆蓋:
        # 一般空集合沒有額外斷言，破壞行仍由操作推導並必須被覆蓋。
        必須覆蓋 = 推導的行
    else:
        必須覆蓋 = 推導的行 | 一筆.必須覆蓋
    with tempfile.TemporaryDirectory(prefix="nova-覆蓋率-", dir="/tmp") as 暫存:
        資料檔 = Path(暫存) / ".coverage"
        for nodeid in 一筆.該紅:
            _丟掉pycache(根目錄)
            try:
                結果 = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "coverage",
                        "run",
                        "--parallel-mode",
                        f"--source={根目錄 / 'src'},{根目錄 / 'tests'}",
                        f"--context={nodeid}",
                        "-m",
                        "pytest",
                        "-p",
                        "tests.負控.執行器",
                        "-p",
                        "no:randomly",
                        "-q",
                        nodeid,
                    ],
                    cwd=根目錄,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=一筆.最多秒,
                    env=_環境(根目錄, COVERAGE_FILE=str(資料檔)),
                )
            except (OSError, subprocess.TimeoutExpired) as 錯:
                _錯(f"RUN_ERROR：coverage 無法完成：{nodeid}", 來源=錯)
            if 結果.returncode != 0:
                _錯(f"RUN_ERROR：coverage 測試失敗：{nodeid}\n{結果.stdout}{結果.stderr}")
            _判定覆蓋(一筆, _覆蓋的行(資料檔, 目標, nodeid), 必須覆蓋)


def _判定覆蓋(
    一筆: 變異,
    命中: set[int],
    必須覆蓋: frozenset[int] | None = None,
) -> None:
    要求 = 一筆.必須覆蓋 if 必須覆蓋 is None else 必須覆蓋
    if 要求 is None:
        _錯(f"RUN_ERROR：沒有覆蓋要求：{一筆.識別}")
    if not 要求 <= 命中:
        缺少 = 要求 - 命中
        _錯(f"WRONG_TEST：{一筆.識別} 的 {一筆.該紅} 沒覆蓋 {sorted(缺少)}")


def _確認錨點(一筆: 變異, 目標: Path) -> None:
    錨點 = 一筆.操作.錨點
    次數 = 目標.read_text(encoding="utf-8").count(錨點)
    if 次數 != 1:
        _錯(f"RUN_ERROR：錨點應恰好一次，實際 {次數}：{錨點!r}")


def _判定結果(
    退出碼: int | None,
    *,
    已收集: bool,
    逾時: bool,
    預期掛住: bool,
) -> str:
    if 逾時:
        if 預期掛住:
            return "KILLED"
        _錯("RUN_ERROR：非預期逾時")
    if not 已收集:
        _錯("RUN_ERROR：沒有正常收集到 nodeid")
    if 退出碼 == 1:
        return "KILLED"
    if 退出碼 == 0:
        _錯("SURVIVED：變異後測試仍然通過")
    _錯(f"RUN_ERROR：pytest exit {退出碼}")


def _跑變異測試(根目錄: Path, 一筆: 變異) -> None:
    for nodeid in 一筆.該紅:
        _要求收集(根目錄, nodeid, 一筆.最多秒)
        _丟掉pycache(根目錄)
        try:
            結果 = subprocess.run(
                [sys.executable, "-m", "pytest", "-p", "no:randomly", "-q", nodeid],
                cwd=根目錄,
                capture_output=True,
                text=True,
                check=False,
                timeout=一筆.最多秒,
                env=_環境(根目錄),
            )
            _判定結果(
                結果.returncode,
                已收集=True,
                逾時=False,
                預期掛住=一筆.預期掛住,
            )
        except subprocess.TimeoutExpired as 錯:
            _判定結果(None, 已收集=True, 逾時=True, 預期掛住=一筆.預期掛住)
            if not 一筆.預期掛住:
                _錯(f"RUN_ERROR：非預期逾時：{nodeid}", 來源=錯)
        except OSError as 錯:
            _錯(f"RUN_ERROR：pytest 無法啟動：{nodeid}", 來源=錯)


def _執行變異副本(根目錄: Path, 一筆: 變異) -> None:
    _丟掉pycache(根目錄)
    _跑變異測試(根目錄, 一筆)


def 執行變異(一筆: 變異, *, 根目錄: Path) -> None:
    """依序執行基線、覆蓋率前置與隔離變異。"""
    if 一筆.平台 not in ("任何平台", sys.platform):
        _錯(f"RUN_ERROR：不支援的平台：{一筆.平台}")
    if not 一筆.該紅:
        _錯(f"RUN_ERROR：{一筆.識別} 沒有該紅測試")
    原始目標 = 根目錄 / 一筆.目標檔
    if not 原始目標.is_file():
        _錯(f"RUN_ERROR：目標不存在：{一筆.目標檔}")
    基線 = _雜湊(原始目標)
    with tempfile.TemporaryDirectory(prefix="nova-負控-", dir="/tmp") as 暫存:
        暫存根 = Path(暫存)
        基線副本 = 暫存根 / "基線"
        _複製專案(根目錄, 基線副本)
        if _雜湊(基線副本 / 一筆.目標檔) != 基線:
            _錯(f"RUN_ERROR：基線 SHA256 不一致：{一筆.識別}")
        _跑基線(基線副本, 一筆)
        _覆蓋率前置(基線副本, 一筆)

        變異副本 = 暫存根 / "變異"
        _複製專案(根目錄, 變異副本)
        目標 = 變異副本 / 一筆.目標檔
        if _雜湊(目標) != 基線:
            _錯(f"RUN_ERROR：變異副本基線 SHA256 不一致：{一筆.識別}")
        _確認錨點(一筆, 目標)
        _, 變異後 = 一筆.操作.套用(目標)
        if 變異後 == 基線:
            _錯(f"RUN_ERROR：變異後 SHA256 沒變：{一筆.識別}")
        _執行變異副本(變異副本, 一筆)


def 執行全部(登記: Iterable[變異], *, 根目錄: Path) -> None:
    for 一筆 in 登記:
        執行變異(一筆, 根目錄=根目錄)

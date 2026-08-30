"""執行登記過的精確負控。"""

# 這個 runner 需要把失敗分類塞進例外訊息，保留完整診斷比 lint 的例外訊息風格重要。
# ruff: noqa: EM101, EM102, TRY003

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path

import coverage

from .登記 import 變異


class 負控錯誤(RuntimeError):
    """負控本身無法判定時的錯誤。"""


def _雜湊(檔案: Path) -> str:
    return hashlib.sha256(檔案.read_bytes()).hexdigest()


def _錯(訊息: str) -> 負控錯誤:
    return 負控錯誤(訊息)


def _忽略快取(_: str, 名字: list[str]) -> set[str]:
    return {名字 for 名字 in 名字 if 名字 == "__pycache__" or 名字.endswith(".pyc")}


def _複製專案(來源: Path, 目的: Path) -> None:
    目的.mkdir()
    for 名稱 in ("src", "tests"):
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
        raise _錯(f"RUN_ERROR：pytest 逾時：{參數[0]}") from 錯
    except OSError as 錯:
        raise _錯(f"RUN_ERROR：pytest 無法啟動：{錯}") from 錯


def _要求收集(根目錄: Path, nodeid: str, 最多秒: float) -> None:
    結果 = _pytest(根目錄, "--collect-only", nodeid, timeout=最多秒)
    if 結果.returncode != 0:
        raise _錯(f"RUN_ERROR：找不到或無法收集 {nodeid}\n{結果.stdout}{結果.stderr}")


def _跑基線(根目錄: Path, 一筆: 變異) -> None:
    for nodeid in 一筆.該紅:
        _要求收集(根目錄, nodeid, 一筆.最多秒)
        結果 = _pytest(根目錄, nodeid, timeout=一筆.最多秒)
        _判定基線(結果.returncode, nodeid, 結果.stdout + 結果.stderr)


def _判定基線(退出碼: int, nodeid: str, 輸出: str = "") -> None:
    if 退出碼 != 0:
        raise _錯(f"BASELINE_RED：{nodeid}\n{輸出}")


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
            raise _錯(f"RUN_ERROR：讀取 coverage 失敗：{錯}") from 錯
        for 實際檔名 in 資料.measured_files():
            if Path(實際檔名).resolve() == 目標.resolve():
                命中.update(_資料行(資料, 實際檔名, 上下文))
    return 命中


def _覆蓋率前置(根目錄: Path, 一筆: 變異) -> None:
    目標 = 根目錄 / 一筆.目標檔
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
                        f"--source={根目錄 / 'src'}",
                        f"--context={nodeid}",
                        "-m",
                        "pytest",
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
                raise _錯(f"RUN_ERROR：coverage 無法完成：{nodeid}") from 錯
            if 結果.returncode != 0:
                raise _錯(f"RUN_ERROR：coverage 測試失敗：{nodeid}\n{結果.stdout}{結果.stderr}")
            _判定覆蓋(一筆, _覆蓋的行(資料檔, 目標, nodeid))


def _判定覆蓋(一筆: 變異, 命中: set[int]) -> None:
    if not 一筆.必須覆蓋 <= 命中:
        缺少 = 一筆.必須覆蓋 - 命中
        raise _錯(f"WRONG_TEST：{一筆.識別} 的 {一筆.該紅} 沒覆蓋 {sorted(缺少)}")


def _確認錨點(一筆: 變異, 目標: Path) -> None:
    錨點 = 一筆.操作.錨點
    次數 = 目標.read_text(encoding="utf-8").count(錨點)
    if 次數 != 1:
        raise _錯(f"RUN_ERROR：錨點應恰好一次，實際 {次數}：{錨點!r}")


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
        raise _錯("RUN_ERROR：非預期逾時")
    if not 已收集:
        raise _錯("RUN_ERROR：沒有正常收集到 nodeid")
    if 退出碼 == 1:
        return "KILLED"
    if 退出碼 == 0:
        raise _錯("SURVIVED：變異後測試仍然通過")
    raise _錯(f"RUN_ERROR：pytest exit {退出碼}")


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
                raise _錯(f"RUN_ERROR：非預期逾時：{nodeid}") from 錯
        except OSError as 錯:
            raise _錯(f"RUN_ERROR：pytest 無法啟動：{nodeid}") from 錯


def _執行變異副本(根目錄: Path, 一筆: 變異) -> None:
    _丟掉pycache(根目錄)
    _跑變異測試(根目錄, 一筆)


def 執行變異(一筆: 變異, *, 根目錄: Path) -> None:
    """依序執行基線、覆蓋率前置與隔離變異。"""
    if 一筆.平台 not in ("任何平台", sys.platform):
        raise _錯(f"RUN_ERROR：不支援的平台：{一筆.平台}")
    if not 一筆.該紅:
        raise _錯(f"RUN_ERROR：{一筆.識別} 沒有該紅測試")
    原始目標 = 根目錄 / 一筆.目標檔
    if not 原始目標.is_file():
        raise _錯(f"RUN_ERROR：目標不存在：{一筆.目標檔}")
    基線 = _雜湊(原始目標)
    with tempfile.TemporaryDirectory(prefix="nova-負控-", dir="/tmp") as 暫存:
        暫存根 = Path(暫存)
        基線副本 = 暫存根 / "基線"
        _複製專案(根目錄, 基線副本)
        if _雜湊(基線副本 / 一筆.目標檔) != 基線:
            raise _錯(f"RUN_ERROR：基線 SHA256 不一致：{一筆.識別}")
        _跑基線(基線副本, 一筆)
        _覆蓋率前置(基線副本, 一筆)

        變異副本 = 暫存根 / "變異"
        _複製專案(根目錄, 變異副本)
        目標 = 變異副本 / 一筆.目標檔
        if _雜湊(目標) != 基線:
            raise _錯(f"RUN_ERROR：變異副本基線 SHA256 不一致：{一筆.識別}")
        _確認錨點(一筆, 目標)
        _, 變異後 = 一筆.操作.套用(目標)
        if 變異後 == 基線:
            raise _錯(f"RUN_ERROR：變異後 SHA256 沒變：{一筆.識別}")
        _執行變異副本(變異副本, 一筆)


def 執行全部(登記: Iterable[變異], *, 根目錄: Path) -> None:
    for 一筆 in 登記:
        執行變異(一筆, 根目錄=根目錄)

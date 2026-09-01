"""ruff 豁免的登記表與純函式比對。"""

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

#: 這是 pyproject.toml 現況的登記，不是讓 ruff 變綠的另一份設定。
期望ruff豁免 = frozenset(
    {
        "ignore:N",
        "ignore:PLC2401",
        "ignore:PLC2403",
        "ignore:RUF001",
        "ignore:RUF002",
        "ignore:RUF003",
        "ignore:D203",
        "ignore:D213",
        "ignore:D400",
        "ignore:D415",
        "ignore:D403",
        "ignore:ISC001",
        "extend-exclude:docs",
        "format:exclude:tests/單元/test_角色工廠.py",
        "per-file-ignores:src/nova/載體/命令列.py:T201",
        "per-file-ignores:tests/**:S101",
        "per-file-ignores:tests/**:D100",
        "per-file-ignores:tests/**:D101",
        "per-file-ignores:tests/**:D102",
        "per-file-ignores:tests/**:D103",
        "per-file-ignores:tests/**:D104",
        "per-file-ignores:tests/**:FBT001",
        "per-file-ignores:tests/**:FBT002",
        "per-file-ignores:tests/**:FBT003",
        "per-file-ignores:tests/**:PLR2004",
        "per-file-ignores:tests/**:ANN401",
        "per-file-ignores:tests/**:SLF001",
        "per-file-ignores:tests/**:S603",
        "per-file-ignores:tests/**:S607",
        # 併成 `X not in (甲, 乙)` 會讓斷言訊息看不出是哪一邊壞掉，那正是測試的價值。
        "per-file-ignores:tests/**:PLR1714",
        "per-file-ignores:tests/**:PLC0415",
        "per-file-ignores:tests/**:PLR0402",
    }
)

_規則豁免鍵 = ("ignore", "extend-ignore")
_檔案豁免鍵 = ("per-file-ignores", "extend-per-file-ignores")
_排除清單鍵 = ("exclude", "extend-exclude")
_輸入範圍鍵 = ("include", "extend-include")


def _表(來源: Mapping[str, object], 名稱: str) -> Mapping[str, object]:
    值 = 來源.get(名稱)
    if not isinstance(值, dict):
        訊息 = f"TOML 缺少表：{名稱}"
        raise TypeError(訊息)
    return cast(Mapping[str, object], 值)


def _字串列(值: object, 名稱: str) -> tuple[str, ...]:
    if not isinstance(值, list) or not all(isinstance(項, str) for 項 in 值):
        訊息 = f"TOML 的 {名稱} 不是字串陣列"
        raise TypeError(訊息)
    return tuple(cast(list[str], 值))


def _表或空(來源: Mapping[str, object], 名稱: str) -> Mapping[str, object]:
    """讀取可省略的 TOML 表；設定缺席時視為空表。"""
    值 = 來源.get(名稱, {})
    if not isinstance(值, dict):
        訊息 = f"TOML 的 {名稱} 不是表"
        raise TypeError(訊息)
    return cast(Mapping[str, object], 值)


def _展平規則(設定: Mapping[str, object], 鍵們: tuple[str, ...]) -> set[str]:
    return {f"{鍵}:{規則}" for 鍵 in 鍵們 for 規則 in _字串列(設定.get(鍵, []), 鍵)}


def _展平檔案規則(設定: Mapping[str, object], 鍵們: tuple[str, ...]) -> set[str]:
    豁免: set[str] = set()
    for 鍵 in 鍵們:
        檔案規則 = _表或空(設定, 鍵)
        豁免.update(
            f"{鍵}:{路徑}:{規則}"
            for 路徑, 規則們 in 檔案規則.items()
            for 規則 in _字串列(規則們, f"{鍵}.{路徑}")
        )
    return 豁免


def _展平路徑鍵(
    設定: Mapping[str, object],
    *,
    表名: str,
    鍵們: tuple[str, ...],
) -> set[str]:
    豁免: set[str] = set()
    for 鍵 in 鍵們:
        名稱 = f"{表名}:{鍵}" if 表名 else 鍵
        豁免.update(f"{名稱}:{路徑}" for 路徑 in _字串列(設定.get(鍵, []), 名稱))
    return 豁免


def 解析ruff豁免(內容: str) -> frozenset[str]:
    """把 TOML 裡的 ruff 豁免與檔案排除攤平成可比對的集合。

    規則豁免用 `ignore:X`；檔案規則用 `per-file-ignores:路徑:規則`（或 `extend-per-file-ignores`）。
    外接設定用 `extend:路徑`；頂層排除／輸入範圍用 `鍵:路徑`，巢狀排除則用
    `表名:鍵:路徑`（例如 `format:exclude:路徑`）。
    """
    根 = cast(Mapping[str, object], tomllib.loads(內容))
    ruff設定 = _表(_表(根, "tool"), "ruff")
    # `lint`／`format` 表都可省略。
    lint設定 = _表或空(ruff設定, "lint")
    規則豁免 = _展平規則(ruff設定, _規則豁免鍵) | _展平規則(lint設定, _規則豁免鍵)
    檔案豁免 = _展平檔案規則(ruff設定, _檔案豁免鍵) | _展平檔案規則(lint設定, _檔案豁免鍵)
    # Ruff 的 lint 表只有 exclude，沒有 extend-exclude；完整盤點見 docs/負控紀錄.md。
    lint排除 = _展平路徑鍵(lint設定, 表名="lint", 鍵們=("exclude",))
    格式設定 = _表或空(ruff設定, "format")
    格式排除 = _展平路徑鍵(格式設定, 表名="format", 鍵們=_排除清單鍵)
    頂層排除 = _展平路徑鍵(ruff設定, 表名="", 鍵們=_排除清單鍵)
    輸入範圍 = _展平路徑鍵(ruff設定, 表名="", 鍵們=_輸入範圍鍵)
    外接設定路徑 = ruff設定.get("extend")
    if 外接設定路徑 is not None and not isinstance(外接設定路徑, str):
        訊息 = "TOML 的 extend 不是字串"
        raise TypeError(訊息)
    所有豁免 = 規則豁免 | 檔案豁免
    所有豁免.update(lint排除, 格式排除, 頂層排除, 輸入範圍)
    if 外接設定路徑 is not None:
        所有豁免.add(f"extend:{外接設定路徑}")
    return frozenset(所有豁免)


def 比對ruff豁免(
    實際: frozenset[str], 期望: frozenset[str] = 期望ruff豁免
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """回傳「多了、少了」；順序固定，方便人看也方便測試。"""
    return tuple(sorted(實際 - 期望)), tuple(sorted(期望 - 實際))


def 判定ruff豁免(實際: frozenset[str], 期望: frozenset[str] = 期望ruff豁免) -> tuple[bool, str]:
    """判定豁免集合並產生可行動的證據。"""
    多了, 少了 = 比對ruff豁免(實際, 期望)
    if not 多了 and not 少了:
        return True, "ruff 豁免符合登記表"
    訊息 = (
        "ruff 豁免與登記表不一致。\n"
        f"多了：{'、'.join(多了) or '無'}\n"
        f"少了：{'、'.join(少了) or '無'}\n"
        "加豁免不是修 lint。要加，先改登記表並說明理由"
    )
    return False, 訊息


def 檢查ruff豁免(根目錄: Path) -> tuple[bool, str]:
    """檢查專案的 ruff 豁免是否與 Python 登記表一致。"""
    try:
        內容 = (根目錄 / "pyproject.toml").read_text(encoding="utf-8")
        實際 = 解析ruff豁免(內容)
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError) as 錯:
        return False, f"讀取 ruff 豁免失敗：{錯}"

    return 判定ruff豁免(實際)

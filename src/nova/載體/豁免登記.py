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
    }
)


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
    return tuple(項 for 項 in 值 if isinstance(項, str))


def 解析ruff豁免(內容: str) -> frozenset[str]:
    """把 TOML 裡兩處 ruff 豁免攤平成可比對的集合。"""
    根 = cast(Mapping[str, object], tomllib.loads(內容))
    lint = _表(_表(_表(根, "tool"), "ruff"), "lint")
    全域 = {f"ignore:{規則}" for 規則 in _字串列(lint.get("ignore", []), "ignore")}
    檔案 = _表(lint, "per-file-ignores")
    檔案豁免 = {
        f"per-file-ignores:{路徑}:{規則}"
        for 路徑, 規則們 in 檔案.items()
        for 規則 in _字串列(規則們, f"per-file-ignores.{路徑}")
    }
    return frozenset(全域 | 檔案豁免)


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

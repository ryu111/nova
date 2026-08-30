"""規則表本身的防護。

規則表是閘的 context（規格 §2.2 第一問）。它壞掉的方式很安靜：
代碼撞名、閘點打錯、提交閘漏了某條 CI 有的規則——都不會有人當場發現。
"""

from pathlib import Path

import pytest

from nova.載體.規則表 import 平行度, 建規則表
from nova.載體.閘 import 型別, 測試, 規則, 閘點清單, 靜態


def _規則表() -> list[規則]:
    return 建規則表(Path("/不存在也沒關係/建表時不該碰硬碟"))


def test_代碼不重複() -> None:
    代碼 = [條.代碼 for 條 in _規則表()]
    assert len(代碼) == len(set(代碼)), f"代碼撞名：{代碼}"


def test_代碼是ASCII() -> None:
    """代碼是跨程序 failure code，要能出現在 CI log、hook 輸出、別的工具裡。"""
    for 條 in _規則表():
        assert 條.代碼.isascii(), f"{條.代碼} 不是 ASCII"


def test_閘點都合法() -> None:
    for 條 in _規則表():
        assert 條.閘點 <= 閘點清單, f"{條.代碼} 掛到未知閘點 {條.閘點 - 閘點清單}"


def test_階段都合法() -> None:
    for 條 in _規則表():
        assert 條.階段 in (靜態, 型別, 測試), f"{條.代碼} 階段 {條.階段} 不合法"


def test_提交閘是ci閘的子集() -> None:
    """提交閘擋掉的，CI 一定也要擋——否則本地綠、推上去紅，或更糟：反過來。"""
    表 = _規則表()
    ci代碼 = {條.代碼 for 條 in 表 if "ci" in 條.閘點}
    只在提交 = {條 for 條 in 表 if "提交" in 條.閘點 and 條.代碼 not in ci代碼}
    for 條 in 只在提交:
        assert 條.涵蓋於, f"{條.代碼} 只在提交閘，CI 抓不到，也沒宣告涵蓋者"
        assert 條.涵蓋於 in ci代碼, f"{條.代碼} 宣告涵蓋於 {條.涵蓋於}，但 CI 沒有這條"


def test_每條規則都有掛閘點() -> None:
    """掛零個閘點＝永遠不會跑，比沒寫還糟——看起來有防護。"""
    for 條 in _規則表():
        assert 條.閘點, f"{條.代碼} 沒掛任何閘點"


def test_四道閘都在ci裡() -> None:
    ci代碼 = {條.代碼 for 條 in _規則表() if "ci" in 條.閘點}
    for 必要 in ("ruff-check", "ruff-format", "mypy"):
        assert 必要 in ci代碼, f"CI 缺少 {必要}"
    assert any(代碼.startswith("pytest") for 代碼 in ci代碼), "CI 沒有跑測試"


def test_三條新規則都上了() -> None:
    表 = 建規則表(Path.cwd())
    代碼 = {條.代碼 for 條 in 表}
    for 必要 in ("lang-traditional", "no-secrets", "test-count"):
        assert 必要 in 代碼, f"缺少 {必要}"


def test_登記的負控runner只接在ci閘() -> None:
    """負控 runner 必須被 CI 執行，但不能拖進十秒提交閘。"""
    負控 = next(
        (條 for 條 in _規則表() if 條.代碼 == "registered-mutation"),
        None,
    )

    assert 負控 is not None, "CI 缺少 registered-mutation 負控 runner"
    assert 負控.閘點 == frozenset({"ci"}), f"負控 runner 閘點錯了：{負控.閘點}"


def test_serial佔比規則已登記且只掛在ci閘() -> None:
    """serial 佔比規則只掛在 CI 閘，不掛提交閘避免 collect 拖垮預算。"""
    表 = _規則表()
    serial條 = next((條 for 條 in 表 if 條.代碼 == "serial-ratio"), None)
    assert serial條 is not None, "缺少 serial-ratio 規則"
    assert "ci" in serial條.閘點, "serial-ratio 必須掛在 ci 閘點"
    assert "提交" not in serial條.閘點, "serial-ratio 不准掛在提交閘（collect 會拖垮 10 秒預算）"


def test_涵蓋宣告不能指向自己() -> None:
    for 條 in _規則表():
        assert 條.涵蓋於 != 條.代碼, f"{條.代碼} 宣告自己涵蓋自己，等於沒宣告"


def test_兩個閘都排除真cli與真端點() -> None:
    """真 CLI 與真端點測試會碰外部資源——不准溜進任何一個閘。

    忘了排除的話 CI 會在沒有資源的機器上紅，而且是紅在跟改動無關的地方。
    """
    根目錄 = Path(__file__).resolve().parents[2]
    命令列們: list[tuple[str, ...]] = []
    for 條 in 建規則表(根目錄):
        if not 條.代碼.startswith("pytest"):
            continue
        閉包 = getattr(條.檢查, "__closure__", None)
        assert 閉包 is not None, f"{條.代碼} 不是包出來的外部指令，這支測試要改寫"
        命令 = next(
            (
                格.cell_contents
                for 格 in 閉包
                if isinstance(格.cell_contents, tuple)
                and 格.cell_contents
                and 格.cell_contents[0] == "pytest"
            ),
            None,
        )
        assert isinstance(命令, tuple), f"{條.代碼} 找不到 pytest 命令列"
        命令列們.append(tuple(str(項) for 項 in 命令))
    帶標記的 = [命令 for 命令 in 命令列們 if "-m" in 命令]
    assert 帶標記的, "找不到帶 -m 的 pytest 規則"
    for 命令 in 帶標記的:
        命令字串 = " ".join(命令)
        assert "not 真cli" in 命令字串, f"這條 pytest 規則沒排除真cli：{命令}"
        assert "not 真端點" in 命令字串, f"這條 pytest 規則沒排除真端點：{命令}"


class Test平行度:
    """平行測試不吃滿核心——競爭造成的紅燈是雜訊不是訊號。"""

    @pytest.mark.parametrize(("核心", "預期"), [(64, 4), (16, 4), (8, 4), (4, 3), (2, 1), (1, 1)])
    def test_四分之三的核心但有上限(self, 核心: int, 預期: int) -> None:
        """兩條規則疊起來：不吃滿（3/4），而且不超過套件攤得掉的 worker 數。

        實測這套測試 16 核開 12 個 worker（3.43 秒）比開 4 個（2.34 秒）**慢**——
        worker 自己的啟動成本吃掉了平行的收益。核心多不代表該開多。
        """
        assert 平行度(核心) == 預期

    def test_上限不會反過來變成下限(self) -> None:
        """小機器不准被上限「補」上去。CI 是 4 核，只能開 3 個。"""
        assert 平行度(4) == 3

    def test_再少也至少一個(self) -> None:
        """`-n 0` 會讓 pytest-xdist 報錯，不能算出 0。"""
        assert 平行度(1) >= 1

    def test_不會吃滿(self) -> None:
        for 核心 in (2, 4, 8, 16, 32, 64):
            assert 平行度(核心) < 核心, f"{核心} 核算出來吃滿了"

    def test_規則表用的是算出來的數字不是auto(self) -> None:
        """`-n auto` 會吃滿——改回去這支要紅。"""
        原始碼 = (Path(__file__).resolve().parents[2] / "src/nova/載體/規則表.py").read_text(
            encoding="utf-8"
        )
        assert '"auto"' not in 原始碼, "-n auto 會吃滿核心"
        assert "平行度()" in 原始碼

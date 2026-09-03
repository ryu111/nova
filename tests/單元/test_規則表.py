"""規則表本身的防護。

規則表是閘的 context（規格 §2.2 第一問）。它壞掉的方式很安靜：
代碼撞名、閘點打錯、提交閘漏了某條 CI 有的規則——都不會有人當場發現。
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from nova.契約.工作流 import 測試員修得掉的規則代碼
from nova.載體.規則表 import 平行度, 建規則表, 版本
from nova.載體.閘 import 型別, 測試, 規則, 閘點清單, 靜態

#: `挖pytest命令列` fixture 的形狀。跨檔 import conftest 會讓 mypy 把它
#: 算成兩個模組（見 `tests/conftest.py` 開頭），所以型別各寫一份。
_挖命令列型 = Callable[[規則], tuple[str, ...]]


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


def test_退給測試員的規則代碼都在規則表上() -> None:
    """守：`契約` 那份「測試員修得掉的規則代碼」跟規則表對得上帳，代碼改名要當場紅。

    `迴圈` 不准 import `載體`（`layer-boundaries` 那條閘擋著），所以那份集合住 `契約`，
    誰也不會在改規則代碼時順手改到它。對不上帳的話這條分流只是靜靜失效，
    症狀是「提交閘紅在測試檔時又開始收 4」——離改名那一手已經很遠了。
    """
    代碼 = {條.代碼 for 條 in _規則表()}
    漏掉的 = 測試員修得掉的規則代碼 - 代碼
    assert not 漏掉的, f"合格集合點名了規則表上沒有的代碼：{sorted(漏掉的)}"


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


def test_本線負控只掛在本線閘() -> None:
    """本線那幾把刀掛的是 `本線` 這個閘點，只有它，而且 CI 的全量那條不准跟著變窄。

    掛錯閘點的症狀全是綠：掛去 `ci` 的話判準第三步（`nova 閘 本線`）跑到零條規則、
    當場放行，線內還是等到 CI 才紅；掛去 `提交` 的話每次 commit 都付整台機器的錢。
    """
    表 = _規則表()
    本線 = next((條 for 條 in 表 if 條.代碼 == "registered-mutation-diff"), None)
    全量 = next((條 for 條 in 表 if 條.代碼 == "registered-mutation"), None)

    assert 本線 is not None, "規則表上沒有 registered-mutation-diff，判準第三步會跑到零條規則"
    assert 本線.閘點 == frozenset({"本線"}), f"本線負控掛錯閘點：{本線.閘點}"
    assert 本線.負責層 == "測試", f"刀紅了是測試員的事，負責層不對：{本線.負責層}"
    assert 全量 is not None and 全量.閘點 == frozenset({"ci"}), (
        "CI 的全量 220 把不准跟著變窄：本票只是把本線那幾把往前挪一次"
    )


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


def test_兩個閘都排除真cli與真端點(挖pytest命令列: _挖命令列型) -> None:
    """真 CLI 與真端點測試會碰外部資源——不准溜進任何一個閘。

    忘了排除的話 CI 會在沒有資源的機器上紅，而且是紅在跟改動無關的地方。
    """
    根目錄 = Path(__file__).resolve().parents[2]
    命令列們 = [挖pytest命令列(條) for 條 in 建規則表(根目錄) if 條.代碼.startswith("pytest")]
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


def test_文件即事實要在提交閘() -> None:
    """**被同一個錯抓過兩次之後補的。**

    `tests/驗收/test_文件即事實.py` 守「文件宣稱存在的檔案要真的存在」，
    但它住驗收層——`nova 閘 提交` 的 `pytest-unit` 只跑 `tests/單元`，跑不到它。
    結果是：改完文件、提交閘全綠、推上去 CI 才紅，而且 CI 的輸出把
    失敗詳情截成一排進度點，每次都要本地重跑一遍才知道紅在哪。

    2026-08-31 一天內中了兩次（E2E 產出的測試檔路徑、路線圖用來指「不存在」的路徑）。
    **兩次就是機械判準抓得到的證據**——那就該進閘，不是靠人記得。

    塞得進 10 秒預算：那 8 支測試實測 0.06 秒。
    """
    提交的 = {
        條.代碼 for 條 in 建規則表(Path("/不存在也沒關係/建表時不該碰硬碟")) if "提交" in 條.閘點
    }
    assert "docs-facts" in 提交的, (
        f"文件即事實不在提交閘裡，改完文件要推上去才會知道紅。現在有：{sorted(提交的)}"
    )


def test_版本跟著規則表的內容變(tmp_path: Path) -> None:
    """`成果` 帳上的 `policy_version` 要答「這次跑的時候規則表是哪一版」。

    **走內容雜湊，不走 git 的 commit**：閘是照**工作區那份**跑的，
    不是照 HEAD 那份跑的。改了還沒提交就跑一次的話，走 git 會給出
    上一版的答案——那比沒有答案更糟，因為它看起來像個答案。
    """
    甲 = tmp_path / "甲.py"
    甲.write_text("規則 = 1\n", encoding="utf-8")
    乙 = tmp_path / "乙.py"
    乙.write_text("規則 = 2\n", encoding="utf-8")

    assert 版本(甲) == 版本(甲), "同一份內容要給同一個答案，不然帳上比不了"
    assert 版本(甲) != 版本(乙), "內容不同就得看得出來，不然這一欄答不了歸因"


def test_沒給路徑就報自己這一版() -> None:
    """呼叫端不必知道規則表住哪個檔——那是規則表自己的知識。"""
    assert len(版本()) == 16

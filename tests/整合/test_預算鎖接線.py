"""預算鎖接線：純函式在、但沒人叫，預算鎖就不存在。

`docs/設計/06` 對持久化那一格的判準原話是「**有沒有任何一行程式碼會因為帳本裡的
東西改變行為**」。`花了多少`／`超支了嗎` 是純函式，測得再漂亮也不會讓任何一次
呼叫停下來——要有呼叫端，而且要**在打出去之前**。打完再判就只是事後記錄，
一塊錢都沒省。

跨執行預算鎖補的是工作流 stop rule 補不到的那一段：`nova 問` 一次只發一個請求，
單看那一次永遠沒有超支，但排程開始自己跑之後，一天兩百次是另一回事。

會寫檔、會跑主程式，所以住整合層。
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nova.契約.帳本 import 摘要
from nova.契約.退出碼 import 放行, 護欄碼, 阻擋
from nova.載體.命令列 import 主程式
from nova.載體.帳本讀取 import 讀一次執行

做假CLI型 = Callable[..., tuple[Path, Path]]


def _寫一次用掉(
    目錄: Path,
    *,
    token: int,
    成本: float | None = 0.5,
    幾小時前: float = 0.0,
    家: str = "codex",
) -> None:
    """在帳本裡種一次已經發生過的執行。

    **檔名開頭必須是真的 UTC 時戳**——讀取端靠字典序當時序，
    寫死成 `2026...` 的話「窗口外不算」那條測試會因為檔名而不是因為時間通過。
    """
    目錄.mkdir(parents=True, exist_ok=True)
    當時 = datetime.now(UTC) - timedelta(hours=幾小時前)
    識別 = 當時.strftime("%Y%m%dT%H%M%SZ") + f"-{int(幾小時前 * 10):04d}"
    完成: dict[str, object] = {
        "run": 識別,
        "seq": 2,
        "ts": 當時.isoformat(),
        "event": "call_finished",
        "call": 1,
        "family": 家,
        "outcome": "ok",
        "input_tokens": token // 2,
        "output_tokens": token - token // 2,
    }
    if 成本 is not None:
        完成["cost_usd"] = 成本
    事件們 = [
        {
            "run": 識別,
            "seq": 1,
            "ts": 當時.isoformat(),
            "event": "call_started",
            "call": 1,
            "family": 家,
        },
        完成,
    ]
    (目錄 / f"{識別}.jsonl").write_text(
        "".join(json.dumps(事, ensure_ascii=False) + "\n" for 事 in 事件們),
        encoding="utf-8",
    )


@pytest.fixture
def 接上假codex(monkeypatch: pytest.MonkeyPatch, 做假CLI: 做假CLI型) -> Path:
    """回傳「codex 有沒有被叫到」的紀錄檔。**存在＝真的打出去了。**"""
    假, 紀錄 = 做假CLI("codex")
    monkeypatch.setattr("nova.載體.模型.轉接.找執行檔", lambda 家, **_: 假)  # noqa: ARG005
    return 紀錄


class Test預設關閉:
    """「我主要是要看帳，但不要讓帳去把流程關閉。」——使用者明講的決定。

    熔斷是這樣，預算也是這樣。機制存在、測得到、要用打開就有，
    但不准因為帳本裡的歷史而**預設**擋掉呼叫。
    """

    def test_不給旗標時歷史再多也照打(self, tmp_path: Path, 接上假codex: Path) -> None:
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=999_999, 成本=999.0)

        碼 = 主程式(["問", "--用", "codex", "--帳本目錄", str(帳本目錄), "在嗎"])

        assert 碼 == 放行
        assert 接上假codex.exists(), "沒開預算鎖就不該擋"


class Test超支要停在打出去之前:
    def test_超過token上限就不呼叫CLI(self, tmp_path: Path, 接上假codex: Path) -> None:
        """**這一條是這個檔案的重點**：擋在呼叫之前，不是事後記錄。"""
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=5000)

        碼 = 主程式(
            ["問", "--用", "codex", "--帳本目錄", str(帳本目錄), "--預算token", "1000", "在嗎"]
        )

        assert 碼 == 護欄碼
        assert not 接上假codex.exists(), "超支了還是把請求打出去，等於預算鎖不存在"

    @pytest.mark.usefixtures("接上假codex")
    def test_退出碼是護欄不是失敗(self, tmp_path: Path) -> None:
        """**4 不是壞了**，是停止規則按設計生效。

        壓成 1 的話，外圈的自動修復迴圈會很合理地去「修」它——
        而護欄最省事的修法就是把上限調高。要放寬是人的決定。
        """
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=5000)

        碼 = 主程式(
            ["問", "--用", "codex", "--帳本目錄", str(帳本目錄), "--預算token", "10", "在嗎"]
        )

        assert 碼 != 阻擋
        assert 碼 == 護欄碼

    @pytest.mark.usefixtures("接上假codex")
    def test_訊息要說得出用了多少與上限多少(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """「超支了」沒有下文的話，人不知道該調上限、該等，還是帳本壞了。"""
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=5000)

        主程式(["問", "--用", "codex", "--帳本目錄", str(帳本目錄), "--預算token", "1000", "在嗎"])

        錯誤 = capsys.readouterr().err
        assert "5000" in 錯誤
        assert "1000" in 錯誤

    def test_成本超過上限也擋(self, tmp_path: Path, 接上假codex: Path) -> None:
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=10, 成本=9.0)

        碼 = 主程式(
            ["問", "--用", "codex", "--帳本目錄", str(帳本目錄), "--預算美金", "1.0", "在嗎"]
        )

        assert 碼 == 護欄碼
        assert not 接上假codex.exists()


class Test不准擋過頭:
    """全部擋掉的話這個旗標一次都不能用。**擋錯比不擋更難查**。"""

    def test_沒超過就照打(self, tmp_path: Path, 接上假codex: Path) -> None:
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=100)

        碼 = 主程式(
            ["問", "--用", "codex", "--帳本目錄", str(帳本目錄), "--預算token", "100000", "在嗎"]
        )

        assert 碼 == 放行
        assert 接上假codex.exists()

    def test_窗口外的歷史不算(self, tmp_path: Path, 接上假codex: Path) -> None:
        """**沒有窗口的預算不是預算，是一次性的封頂**——

        用了三個月之後永遠超支，然後使用者只能把上限調高，那就等於沒有。
        """
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=999_999, 幾小時前=48)

        碼 = 主程式(
            [
                "問",
                "--用",
                "codex",
                "--帳本目錄",
                str(帳本目錄),
                "--預算token",
                "1000",
                "--預算幾小時",
                "24",
                "在嗎",
            ]
        )

        assert 碼 == 放行
        assert 接上假codex.exists()

    def test_算不出成本時成本上限一律放行(self, tmp_path: Path, 接上假codex: Path) -> None:
        """**這一條方向跟「不確定就擋」相反，而且是刻意的。**

        codex 與 agy 都不回成本。算不出成本就擋的話，預算鎖會變成
        「永遠擋住」——那不是保護，那是壞掉。
        擋不住的時候要說得出擋不住，不要假裝擋得住。
        """
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=100, 成本=None)

        碼 = 主程式(
            ["問", "--用", "codex", "--帳本目錄", str(帳本目錄), "--預算美金", "0.01", "在嗎"]
        )

        assert 碼 == 放行
        assert 接上假codex.exists()

    @pytest.mark.usefixtures("接上假codex")
    def test_沒有帳本目錄就是沒花過(self, tmp_path: Path) -> None:
        """第一次跑的人不該被自己還沒有的歷史擋住。"""
        碼 = 主程式(
            [
                "問",
                "--用",
                "codex",
                "--帳本目錄",
                str(tmp_path / "還沒有的帳"),
                "--預算token",
                "10",
                "在嗎",
            ]
        )

        assert 碼 == 放行


class Test窗口外的檔連開都不開:
    """**這一組釘的是「開幾個檔」，不是「算出多少」。**

    時間過濾本來就由 `花了多少` 做，所以「窗口外的不算」拿掉檔名過濾照樣綠——
    第一次負控就是這樣沒紅的。但檔名過濾不是裝飾：每次呼叫前把整個專案
    三個月的帳本全部開來讀，是新的成本漏洞，而**沒有測試背書的最佳化
    下一個人會很合理地把它刪掉**。

    檔名開頭就是 UTC 時戳，字典序就是時序（`列出執行` 新的在前），
    所以遇到第一個舊的就可以停。
    """

    @pytest.mark.usefixtures("接上假codex")
    def test_三個月前的帳本不會被開起來(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=100, 幾小時前=0)
        # **從 2 天前起跳，不從 1 天**：檔名只精確到秒，剛好卡在窗口邊界的那個檔
        # 會被檔名過濾放進來、再被 `花了多少` 濾掉，讓這支測試多一個檔而變得會飄。
        for 幾天前 in range(2, 41):
            _寫一次用掉(帳本目錄, token=100, 幾小時前=幾天前 * 24)
        開過: list[Path] = []
        真的讀 = 讀一次執行

        def 記一筆(檔: Path) -> 摘要:
            開過.append(檔)
            return 真的讀(檔)

        # **打在 `命令列` 的名字上，不是 `帳本讀取` 的**——`from ... import` 之後
        # 呼叫端查的是自己模組裡的那個名字，改到來源模組不會有任何效果
        # （改了、測試綠、其實沒接上，就是「用規避換來的假綠」）。
        monkeypatch.setattr("nova.載體.命令列.讀一次執行", 記一筆)

        碼 = 主程式(
            [
                "問",
                "--用",
                "codex",
                "--帳本目錄",
                str(帳本目錄),
                "--預算token",
                "100000",
                "--預算幾小時",
                "24",
                "在嗎",
            ]
        )

        assert 碼 == 放行
        assert len(開過) == 1, f"窗口內只有 1 次執行，卻開了 {len(開過)} 個檔"


class Test寫端與讀端要對得上:
    """**檔名時戳是兩邊共用的約定**：`新執行識別碼` 寫、`_窗口內的執行` 讀。

    格式走散的話，窗口過濾會靜默地濾掉**全部**——看起來像「從來沒花過」，
    預算鎖整個 fail-open 而且一個錯誤訊息都沒有。

    這一組**不自己組檔名**（其他測試的 `_寫一次用掉` 用的是它自己的 strftime，
    兩邊一起走錯的話它照樣綠），改用真的寫端寫一次，再讓真的讀端去算。
    """

    def test_剛剛那次自己記的帳下一次就算得進去(self, tmp_path: Path, 接上假codex: Path) -> None:
        帳本目錄 = tmp_path / "帳"

        先跑一次 = 主程式(["問", "--用", "codex", "--帳本目錄", str(帳本目錄), "在嗎"])

        assert 先跑一次 == 放行
        assert 接上假codex.exists()
        碼 = 主程式(
            ["問", "--用", "codex", "--帳本目錄", str(帳本目錄), "--預算token", "1", "在嗎"]
        )
        assert 碼 == 護欄碼, "剛剛那次記的帳，下一次沒算進去"


class Test旗標本身給錯是用法錯誤不是護欄:
    def test_窗口零是阻擋不是護欄(self, tmp_path: Path, 接上假codex: Path) -> None:
        """**兩件事要分得開**：護欄生效（4）是設計中的停，旗標給錯（2）是人打錯字。

        窗口是 0 的話什麼都不算，預算鎖看起來在跑但永遠不會擋——**假的保護**。
        """
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=5000)

        碼 = 主程式(
            [
                "問",
                "--用",
                "codex",
                "--帳本目錄",
                str(帳本目錄),
                "--預算token",
                "10",
                "--預算幾小時",
                "0",
                "在嗎",
            ]
        )

        assert 碼 == 阻擋
        assert not 接上假codex.exists()


def test_工作流也有預算鎖(tmp_path: Path, 接上假codex: Path) -> None:
    """**排程自己跑的是工作流，不是 `nova 問`。**

    只接在 `問` 上的話，預算鎖剛好在最需要它的那條路徑上不存在。
    """
    帳本目錄 = tmp_path / "帳"
    _寫一次用掉(帳本目錄, token=5000)

    碼 = 主程式(
        [
            "工作流",
            "--用",
            "codex",
            "--審查用",
            "agy",
            "--帳本目錄",
            str(帳本目錄),
            "--預算token",
            "10",
            "--工作目錄",
            str(tmp_path),
            "隨便做點什麼",
        ]
    )

    assert 碼 == 護欄碼
    assert not 接上假codex.exists()

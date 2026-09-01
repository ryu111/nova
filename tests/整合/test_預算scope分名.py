"""預算 scope 分名：視窗累計、本輪累計、單次呼叫三個 scope 必須語意分明。

使用者踩到的痛點是 scope 名稱不是缺一個說明：
- `--預算token` / `--預算美金` / `--預算幾小時`：全專案時間視窗累計
- `--最多token`：工作流本輪累計
- `--單次上限token` / `--單次最多token`：每一次模型呼叫的單次上限

本檔案守護以下契約：
1. 視窗已用 1.3 億、單次上限 300 萬時：
   給 `--單次上限token 3000000` 照常發送；給 `--預算token 3000000` 在模型前以護欄碼 4 擋住。
2. 假回應單次超過上限時回 4、記清實際／上限、不接力重問。
3. 缺用量而無法判定時回 3，不把未知當 0。
4. help 說明清楚區分三個 scope，不把 `--預算token` 偷換成單次語意。
5. 單次上限非法數值（零或負數）回用法錯誤 2。
"""

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nova.契約.退出碼 import 放行, 未知, 護欄碼, 阻擋
from nova.載體.剖析器 import 建剖析器
from nova.載體.命令列 import 主程式, 處理們

做假CLI型 = Callable[..., tuple[Path, Path]]


def _寫一次用掉(
    目錄: Path,
    *,
    token: int,
    成本: float | None = 0.5,
    幾小時前: float = 0.0,
    家: str = "codex",
) -> None:
    """在帳本裡種一次已經發生過的執行（模擬視窗歷史累積用量）。"""
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


def _做假codex實錄(目錄: Path, token: int, 文字: str = "ok") -> Path:
    """產出帶有指定 input_tokens 的 codex 實錄檔。"""
    檔 = 目錄 / f"codex_{token}.jsonl"
    行們 = [
        "Reading additional input from stdin...",
        '{"type":"thread.started","thread_id":"00000000-0000-4000-8000-000000000001"}',
        '{"type":"turn.started"}',
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item_0", "type": "agent_message", "text": 文字},
            }
        ),
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": token,
                    "cached_input_tokens": 0,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 50,
                    "reasoning_output_tokens": 0,
                },
            }
        ),
    ]
    檔.write_text("\n".join(行們) + "\n", encoding="utf-8")
    return 檔


def _做假codex無用量實錄(目錄: Path, 文字: str = "ok") -> Path:
    """產出沒有 usage 欄位的 codex 實錄檔。"""
    檔 = 目錄 / "codex_no_usage.jsonl"
    行們 = [
        "Reading additional input from stdin...",
        '{"type":"thread.started","thread_id":"00000000-0000-4000-8000-000000000001"}',
        '{"type":"turn.started"}',
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item_0", "type": "agent_message", "text": 文字},
            }
        ),
        '{"type":"turn.completed"}',
    ]
    檔.write_text("\n".join(行們) + "\n", encoding="utf-8")
    return 檔


def _做假agy可接力失敗實錄(目錄: Path, token: int) -> Path:
    """產出「確定失敗但可以換下一顆」的 agy 實錄，而且**帶著用量**。

    接力鏈只有在第一顆失敗時才會往下走，所以要抓「單次超標之後還接力」
    這個病，第一顆非失敗不可——第一顆成功的話接力分支根本不會執行，
    那支測試看起來綠得很安穩，卻什麼都沒守到。

    `no such model` 會被分類成 `失敗代碼.模型不存在`＝確定失敗、可以換下一顆
    （不是權限被擋那條「能重做但不該重做」）。
    """
    檔 = 目錄 / f"agy_fail_{token}.json"
    檔.write_text(
        json.dumps(
            {
                "status": "FAILED",
                "error": "no such model: 這顆不存在",
                "response": "",
                "usage": {"input_tokens": token, "output_tokens": 50},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return 檔


def _找出子剖析器(剖析: argparse.ArgumentParser, 名: str) -> argparse.ArgumentParser:
    for 動作 in 剖析._actions:  # noqa: SLF001
        if isinstance(動作, argparse._SubParsersAction) and 動作.choices and 名 in 動作.choices:
            子 = 動作.choices[名]
            if isinstance(子, argparse.ArgumentParser):
                return 子
    raise KeyError(名)


@pytest.fixture
def 接上假codex(monkeypatch: pytest.MonkeyPatch, 做假CLI: 做假CLI型) -> Path:
    """回傳「codex 有沒有被叫到」的紀錄檔。**存在＝真的打出去了。**"""
    假, 紀錄 = 做假CLI("codex")
    monkeypatch.setattr("nova.載體.模型.轉接.找執行檔", lambda 家, **_: 假)  # noqa: ARG005
    return 紀錄


@pytest.fixture
def 接上假codex與agy(monkeypatch: pytest.MonkeyPatch, 做假CLI: 做假CLI型) -> tuple[Path, Path]:
    """回傳 (codex紀錄, agy紀錄)。"""
    假_codex, 紀錄_codex = 做假CLI("codex")
    假_agy, 紀錄_agy = 做假CLI("agy")
    monkeypatch.setattr(
        "nova.載體.模型.轉接.找執行檔",
        lambda 家, **_: 假_codex if 家 == "codex" else 假_agy,
    )
    return 紀錄_codex, 紀錄_agy


class Test視窗預算與單次上限互相對照:
    """重現「視窗已用 129759299、命令只給 3000000」的現場。

    - `--預算token 3000000`：全專案時間視窗累計，已用 1.3 億 > 300 萬，在模型呼叫前以護欄碼 4 擋下。
    - `--單次上限token 3000000`：僅限制這次單次呼叫，不看時間視窗歷史累積，正常打出請求。
    """

    def test_視窗已花1億3但單次上限內照常發送(
        self, tmp_path: Path, 接上假codex: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=129_759_299)
        實錄 = _做假codex實錄(tmp_path, token=500)
        monkeypatch.setenv("NOVA_FAKE_CODEX_TRANSCRIPT", str(實錄))

        碼 = 主程式(
            [
                "問",
                "--用",
                "codex",
                "--帳本目錄",
                str(帳本目錄),
                "--單次上限token",
                "3000000",
                "在嗎",
            ]
        )

        assert 碼 == 放行
        assert 接上假codex.exists(), "單次上限未超標且不看視窗累積，請求應正常發出"

    def test_視窗預算超限在模型呼叫前以護欄碼4擋住(
        self,
        tmp_path: Path,
        接上假codex: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=129_759_299)

        碼 = 主程式(
            [
                "問",
                "--用",
                "codex",
                "--帳本目錄",
                str(帳本目錄),
                "--預算token",
                "3000000",
                "在嗎",
            ]
        )

        assert 碼 == 護欄碼
        assert not 接上假codex.exists(), "視窗累積超支應在模型呼叫前擋下"
        錯誤 = capsys.readouterr().err
        assert "129759299" in 錯誤
        assert "3000000" in 錯誤
        assert "視窗" in 錯誤 or "這段時間" in 錯誤, f"錯誤訊息應清楚表達視窗累積超限：{錯誤}"


class Test單次上限超標行為:
    def test_單次呼叫超過上限收在護欄碼4且記清實際與上限(
        self,
        tmp_path: Path,
        接上假codex: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """假回應單次超過上限時回 4，且訊息說得出單次呼叫超限與實際/上限數值。"""
        實錄 = _做假codex實錄(tmp_path, token=3_500_000)
        monkeypatch.setenv("NOVA_FAKE_CODEX_TRANSCRIPT", str(實錄))

        碼 = 主程式(
            [
                "問",
                "--用",
                "codex",
                "--單次上限token",
                "3000000",
                "在嗎",
            ]
        )

        assert 碼 == 護欄碼
        assert 接上假codex.exists(), "單次上限是在呼叫後判定用量超標"
        錯誤 = capsys.readouterr().err
        assert "3500000" in 錯誤 or "3500050" in 錯誤
        assert "3000000" in 錯誤
        assert "單次" in 錯誤, f"錯誤訊息應標明單次呼叫超限：{錯誤}"

    def test_第一顆超標就收手不接力問第二家(
        self,
        tmp_path: Path,
        接上假codex與agy: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """第一顆**失敗且單次超標**時，接力鏈當場收手，不准再燒第二家。

        這裡第一顆非「失敗」不可：接力只在失敗時才往下走，讓第一顆回成功的話
        接力分支根本不會執行，測試會綠得很安穩卻什麼都沒守到。

        單次超標是護欄生效（4），不是供應商暫時失敗——「換一家再問一次」
        只會把同一份超大的提示再燒一次，而那正是上限想擋的事。
        """
        紀錄_codex, 紀錄_agy = 接上假codex與agy
        monkeypatch.setenv(
            "NOVA_FAKE_AGY_TRANSCRIPT", str(_做假agy可接力失敗實錄(tmp_path, token=3_500_000))
        )

        碼 = 主程式(
            [
                "問",
                "--用",
                "agy,codex",
                "--單次上限token",
                "3000000",
                "在嗎",
            ]
        )

        assert 碼 == 護欄碼, f"第一顆單次超標應收在護欄碼 4，實際為 {碼}"
        assert 紀錄_agy.exists(), "第一家 agy 有被呼叫"
        assert not 紀錄_codex.exists(), "第一顆已經超過單次上限，不准接力再燒第二家 codex"

    def test_兩顆各自沒超標不因總和被誤判成單次超標(
        self,
        tmp_path: Path,
        接上假codex與agy: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """接力鏈回的是整條鏈的總和，但「單次上限」量的是**一次呼叫**。

        拿總和去比單次上限，兩顆各自 200 萬（都在 300 萬以內）會被報成
        「單次呼叫超過 300 萬」——那句話是假的，而且它會讓派工的人去調高
        一個根本沒被撞到的上限。
        """
        紀錄_codex, 紀錄_agy = 接上假codex與agy
        monkeypatch.setenv(
            "NOVA_FAKE_AGY_TRANSCRIPT", str(_做假agy可接力失敗實錄(tmp_path, token=2_000_000))
        )
        monkeypatch.setenv(
            "NOVA_FAKE_CODEX_TRANSCRIPT", str(_做假codex實錄(tmp_path, token=2_000_000))
        )

        碼 = 主程式(
            [
                "問",
                "--用",
                "agy,codex",
                "--單次上限token",
                "3000000",
                "在嗎",
            ]
        )

        assert 紀錄_agy.exists() and 紀錄_codex.exists(), "第一顆是可接力的失敗，第二顆該被問到"
        錯誤 = capsys.readouterr().err
        assert 碼 == 放行, f"兩顆各自都沒超過單次上限，不該被護欄擋：{碼}／{錯誤}"
        assert "單次" not in 錯誤 or "超過" not in 錯誤, (
            f"沒有任何一次呼叫超標，不該報單次超限：{錯誤}"
        )


class Test缺用量無法判定單次超限:
    @pytest.mark.usefixtures("接上假codex")
    def test_缺用量無法判定時回退出碼未知3(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """缺用量而無法判定是否超標時回 3（未知），不把未知當 0。"""
        實錄 = _做假codex無用量實錄(tmp_path)
        monkeypatch.setenv("NOVA_FAKE_CODEX_TRANSCRIPT", str(實錄))

        碼 = 主程式(
            [
                "問",
                "--用",
                "codex",
                "--單次上限token",
                "3000000",
                "在嗎",
            ]
        )

        assert 碼 == 未知, f"缺用量無法判定單次上限時應回未知碼 3，實際為 {碼}"


class Test護欄擋下時JSON證據講得出是哪個Scope:
    """`--json` 是給腳本讀的那一面。人看 stderr，腳本看 JSON。

    退出碼 4 只說「護欄生效」，說不出是**視窗累計**還是**單次呼叫**擋的——
    而外圈要決定「換小一點的題目重派」還是「這個視窗今天不要再打了」，
    靠的正是這個差別。stderr 那句話是給人讀的，腳本去 grep 中文字串就是把
    訊息措辭變成介面：改一個字外圈就壞，而且壞得沒有聲音。

    所以單次超限時 JSON 要帶一筆 `上限判定`，寫明範圍、實際花了多少、上限多少。
    """

    def test_單次超限的json證據標明範圍是單次呼叫並記下實際與上限(
        self,
        tmp_path: Path,
        接上假codex: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        實錄 = _做假codex實錄(tmp_path, token=3_500_000)  # 輸入 3,500,000 + 輸出 50
        monkeypatch.setenv("NOVA_FAKE_CODEX_TRANSCRIPT", str(實錄))

        碼 = 主程式(
            [
                "問",
                "--用",
                "codex",
                "--json",
                "--單次上限token",
                "3000000",
                "在嗎",
            ]
        )

        assert 碼 == 護欄碼
        assert 接上假codex.exists(), "單次上限是在呼叫後判定用量超標"
        證據 = json.loads(capsys.readouterr().out)
        assert "上限判定" in 證據, f"護欄擋下時 JSON 要說得出是哪個 scope 擋的：{sorted(證據)}"
        判定 = 證據["上限判定"]
        assert 判定["範圍"] == "單次呼叫", f"這次是單次上限擋的，不是視窗累計：{判定}"
        assert 判定["實際token"] == 3_500_050, f"實際花費要記真數字，不能省略：{判定}"
        assert 判定["上限token"] == 3_000_000, f"上限要記命令列給的那個數：{判定}"

    def test_視窗超限的json證據標明範圍是視窗累計(
        self,
        tmp_path: Path,
        接上假codex: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """兩個 scope 都要走同一個結構化欄位，腳本才分得出來是哪一個擋的。

        只有單次超限吐 JSON、視窗超限只留一行中文 stderr 的話，
        「這個結構化證據說得出 scope」是半句話：外圈遇到視窗超限時
        還是只拿得到退出碼 4，只能回去 grep 中文措辭。
        """
        帳本目錄 = tmp_path / "帳"
        _寫一次用掉(帳本目錄, token=129_759_299)

        碼 = 主程式(
            [
                "問",
                "--用",
                "codex",
                "--json",
                "--帳本目錄",
                str(帳本目錄),
                "--預算token",
                "3000000",
                "在嗎",
            ]
        )

        assert 碼 == 護欄碼
        assert not 接上假codex.exists(), "視窗累積超支應在模型呼叫前擋下"
        輸出 = capsys.readouterr().out.strip()
        assert 輸出, "給了 --json 卻連一個字都沒吐，腳本只剩退出碼 4 可看"
        判定 = json.loads(輸出).get("上限判定")
        assert 判定 is not None, f"視窗超限也要交代是哪個 scope 擋的：{輸出}"
        assert 判定["範圍"] == "視窗累計", f"這次是視窗累計擋的，不是單次呼叫：{判定}"
        assert 判定["實際token"] == 129_759_299, f"視窗內已用要記真數字：{判定}"
        assert 判定["上限token"] == 3_000_000, f"上限要記 --預算token 給的那個數：{判定}"


#: 三個 scope 各自的「說得出口」與「不准講」。
#: 只驗旗標名字會自我滿足——`--單次上限token` 這個名字本身就含「單次」，
#: metavar 寫個「視窗token」也一樣——所以這裡只看 **說明文字本身**。
_視窗說法 = ("視窗", "窗口", "這段時間", "全專案")
_本輪說法 = ("本輪", "這一輪", "這輪")
_單次說法 = ("單次", "這一次", "每次")


def _旗標說明(剖析: argparse.ArgumentParser, 旗標: str) -> str:
    """拿某個旗標的 help 描述本身（不含旗標名、不含 metavar）。

    `format_help()` 那份把旗標名與 metavar 一起排進同一行，
    對「說明有沒有講清楚 scope」這件事會被名字混過去。
    """
    for 動作 in 剖析._actions:  # noqa: SLF001
        if 旗標 in 動作.option_strings:
            return 動作.help or ""
    raise KeyError(旗標)


class Test三個預算Scope的Help說明分明:
    """help 要讓人分得出視窗累計／本輪累計／單次呼叫是三件事。

    使用者踩到的就是 scope 名稱：`--預算token` 被當成「這一次最多花 300 萬」。
    所以每個旗標的說明都要**自己**講得出自己的 scope，
    而且不准混進別的 scope 的說法把人帶偏。
    """

    def test_問的視窗預算說明講視窗累計且不講單次(self) -> None:
        說明 = _旗標說明(_找出子剖析器(建剖析器(處理們), "問"), "--預算token")
        assert any(說法 in 說明 for 說法 in _視窗說法), (
            f"--預算token 的說明要自己講得出視窗累計：{說明!r}"
        )
        assert not any(說法 in 說明 for 說法 in _單次說法), (
            f"--預算token 是視窗累計，說明不准帶單次語意把人帶偏：{說明!r}"
        )

    def test_問的單次上限說明講單次呼叫且不講視窗(self) -> None:
        說明 = _旗標說明(_找出子剖析器(建剖析器(處理們), "問"), "--單次上限token")
        assert any(說法 in 說明 for 說法 in _單次說法), (
            f"--單次上限token 的說明要講單次呼叫：{說明!r}"
        )
        assert not any(說法 in 說明 for 說法 in _視窗說法), (
            f"--單次上限token 只管這一次，說明不准混進視窗說法：{說明!r}"
        )

    def test_工作流三個旗標的說明各自認領一個scope(self) -> None:
        """`--預算token`（視窗）、`--最多token`（本輪累計）、`--單次最多token`（單次）。

        三個並排在同一份 help 裡，只寫「累計」是分不出誰是誰的：
        視窗那個也叫累計。本輪那個要自己說出是**這一輪**的累計。
        """
        流剖析 = _找出子剖析器(建剖析器(處理們), "工作流")
        視窗 = _旗標說明(流剖析, "--預算token")
        本輪 = _旗標說明(流剖析, "--最多token")
        單次 = _旗標說明(流剖析, "--單次最多token")

        assert any(說法 in 視窗 for 說法 in _視窗說法), f"--預算token 要講視窗累計：{視窗!r}"
        assert any(說法 in 本輪 for 說法 in _本輪說法), (
            f"--最多token 是這一輪工作流的累計，說明要說得出「本輪」，"
            f"否則跟視窗累計的說明並排時分不出來：{本輪!r}"
        )
        assert any(說法 in 單次 for 說法 in _單次說法), f"--單次最多token 要講單次呼叫：{單次!r}"

        assert not any(說法 in 本輪 for 說法 in _視窗說法 + _單次說法), (
            f"--最多token 是本輪累計，說明不准混進視窗或單次的說法：{本輪!r}"
        )
        assert not any(說法 in 單次 for 說法 in _視窗說法), (
            f"--單次最多token 不看時間視窗，說明不准混進視窗說法：{單次!r}"
        )
        assert not any(說法 in 視窗 for 說法 in _單次說法 + _本輪說法), (
            f"--預算token 是全專案視窗累計，說明不准被偷換成單次或本輪：{視窗!r}"
        )


class Test單次上限參數非法用法錯誤:
    def test_單次上限為零或負數時回阻擋2(self, 接上假codex: Path) -> None:
        """單次上限給 0 或負數是用法錯誤（2），不是護欄生效（4）。"""
        for 數值 in ("0", "-10"):
            碼 = 主程式(
                [
                    "問",
                    "--用",
                    "codex",
                    "--單次上限token",
                    數值,
                    "在嗎",
                ]
            )
            assert 碼 == 阻擋, f"--單次上限token {數值} 應回阻擋碼 2，實際為 {碼}"
            assert not 接上假codex.exists()

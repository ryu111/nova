"""逾時被殺的時候，把子程序已經吐出來的東西撿回來。

**這是「接續思考」的前提。** 逾時之後想 `--續接` 接著做，前提是知道 sid；
而 sid 一直都在——它在部分輸出的第一行，是 nova 把它丟掉了。

實測（2026-08-29，強制 15 秒逾時）：

| 家 | 輸出格式 | 逾時當下的部分 stdout |
|---|---|---|
| codex | `exec --json`（JSONL） | **20,865 字元**，第一行帶 `thread_id` |
| agy | `--output-format json`（單一物件） | **0 字元**——整包最後才寫 |
| agy | `--output-format stream-json`（NDJSON） | **1,421 字元**，第一行帶 `conversation_id` |

所以 codex（也就是 sol，逾時最痛的那個）現在就撿得回。agy 要換輸出格式，另案。

## 為什麼不用 `--continue`

agy 有 `--continue`「接最近一段對話」，不需要 sid。**但那不是保證**：
中間插進任何一次別的呼叫，「最近一段」就換人了。使用者的原話：
「Sid 是保證同一個，沒加差別是可能會不同一個」。
"""

from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.載體.模型.解析 import 撿對話識別碼
from nova.載體.模型.轉接 import 逾時的回應

codex部分輸出 = (
    '{"type":"thread.started","thread_id":"01a04c10-ef63-78e1-baf0-9785f72587fb"}\n'
    '{"type":"turn.started"}\n'
    '{"type":"item.completed","item":{"id":"i2","type":"agent_message","text":"我先釐清需求"}}\n'
)


def 假解析(標準輸出: str, 結束碼: int, 標準錯誤: str = "") -> 回應:
    del 標準輸出, 結束碼, 標準錯誤
    return 回應(
        文字="半成品",
        終局=終局.成功,
        失敗代碼=失敗代碼.無,
        原始結束碼=0,
        對話識別碼="從解析器來的",
        用量=用量(輸入token=999, 輸出token=999),
    )


def _沒文字的解析(標準輸出: str, 結束碼: int, 標準錯誤: str = "") -> 回應:
    """截斷的輸出走的是解析器的失敗路徑：沒有文字、也沒有 sid。

    這才是逾時當下的真實形狀，`假解析` 那顆是用來驗「有半成品時怎麼辦」的。
    """
    del 標準輸出, 結束碼
    return 回應(
        文字=標準錯誤,
        終局=終局.確定失敗,
        失敗代碼=失敗代碼.未知,
        原始結束碼=-1,
        對話識別碼=None,
        用量=用量(輸入token=0, 輸出token=0),
    )


class Test撿對話識別碼:
    def test_codex的thread_id(self) -> None:
        assert 撿對話識別碼(codex部分輸出) == "01a04c10-ef63-78e1-baf0-9785f72587fb"

    def test_agy的conversation_id(self) -> None:
        行 = '{"event":"init","conversation_id":"76bca02a-6187-46dc-818c-9e35f9668764"}\n'
        assert 撿對話識別碼(行) == "76bca02a-6187-46dc-818c-9e35f9668764"

    def test_半行不要爆(self) -> None:
        """逾時砍在一半，最後一行一定是壞的。整份讀不動比少一行糟得多。"""
        assert 撿對話識別碼(codex部分輸出 + '{"type":"item.comp') is not None

    def test_沒有就回None(self) -> None:
        assert 撿對話識別碼('{"type":"turn.started"}\n') is None

    def test_空的回None(self) -> None:
        assert 撿對話識別碼("") is None

    def test_取第一個不是最後一個(self) -> None:
        """一次執行只有一段對話。出現第二個 id 多半是雜訊，開場那個才是真的。"""
        兩個 = codex部分輸出 + '{"type":"thread.started","thread_id":"後來的"}\n'
        assert 撿對話識別碼(兩個) == "01a04c10-ef63-78e1-baf0-9785f72587fb"


class Test逾時的回應:
    def test_沒有部分輸出就跟以前一樣(self) -> None:
        答 = 逾時的回應(假解析, "")
        assert 答.文字 == ""
        assert 答.對話識別碼 is None

    def test_有部分輸出就撿回sid(self) -> None:
        """撿回 sid 才續接得了。這是整條路的關鍵一格。"""
        assert 逾時的回應(假解析, codex部分輸出).對話識別碼 == "從解析器來的"

    def test_逾時也要帶得回診斷(self) -> None:
        """`部分標準錯誤` 抓了卻沒人讀，等於沒抓。

        逾時是**最需要診斷的那一刻**：不知道它做到哪，
        而 CLI 死前那幾行 stderr 往往就寫著卡在哪
        （實測過一次：codex 印「Reading additional input from stdin...」
        然後 0 token 逾時，跟「想太久」長得一模一樣）。
        """
        答 = 逾時的回應(_沒文字的解析, codex部分輸出, "卡在讀 stdin")
        assert "卡在讀 stdin" in 答.文字

    def test_逾時診斷要在第一行(self) -> None:
        """CLI 只印證據第一行，所以診斷必須站在半成品前面。"""
        答 = 逾時的回應(
            假解析,
            codex部分輸出,
            耗時秒=12.34,
            上限秒=3.5,
        )

        assert 答.文字.splitlines()[0] == (
            "結果未知：這次呼叫跑了 12.3 秒，上限 3.5 秒；不准重跑，去看工作區。"
        )

    def test_解析器給不出sid就自己撿(self) -> None:
        """截斷的輸出多半走不到解析器的成功路徑，`_壞掉` 那條不帶 id。"""
        答 = 逾時的回應(_沒文字的解析, codex部分輸出)
        assert 答.對話識別碼 == "01a04c10-ef63-78e1-baf0-9785f72587fb"

    def test_終局一定還是結果未知(self) -> None:
        """**最重要的一條。**

        解析得動不等於跑完了——假解析回的是「成功」，但它只跑了一半就被殺。
        讓解析結果決定終局就是拿半成品當成品，而結果未知在可編輯下不准自動重跑，
        「成功」卻會被當成做完了。
        """
        答 = 逾時的回應(假解析, codex部分輸出)
        assert 答.終局 is 終局.結果未知
        assert 答.失敗代碼 is 失敗代碼.逾時
        assert 答.原始結束碼 == -1

    def test_用量不准從半成品抄(self) -> None:
        """半途的 usage 不是這次的花費。抄過來會讓帳本記到一個假的數字。"""
        assert 逾時的回應(假解析, codex部分輸出).用量.總token == 0

    def test_進度要留在文字裡(self) -> None:
        assert "半成品" in 逾時的回應(假解析, codex部分輸出).文字

    def test_解析不出文字就給原始輸出(self) -> None:
        assert "thread.started" in 逾時的回應(_沒文字的解析, codex部分輸出).文字

    def test_太長要截斷(self) -> None:
        """部分輸出實測 20,865 字元，整包塞進回應會把終端機洗掉。

        **要用「解析不出文字」的那顆解析器**：`假解析` 會回一段短文字，
        於是原始輸出根本走不到截斷那一行——第一版就是這樣寫的，
        負控（把截斷拿掉）完全沒紅。
        """
        答 = 逾時的回應(_沒文字的解析, "x" * 100_000)
        assert len(答.文字) < 20_000

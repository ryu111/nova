"""無進展護欄的行為測試。"""

from hashlib import sha256
from pathlib import Path

from nova.契約.工作流 import (
    任務,
    停止條件,
    步驟結果,
    種類,
    結束代碼,
    階段代碼,
    階段定義,
)
from nova.契約.模型回應 import 終局
from nova.迴圈.工作流 import 跑工作流


def test_同一批失敗測試且工作區未變要提早停(tmp_path: Path) -> None:
    """同一批失敗 nodeid 在工作區未變時，不論附帶輸出怎麼變，連紅三輪就以護欄 4 停下。"""
    目標檔 = tmp_path / "實作.py"
    目標檔.write_text("固定內容\n", encoding="utf-8")
    工作區雜湊 = sha256(目標檔.read_bytes()).hexdigest()
    工作 = 任務(描述="修好一個卡住的功能", 工作目錄=tmp_path)
    nodeid們 = (
        "tests/單元/test_功能.py::test_空輸入",
        "tests/單元/test_功能.py::test_缺少必要欄位",
    )
    判準紅次數 = 0

    def 執行一步(
        定義: 階段定義,
        _任務: 任務,
        _軌跡: tuple[步驟結果, ...],
    ) -> 步驟結果:
        nonlocal 判準紅次數
        del _任務, _軌跡
        if 定義.代碼 is 階段代碼.驗證紅:
            return 步驟結果(
                階段=定義.代碼,
                終局=終局.成功,
                判準綠=False,
                證據="初始測試確實是紅的",
            )
        if 定義.代碼 is 階段代碼.驗證綠:
            判準紅次數 += 1
            順序 = nodeid們 if 判準紅次數 % 2 else tuple(reversed(nodeid們))
            證據 = f"FAILED {順序[0]}\nFAILED {順序[1]}\n本次執行耗時 {判準紅次數 * 7} ms"
            return 步驟結果(
                階段=定義.代碼,
                終局=終局.成功,
                判準綠=False,
                證據=證據,
            )
        return 步驟結果(
            階段=定義.代碼,
            終局=終局.成功,
            判準綠=None if 定義.種類 is 種類.模型 else 定義.期望綠,
            證據="本輪沒有改動工作區",
        )

    結果 = 跑工作流(
        工作,
        執行一步=執行一步,
        停止=停止條件(最多步數=35, 最多token=10**9),
    )

    assert 結果.結束.代碼 is 結束代碼.護欄
    assert "無進展" in 結果.結束.原因
    assert all(nodeid in 結果.結束.原因 for nodeid in nodeid們)
    assert len([步 for 步 in 結果.軌跡 if 步.階段 is 階段代碼.驗證綠]) == 3
    assert len(結果.軌跡) < 12
    assert sha256(目標檔.read_bytes()).hexdigest() == 工作區雜湊

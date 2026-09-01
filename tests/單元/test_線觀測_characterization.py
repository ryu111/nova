"""`nova 線` 的 characterization 測試：凍結觀測來源、工作樹查詢與呈現的所有既有判斷。

此測試檔嚴格凍結現有行為：
1. `_是nova命令` 的所有命令列猜測結果（正向與反向，包括 python、uv、claude 引數等）。
2. `--工作目錄` 與 `.venv` 路徑推導。
3. `ps` 行解析、三值狀態判斷（在跑嗎：是／否／查不到）。
4. 各觀測契約型別（`線現況`、`程序資料`、`程序清查`、`基底比較`）。
5. 呈現層的人話輸出格式。
"""

from pathlib import Path

import pytest

from nova.契約.成果 import 成果
from nova.契約.線觀測 import (
    線現況,
)
from nova.契約.遮罩 import 已經遮過了
from nova.載體.程序觀測 import (
    命令指定的工作目錄,
    是nova命令,
    裝在哪棵樹,
    解析一行ps,
)
from nova.載體.線呈現 import 排版


class Test是nova命令特徵凍結:
    """凍結既有 `_是nova命令` 的猜身分判斷，不准在此票擅自改變既有真假。"""

    @pytest.mark.parametrize(
        ("命令列", "預期結果"),
        [
            (["nova"], True),
            (["nova", "線"], True),
            (["nova", "工作流", "任務"], True),
            (["/usr/local/bin/nova", "線"], True),
            (["/Users/sbu/.local/bin/nova-inbox", "收件"], True),
            (["nova-wt-測試", "跑"], True),
            (["nova.py"], True),
            (["python", "-m", "nova", "工作流"], True),
            (["python3", "-m", "nova", "線"], True),
            (["/Users/sbu/.venv/bin/python3", "-m", "nova.載體.命令列"], True),
            (["/Users/sbu/.venv/bin/python3", "/Users/sbu/nova/.venv/bin/nova", "工作流"], True),
            (["python", "-u", "-m", "nova", "線"], True),
            (["uv", "run", "nova", "工作流"], True),
            (["uv", "run", "/path/to/nova", "線"], True),
            (["uv", "run", "--frozen", "nova", "工作流"], True),
            # 反向：非 nova 命令或參數中含有 nova 字眼但不構成 nova 本體
            ([], False),
            (["python", "other_script.py"], False),
            (["python", "-m", "pytest"], False),
            (["uv", "run", "pytest", "tests/單元"], False),
            (["uv", "run"], False),
            (["claude", "--add-dir", "/Users/sbu/nova"], False),
            (["git", "commit", "-m", "fix nova bug"], False),
            (["sh", "-c", "echo nova"], False),
            (["pytest", "tests/單元/test_線.py"], False),
        ],
    )
    def test_命令列識別判斷(self, 命令列: list[str], 預期結果: bool) -> None:
        assert 是nova命令(命令列) is 預期結果


class Test工作目錄與路徑推導特徵凍結:
    def test_從命令列取得工作目錄(self) -> None:
        assert (
            命令指定的工作目錄(["nova", "--工作目錄", "/path/to/tree"])
            == Path("/path/to/tree").resolve()
        )
        assert (
            命令指定的工作目錄(["nova", "--工作目錄=/path/to/tree"])
            == Path("/path/to/tree").resolve()
        )
        assert 命令指定的工作目錄(["nova", "線"]) is None
        assert 命令指定的工作目錄([]) is None

    def test_從venv推導所在樹(self) -> None:
        assert (
            裝在哪棵樹(["/Users/sbu/nova-wt-1/.venv/bin/nova-inbox"])
            == Path("/Users/sbu/nova-wt-1").resolve()
        )
        assert 裝在哪棵樹(["/usr/local/bin/nova"]) is None
        assert 裝在哪棵樹([]) is None


class Test程序解析特徵凍結:
    def test_解析有效ps行(self) -> None:
        行 = "12345 01:23:45 Mon Aug 31 00:00:00 2026 /Users/sbu/nova-wt-1/.venv/bin/nova-inbox"
        程序, 未定位 = 解析一行ps(行, 本身pid=99999)
        assert 未定位 is False
        assert 程序 is not None
        assert 程序.工作目錄 == Path("/Users/sbu/nova-wt-1").resolve()
        assert 程序.跑多久 == "01:23:45"
        assert 程序.啟動時間 == "Mon Aug 31 00:00:00 2026"

    def test_自身pid會被略過(self) -> None:
        行 = "12345 01:23:45 Mon Aug 31 00:00:00 2026 nova 線"
        程序, 未定位 = 解析一行ps(行, 本身pid=12345)
        assert 程序 is None
        assert 未定位 is False

    def test_無效ps欄位數回傳None(self) -> None:
        行 = "12345 01:23:45 nova"
        程序, 未定位 = 解析一行ps(行, 本身pid=99999)
        assert 程序 is None
        assert 未定位 is False

    def test_無法定位工作目錄標記為未定位(self) -> None:
        行 = "12345 01:23:45 Mon Aug 31 00:00:00 2026 /usr/bin/nova"
        程序, 未定位 = 解析一行ps(行, 本身pid=99999)
        assert 程序 is None
        assert 未定位 is True


class Test線觀測契約特徵凍結:
    def test_線現況衍生屬性(self) -> None:
        現況 = 線現況(
            名字="測試線",
            在跑嗎=True,
            跑多久="01:00",
            啟動時間="now",
            目前階段="實作",
            上一次=None,
            護欄原因=None,
            未提交檔案數=3,
            基底落後數=2,
        )
        assert 現況.落後基底數 == 2
        assert 現況.工作區乾淨嗎 is False

    def test_線現況未提交檔案數為None時乾淨嗎也為None(self) -> None:
        現況 = 線現況(
            名字="測試線",
            在跑嗎=False,
            跑多久=None,
            啟動時間=None,
            目前階段=None,
            上一次=None,
            護欄原因=None,
            未提交檔案數=None,
            基底落後數=None,
        )
        assert 現況.工作區乾淨嗎 is None
        assert 現況.落後基底數 is None


class Test線呈現特徵凍結:
    def test_無工作樹排版輸出(self) -> None:
        assert 排版(()) == "線：查不到（沒有 worktree）\n"

    def test_完整線排版輸出(self) -> None:
        成果紀錄 = 成果(
            執行識別碼="20260831T000000Z-測試",
            任務=已經遮過了("測試任務", 因為="單元測試"),
            收場="測試",
            退出碼=0,
            起="",
            迄="",
            走了幾階=0,
            總token=0,
        )
        現況 = 線現況(
            名字="主工作區／main",
            在跑嗎=True,
            跑多久="00:15",
            啟動時間="一  9月/ 1 12:00:00 2026",
            目前階段="實作",
            上一次=成果紀錄,
            護欄原因=None,
            未提交檔案數=0,
            基底落後數=0,
        )
        輸出 = 排版((現況,))
        assert "線：主工作區／main" in 輸出
        assert "  在跑嗎：是" in 輸出
        assert "  跑多久了：00:15（啟動於 一  9月/ 1 12:00:00 2026）" in 輸出
        assert "  現在在哪一階：實作" in 輸出
        assert "  上一次怎麼收的：退出碼 0：成功" in 輸出
        assert "  工作區乾淨嗎：是（0 個未提交檔案）" in 輸出
        assert "  base 落後幾個 commit：0" in 輸出

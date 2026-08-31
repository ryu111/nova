"""給本地模型的工具箱：規格、執行、以及**路徑圈禁**。

本地腦原本只會回文字——`_做不到的地方` 直接擋掉可編輯權限，訊息是
「本地模型沒有工具」。2026-08-31 驗到那句話是錯的：端點吃 OpenAI 相容的
`tools` 參數，27B 會回 `tool_calls`，而且吃得下 `role: "tool"` 的結果再收尾。
缺的一直是 nova 這一側。

**這個檔只測純函式**（規格長什麼樣、路徑准不准、結果怎麼截斷）。
真的走 HTTP 的迴圈在 `tests/整合/`——單元層不准開 socket。
"""

from pathlib import Path

import pytest

from nova.契約.角色 import 權限
from nova.載體.模型.本地工具 import 工具箱, 工具錯誤


@pytest.fixture
def 工作區(tmp_path: Path) -> Path:
    (tmp_path / "有的.txt").write_text("內容一二三", encoding="utf-8")
    (tmp_path / "子").mkdir()
    (tmp_path / "子" / "深的.txt").write_text("深處", encoding="utf-8")
    return tmp_path


class Test工具集由權限推導:
    """**權限決定給什麼工具，不是給了工具再檢查權限。**

    給了 write 再在執行時擋，等於讓模型每一輪都撞一次牆、每一次都燒 token。
    唯讀就不要把那把刀放在桌上。
    """

    def test_唯讀拿不到寫入工具(self, 工作區: Path) -> None:
        名字們 = {規["function"]["name"] for 規 in 工具箱(工作區, 權限.唯讀).規格()}
        assert "write_file" not in 名字們

    def test_唯讀拿得到讀取與搜尋(self, 工作區: Path) -> None:
        名字們 = {規["function"]["name"] for 規 in 工具箱(工作區, 權限.唯讀).規格()}
        assert {"read_file", "grep"} <= 名字們

    def test_可編輯才拿得到寫入(self, 工作區: Path) -> None:
        名字們 = {規["function"]["name"] for 規 in 工具箱(工作區, 權限.可編輯).規格()}
        assert "write_file" in 名字們

    def test_一律不給執行指令(self, 工作區: Path) -> None:
        """**exec 不在工具集裡。**

        TDD 的驗證紅／驗證綠是機械判準階段（帳本裡是 `verify-red`，0 token），
        模型從頭到尾不需要自己跑 pytest。不給 exec 就沒有沙箱問題要解。
        """
        for 權 in (權限.唯讀, 權限.可編輯):
            名字們 = {規["function"]["name"] for 規 in 工具箱(工作區, 權).規格()}
            assert not (名字們 & {"exec", "run", "bash", "shell", "run_command"}), 權


class Test路徑一律圈在工作目錄裡:
    """**模型指揮的路徑是不可信輸入。** repo 是 public，洩漏一次收不回來。

    圈禁要在**解析之後**判斷：`工作目錄/../../etc/passwd` 字串上看起來在裡面，
    解析完才看得出它跑出去了。只比對前綴會被 `/tmp/工作區-偷` 這種同前綴
    的兄弟目錄騙過去。
    """

    def test_讀得到工作目錄裡的檔(self, 工作區: Path) -> None:
        assert "內容一二三" in 工具箱(工作區, 權限.唯讀).執行("read_file", {"path": "有的.txt"})

    def test_讀得到子目錄(self, 工作區: Path) -> None:
        結果 = 工具箱(工作區, 權限.唯讀).執行("read_file", {"path": "子/深的.txt"})
        assert "深處" in 結果

    def test_絕對路徑被擋(self, 工作區: Path) -> None:
        with pytest.raises(工具錯誤, match="工作目錄"):
            工具箱(工作區, 權限.唯讀).執行("read_file", {"path": "/etc/passwd"})

    def test_往上跳被擋(self, 工作區: Path) -> None:
        with pytest.raises(工具錯誤, match="工作目錄"):
            工具箱(工作區, 權限.唯讀).執行("read_file", {"path": "../../etc/passwd"})

    def test_同前綴的兄弟目錄被擋(self, tmp_path: Path) -> None:
        """`/tmp/區` 與 `/tmp/區-偷` 的字串前綴一樣，但那是兩個目錄。"""
        區 = tmp_path / "區"
        區.mkdir()
        (tmp_path / "區-偷").mkdir()
        (tmp_path / "區-偷" / "秘密.txt").write_text("不該被讀到", encoding="utf-8")
        with pytest.raises(工具錯誤, match="工作目錄"):
            工具箱(區, 權限.唯讀).執行("read_file", {"path": "../區-偷/秘密.txt"})

    def test_寫入也要圈禁(self, 工作區: Path) -> None:
        with pytest.raises(工具錯誤, match="工作目錄"):
            工具箱(工作區, 權限.可編輯).執行(
                "write_file", {"path": "/etc/nova-逃.txt", "content": "x"}
            )

    def test_唯讀時寫入被擋(self, 工作區: Path) -> None:
        """就算模型硬叫一個沒給它的工具，也不准真的寫下去。"""
        with pytest.raises(工具錯誤, match="唯讀"):
            工具箱(工作區, 權限.唯讀).執行("write_file", {"path": "新.txt", "content": "x"})


class Test工具結果不准撐爆context:
    """本地模型的 context 比雲端小。讀兩個大檔就爆，而爆掉的樣子是

    「模型突然開始胡言亂語」——**看起來像模型笨，不是像工具壞了**。
    """

    def test_太大的檔案會被截斷並講明(self, 工作區: Path) -> None:
        (工作區 / "大.txt").write_text("字" * 50_000, encoding="utf-8")
        結果 = 工具箱(工作區, 權限.唯讀).執行("read_file", {"path": "大.txt"})
        assert len(結果) < 50_000
        assert "截斷" in 結果, "截斷了卻不講，模型會以為自己讀完了"


class Test寫入要有資源上限:
    """**本地跑不燒 API 額度，所以風險不在 usage，在準確度與資源控管。**

    模型寫錯一個 path 就覆蓋掉一個真的檔案；寫一個超大的 content 就吃掉磁碟。
    這兩件事都不會有帳單來提醒你。
    """

    def test_單次寫入的內容有大小上限(self, 工作區: Path) -> None:
        with pytest.raises(工具錯誤, match="太大"):
            工具箱(工作區, 權限.可編輯).執行(
                "write_file", {"path": "巨大.txt", "content": "字" * 500_000}
            )

    def test_一輪最多寫幾個檔案(self, 工作區: Path) -> None:
        """**一個工具箱只服務一次呼叫**，所以次數上限就是「這一輪最多動幾個檔」。

        沒有這條的話，模型可以在回合上限內把整個工作目錄覆蓋掉——
        每一次寫入本身都合法，合起來是災難。
        """
        箱 = 工具箱(工作區, 權限.可編輯)
        for 號 in range(20):
            try:
                箱.執行("write_file", {"path": f"第{號}.txt", "content": "x"})
            except 工具錯誤 as 錯:
                assert "上限" in str(錯), 錯
                assert 號 < 20, "跑完 20 個都沒擋"
                return
        pytest.fail("寫了 20 個檔案都沒有撞到上限")


class Test不准寫的路徑:
    """**「實作員不准改測試檔」原本只寫在角色提示裡——那是懇求。**

    測試是驗收機制，讓實作階段的模型改得到它，等於自己給自己發及格證。
    提示可以被忽略、漏了沒人發現；工具箱不給那把刀，模型
    「不用知道、不用記得、也違反不了」。
    """

    def test_擋下不准寫的路徑(self, 工作區: Path) -> None:
        (工作區 / "tests").mkdir()
        箱 = 工具箱(工作區, 權限.可編輯, 不准寫=("tests",))
        with pytest.raises(工具錯誤, match="不准"):
            箱.執行("write_file", {"path": "tests/test_偷改.py", "content": "assert True"})

    def test_擋的是子樹不只是那一層(self, 工作區: Path) -> None:
        (工作區 / "tests" / "單元").mkdir(parents=True)
        箱 = 工具箱(工作區, 權限.可編輯, 不准寫=("tests",))
        with pytest.raises(工具錯誤, match="不准"):
            箱.執行("write_file", {"path": "tests/單元/test_深的.py", "content": "x"})

    def test_同前綴的兄弟目錄不受影響(self, 工作區: Path) -> None:
        """`tests` 擋住，`tests-資料` 不該跟著被擋——比路徑節點，不比字元。"""
        箱 = 工具箱(工作區, 權限.可編輯, 不准寫=("tests",))
        assert "已寫入" in 箱.執行("write_file", {"path": "tests-資料/x.txt", "content": "x"})

    def test_不准寫的路徑仍然讀得到(self, 工作區: Path) -> None:
        """**讀是必要的**——實作員要看測試在斷言什麼才寫得出實作。擋的是寫不是讀。"""
        (工作區 / "tests").mkdir()
        (工作區 / "tests" / "test_甲.py").write_text("assert 甲() == 1", encoding="utf-8")
        箱 = 工具箱(工作區, 權限.可編輯, 不准寫=("tests",))
        assert "甲()" in 箱.執行("read_file", {"path": "tests/test_甲.py"})

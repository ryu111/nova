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

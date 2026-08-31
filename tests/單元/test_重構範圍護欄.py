"""重構只准動指名的模組——**範圍也要是實線的**。

## 為什麼

現在的 `重構護欄` 只擋一件事：重構員動測試檔。擋得住「自己給自己發及格證」，
擋不住「把手伸到別的模組去」。呼叫端說「這次只整理 `src/nova/載體`」時，
那句話一樣是寫在提示裡的懇求：模型可以順手改別的檔，而且改了之後
判準還是綠的（那些檔本來就有測試護著），沒有人會發現範圍被悄悄撐開。

判準跟「動到測試了嗎」同一條：**跑之前 vs 跑之後的快照比對**，
不是模型自己說它只動了哪些。

## 比路徑節點，不比字元前綴

`src/nova/載體` 在範圍內時，`src/nova/載體-舊/` 不該跟著被放行——
字元前綴比對會把同前綴的兄弟目錄一起放進來。這個坑
`載體/模型/本地工具.py` 的 `_圈在裡面` 踩過一次，那裡的結論是
「用路徑節點比，不比字元」，這裡是同一個結論的第二個現場。

純函式，快照由呼叫端拍，所以住單元層。
"""

from pathlib import Path

from nova.載體.重構護欄 import 拍全樹快照, 跑出範圍了嗎


class Test跑出範圍了嗎:
    def test_範圍內放行而同前綴的兄弟目錄要被抓出來(self) -> None:
        """一次釘住四件事，因為它們是同一個決定的四個面：

        - 範圍內的檔被改：**放行**（那就是這次重構要做的事）
        - 範圍外的檔被改：抓出來（呼叫端要印得出「動到哪些範圍外的檔案」）
        - `src/nova/載體-舊` 不因為 `src/nova/載體` 在範圍內而被放行
        - 回傳按路徑排序，同一次違規每次印出來要長一樣
        """
        前 = {
            "src/nova/載體/重構護欄.py": "aaa",
            "src/nova/載體-舊/甲.py": "bbb",
            "src/nova/迴圈/工作流.py": "ccc",
        }
        後 = {
            "src/nova/載體/重構護欄.py": "整理過了",
            "src/nova/載體-舊/甲.py": "被順手改了",
            "src/nova/迴圈/工作流.py": "ccc",
        }

        assert 跑出範圍了嗎(前, 後, ("src/nova/載體",)) == ("src/nova/載體-舊/甲.py",)


class Test範圍要看得到整棵樹:
    """**範圍護欄不能只拍 `tests/`。**

    `拍快照` 是 `拍測試快照` 的別名（只掃 `tests/` 底下），
    那對「動到測試了嗎」剛剛好，對「跑出範圍了嗎」卻是**永遠抓不到**：
    重構員把手伸到 `src/` 的別的模組，快照裡根本沒有那些檔，
    差集是空的，護欄放行。

    **這是最貴的那種假綠**：測試綠、閘綠、護欄在，但它守不到任何東西。
    """

    def test_拍得到src底下的檔(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "src" / "甲.py").write_text("x = 1", encoding="utf-8")
        (tmp_path / "tests" / "test_甲.py").write_text("y = 2", encoding="utf-8")
        快照 = 拍全樹快照(tmp_path)
        assert "src/甲.py" in 快照, f"拍不到 src/ 底下的檔：{sorted(快照)}"
        assert "tests/test_甲.py" in 快照

    def test_不拍垃圾目錄(self, tmp_path: Path) -> None:
        """`.git` 與 `.venv` 幾萬個檔，拍下去每次重構都要等。"""
        for 髒 in (".git", ".venv", "__pycache__", "node_modules"):
            (tmp_path / 髒).mkdir()
            (tmp_path / 髒 / "髒東西").write_text("x", encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "甲.py").write_text("x = 1", encoding="utf-8")
        assert set(拍全樹快照(tmp_path)) == {"src/甲.py"}

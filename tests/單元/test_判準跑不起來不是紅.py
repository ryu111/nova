"""**判準「跑不起來」不是「紅」。**

2026-08-30 的真實 trace，一次燒掉 997,031 token：

```
launchd 的 PATH 是 /usr/bin:/bin:/usr/sbin:/sbin，裡面沒有 uv
      ↓
判準 `uv run pytest -q` → FileNotFoundError
      ↓
被當成「紅」→ 工作流：還沒綠，回去再實作一次
      ↓
實作（叫模型，貴）→ 驗證綠 → 還是跑不起來 → 再實作 → ...
      ↓
第 3 次才被卡住偵測器停下。三次醒來共 1,720,140 token
```

nova 自己的診斷順序寫著 **環境 → 回饋 → 流程**。判準跑不起來是**環境**：
指令不存在、PATH 不對、沒有執行權限。**環境問題重跑一百次還是同一個環境**，
而每一次重跑中間都夾著一個模型階段。

所以判準是三值不是兩值：綠／紅／**跑不起來**。前兩個是回饋，第三個是環境。
"""

from pathlib import Path

from nova.契約.工作流 import 任務, 判準終局, 步驟結果, 結束代碼, 階段代碼
from nova.契約.模型回應 import 終局
from nova.載體.判準 import 建判準
from nova.迴圈.狀態機 import 下一步, 查階段


def _判準步(終: 終局, 判準綠: bool | None) -> 步驟結果:
    return 步驟結果(階段=階段代碼.驗證綠, 終局=終, 判準綠=判準綠, 證據="")


class Test判準跑不起來要當場中止:
    def test_跑不起來不准走紅邊(self) -> None:
        """**走紅邊就是「回去再實作一次」**——而實作要叫模型，那是最貴的一步。"""
        去哪 = 下一步(查階段(階段代碼.驗證綠), _判準步(終局.確定失敗, None))

        assert not isinstance(去哪, 階段代碼), f"不准回頭再跑一輪，卻走到 {去哪}"

    def test_跑不起來收在中止不是護欄(self) -> None:
        """**中止跟護欄要分開。**

        護欄是「按設計停了」，外圈不准去修；中止是「東西壞了」，
        外圈該照診斷順序去查環境。
        """
        去哪 = 下一步(查階段(階段代碼.驗證綠), _判準步(終局.確定失敗, None))

        assert not isinstance(去哪, 階段代碼)
        assert 去哪.代碼 is 結束代碼.中止, 去哪

    def test_真的紅還是要走紅邊(self) -> None:
        """**只改「跑不起來」那一格**，測試真的沒過還是要回去改。"""
        assert 下一步(查階段(階段代碼.驗證綠), _判準步(終局.成功, False)) is 階段代碼.實作


class Test建判準分得出三種收場:
    def test_指令不存在是跑不起來(self, tmp_path: Path) -> None:
        """**這正是那 997,031 token 的來源。**"""
        收場, 證據 = 建判準(["絕對不存在的指令-xyz"])(任務(描述="", 工作目錄=tmp_path))

        assert 收場 is 判準終局.跑不起來, 證據
        assert "跑不起來" in 證據

    def test_退出碼非零是紅(self, tmp_path: Path) -> None:
        收場, _ = 建判準(["sh", "-c", "exit 1"])(任務(描述="", 工作目錄=tmp_path))

        assert 收場 is 判準終局.紅

    def test_退出碼零是綠(self, tmp_path: Path) -> None:
        收場, _ = 建判準(["sh", "-c", "exit 0"])(任務(描述="", 工作目錄=tmp_path))

        assert 收場 is 判準終局.綠

    def test_逾時還是當紅(self, tmp_path: Path) -> None:
        """**刻意不改這一格。**

        逾時分不出是環境壞了還是測試真的卡住，fail-closed 當紅是既有的
        決定；卡住偵測器會在第 3 次擋下來。
        """
        收場, 證據 = 建判準(["sh", "-c", "sleep 5"], 逾時秒=0.2)(任務(描述="", 工作目錄=tmp_path))

        assert 收場 is 判準終局.紅
        assert "逾時" in 證據 or "沒跑完" in 證據


def test_判準階段不准再有紅邊的特例() -> None:
    """守著這條規則本身：`下一步` 裡不准再出現「判準確定失敗就走紅邊」。

    **這是把那 997,031 token 的成因釘死。** 沒有這一支的話，
    有人為了「讓它自己重試」把那個特例加回去，而紅只會出現在帳單上。
    """
    來源 = Path("src/nova/迴圈/狀態機.py").read_text(encoding="utf-8")
    確定失敗那段 = 來源.split("if 結果.終局 is 終局.確定失敗:")[1].split("\n\n")[0]

    assert "種類.判準" not in 確定失敗那段, 確定失敗那段


def _假pytest(tmp_path: Path, 退出碼: int) -> list[str]:
    """一支名字叫 `pytest`、只負責回一個退出碼的腳本。

    用 `sh 腳本` 跑而不是加執行位元：這一格要測的是**退出碼怎麼被翻譯**，
    不是檔案權限。指令裡有 `pytest` 這個字，判準才知道該用誰的退出碼語意。
    """
    腳本 = tmp_path / "pytest"
    腳本.write_text(f"exit {退出碼}\n", encoding="utf-8")
    return ["sh", str(腳本)]


class Test判準看得懂pytest的退出碼:
    """**pytest 用退出碼分「測試沒過」與「根本沒驗到」，判準也要分。**

    分界線原本劃在「Python 端有沒有丟例外」——那條線只抓得到指令不存在。
    `pytest` 好端端地跑起來、卻回報「一支測試都沒收集到」時，Python 端
    什麼例外都沒有，於是判準說紅、工作流回去「再實作一次」，每一輪夾一個模型階段。

    exit 5 正是「研究題誤進 TDD 工作流」的準確形狀：沒有測試檔，
    所以永遠收集不到，所以永遠燒下去。
    """

    def test_沒收集到任何測試是跑不起來(self, tmp_path: Path) -> None:
        """exit 5 = 沒收集到任何測試。**沒驗到不等於驗不過。**"""
        收場, 證據 = 建判準(_假pytest(tmp_path, 5))(任務(描述="", 工作目錄=tmp_path))

        assert 收場 is 判準終局.跑不起來, 證據
        assert "跑不起來" in 證據

    def test_用法錯誤是跑不起來(self, tmp_path: Path) -> None:
        """exit 4 = 旗標打錯或路徑不存在。改實作一百次也不會讓旗標變對。"""
        收場, 證據 = 建判準(_假pytest(tmp_path, 4))(任務(描述="", 工作目錄=tmp_path))

        assert 收場 is 判準終局.跑不起來, 證據
        assert "跑不起來" in 證據

    def test_有測試失敗還是紅(self, tmp_path: Path) -> None:
        """exit 1 = 真的有測試沒過。**只改「沒驗到」那兩格**，回饋那一格不准動。"""
        收場, _ = 建判準(_假pytest(tmp_path, 1))(任務(描述="", 工作目錄=tmp_path))

        assert 收場 is 判準終局.紅

    def test_全過還是綠(self, tmp_path: Path) -> None:
        收場, _ = 建判準(_假pytest(tmp_path, 0))(任務(描述="", 工作目錄=tmp_path))

        assert 收場 is 判準終局.綠

    def test_不是pytest的指令退出碼5仍是紅(self, tmp_path: Path) -> None:
        """**退出碼語意是各程式自己的知識，不是通用常識。**

        nova 自己的 4 就是「護欄生效」而不是「用法錯誤」。把 4／5 無條件
        翻成跑不起來，等於把別人給的回饋偽裝成環境問題——正好是
        `判準終局.跑不起來` 這個型別存在理由的鏡像錯誤。

        所以這個映射綁在 pytest 上；認不出來就退回當紅（降級方向安全）。
        """
        收場, _ = 建判準(["sh", "-c", "exit 5"])(任務(描述="", 工作目錄=tmp_path))

        assert 收場 is 判準終局.紅

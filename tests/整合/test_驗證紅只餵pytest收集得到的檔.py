"""`驗證紅` 只准把 **pytest 真的收得到的檔**餵給指定測試判準。

## 這支釘的是哪個洞

護欄的「動過的測試檔」故意不看檔名——`tests/` 底下全算，含 fixture、含被刪掉的檔
（實作員動 fixture 也是動測試）。那一格是對的。錯的是下游把同一個集合原封不動
當成 pytest 的命令列目標：

- 2026-09-02 09:50（run 92cfcd）：`tests/資料/儀表板設計稿CSS.css` 進了目標清單，
  pytest 對非 `.py` 沒有 collector → `ERROR: not found`（exit 4）→
  `判準終局.跑不起來` → 步驟終局「結果未知」→ 工作流停掉。**一支測試都沒跑到。**
- 2026-09-02 01:34（run 128d6f）：同一個洞，換成 `實錄/*.json` 與 `README.md`。
- 2026-09-01：同一個洞的第一次，`登記們/*.py` → exit 5。

三次都是「補一條排除項」收場，所以這支測試釘的是另一半知識：
**「動過的測試檔」（護欄要看到 fixture）跟「pytest 目標」（pytest 收得到的檔）
是兩個集合。** 順帶釘第二半——改名／刪除的舊路徑也不是 pytest 收得到的檔。

## 這支怎麼接線

走真接線 `建TDD執行器(…, 建指定測試判準=假工廠, 篩選指定測試=可作指定pytest目標)`，
不叫私有函式：這個保證要活在「產線注入的那份政策」上，不是某個內部 helper 上。
判準用假工廠（只記下收到什麼），**不開真 pytest 子程序**——「真 pytest 對 `.css`
回 exit 4」已由上面那三次實測釘死，CI 不必每次再付一次子程序的錢。
"""

from pathlib import Path

from nova.契約.工作流 import 任務, 判準, 判準終局, 步驟結果, 階段代碼
from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.載體.判準 import 可作指定pytest目標
from nova.迴圈.工作流 import 建TDD執行器
from nova.迴圈.狀態機 import 查階段

#: 這一輪真的寫出來的測試檔。它是唯一一個 pytest 收得到的。
活著的測試 = "tests/test_甲.py"
會紅的內容 = "def test_甲() -> None:\n    assert 1 + 1 == 3\n"
#: 測試員同一輪放的 fixture。護欄看得到它（對），但它不是 pytest 目標。
fixture檔 = "tests/資料/乙.css"
#: 改名前的舊路徑：護欄把「刪除」也算動過測試，但這個檔已經不在工作樹上了。
已不在的舊路徑 = "tests/test_丙.py"


class _假角色:
    @property
    def 名稱(self) -> str:
        return "假角色"

    def 做(self, 提示: str, *, 工作目錄: Path | None = None) -> 回應:
        del 提示, 工作目錄
        return 回應(
            文字="做好了",
            終局=終局.成功,
            失敗代碼=失敗代碼.無,
            原始結束碼=0,
            對話識別碼=None,
            用量=用量(輸入token=1, 輸出token=1),
        )


class _假工廠:
    """記下「哪幾個檔真的被接到 pytest 指令上」。"""

    def __init__(self) -> None:
        self.收到: list[tuple[str, ...]] = []

    def __call__(self, 檔們: tuple[str, ...]) -> 判準:
        self.收到.append(檔們)

        def 判(_: 任務) -> tuple[判準終局, str]:
            return 判準終局.紅, "假判準：1 failed"

        return 判


def _工作區(tmp_path: Path) -> Path:
    """只有 `tests/test_甲.py` 與 `tests/資料/乙.css` 真的存在。丙已經被改名走了。"""
    (tmp_path / "tests" / "資料").mkdir(parents=True)
    (tmp_path / 活著的測試).write_text(會紅的內容, encoding="utf-8")
    (tmp_path / fixture檔).write_text("body { color: red; }\n", encoding="utf-8")
    return tmp_path


def _跑驗證紅(tmp_path: Path) -> tuple[_假工廠, 步驟結果]:
    工廠 = _假工廠()
    全套跑過了: list[str] = []

    def 跑全套(_: 任務) -> tuple[判準終局, str]:
        全套跑過了.append("跑了")
        return 判準終局.紅, "假全套判準"

    執行 = 建TDD執行器(
        角色表={
            階段代碼.測試: _假角色(),
            階段代碼.實作: _假角色(),
            階段代碼.重構: _假角色(),
            階段代碼.審查: _假角色(),
        },
        跑判準=跑全套,
        建指定測試判準=工廠,
        篩選指定測試=可作指定pytest目標,
    )
    軌跡 = (
        步驟結果(
            階段=階段代碼.測試,
            終局=終局.成功,
            判準綠=None,
            證據="寫好了",
            動過的測試檔=(活著的測試, fixture檔, 已不在的舊路徑),
        ),
    )
    這步 = 執行(查階段(階段代碼.驗證紅), 任務(描述="讓 X 變成 Y", 工作目錄=_工作區(tmp_path)), 軌跡)
    assert not 全套跑過了, "有一個檔收得到就不該退回全套判準"
    return 工廠, 這步


def test_動過的測試檔含fixture與已刪檔時工廠只收到活著的測試檔(tmp_path: Path) -> None:
    """餵不下去的檔一個都不准上命令列——那就是 exit 4／「結果未知」那條路。"""
    工廠, _ = _跑驗證紅(tmp_path)

    assert 工廠.收到 == [(活著的測試,)], f"只有 pytest 收得到的檔可以當目標，實際收到：{工廠.收到}"


def test_證據那行只列真的餵給pytest的那幾支(tmp_path: Path) -> None:
    """證據把 fixture 一起列進「驗了」那一段，讀的人會以為它被驗過。"""
    _, 這步 = _跑驗證紅(tmp_path)

    那一行 = 這步.證據.splitlines()[0]
    assert 活著的測試 in 那一行, 那一行
    assert fixture檔 not in 那一行, f"fixture 沒被驗，不准列進「驗了」那一段：{那一行}"
    assert 已不在的舊路徑 not in 那一行, f"這個檔已經不在工作樹上：{那一行}"

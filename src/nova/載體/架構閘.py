"""三層落點閘：`契約 ← 迴圈 ← 載體`，箭頭不准反過來。

守的兩條（`載體` 可以 import 任何一層，它是最外圈，那是設計）：

1. `src/nova/契約/` 底下**不准** import `nova.載體.*` 或 `nova.迴圈.*`
2. `src/nova/迴圈/` 底下**不准** import `nova.載體.*`

**`if TYPE_CHECKING:` 主體裡的 import 放行（`else:` 那半邊不放行）。**
兩種決定都說得通，這裡選放行，
理由是：那種 import **執行期根本不會發生**，低層的模組不會因此被載入，
也就沒有「低層決定高層長什麼樣」的執行期耦合——真正要擋的是那個。
把它一起算進去的話，唯一的出路是改寫成字串 forward reference 或 `Any`，
那是把同一份相依**藏起來**（而且順便弄壞型別檢查），不是移除它。
**代價要講明**：這條放行讓「先寫成 TYPE_CHECKING、之後有人搬到執行期」
變成可能，擋那一步的是這道閘本身——搬出去的那一刻它就紅。

`import nova.載體.x` 這種寫法一樣算——不然把 `from` 換成 `import` 就繞過去了。
"""

import ast
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

#: 哪一層不准 import 哪幾層。寫成表不是寫成 `if`：加一層＝加一列。
#: 沒列進來的層（例如最外圈的 `載體`）＝不受限，那是設計。
_每一層不准import的層們: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "契約": ("載體", "迴圈"),
        "迴圈": ("載體",),
    }
)


def _說法(層: str, 不准的層們: tuple[str, ...]) -> str:
    """紅的時候要說出來的那條規則，直接從禁令資料長出來。

    不另外存一句話：存兩份的話改了資料忘了改字串，訊息就開始說謊。
    """
    return f"{層}不准 import {'或'.join(不准的層們)}"


#: 住在某一層底下要湊得出 `nova/<層>/<檔>` 三格；`src/nova/__init__.py` 這種只有兩格，
#: 它不住在任何一層裡。
_住在某一層底下至少幾格 = 3


def _從nova數起的片段們(路徑: str) -> tuple[str, ...]:
    """路徑裡從 `nova` 那一格開始往後數的片段。

    `src/nova/迴圈/工作流.py` → `("nova", "迴圈", "工作流.py")`。
    找不到 `nova` 就回空的：那個檔不在這棵樹底下，沒有哪一條管得到它。
    """
    片段 = Path(路徑).as_posix().split("/")
    if "nova" not in 片段:
        return ()
    return tuple(片段[片段.index("nova") :])


def _住哪一層(路徑: str) -> str | None:
    """這個檔住 `src/nova/<層>/` 的哪一層。不住在任何一層底下的回 `None`。

    只認路徑不認禁令表：住哪一層是事實，受不受管是另一回事。
    """
    片段 = _從nova數起的片段們(路徑)
    if len(片段) < _住在某一層底下至少幾格:
        return None
    return 片段[1]


def _型別檢查主體裡的import們(樹: ast.Module) -> set[ast.AST]:
    """`if TYPE_CHECKING:` **主體**裡的每一個 import 節點。

    只收 `body`，不收 `else`：`else` 那半邊正是 `TYPE_CHECKING` 為假、
    也就是**執行期真的會跑**的那一半，放行它等於放行真正的越界。

    收的是節點本身（AST 節點按身分比對，不是按內容），所以同一份原始碼裡
    長得一樣的兩行 import 不會互相誤傷。放行的理由見模組 docstring。
    """
    放行: set[ast.AST] = set()
    for 節點 in ast.walk(樹):
        if not isinstance(節點, ast.If) or not _是型別檢查(節點.test):
            continue
        for 句 in 節點.body:
            放行.update(子 for 子 in ast.walk(句) if isinstance(子, ast.Import | ast.ImportFrom))
    return 放行


def _是型別檢查(條件: ast.expr) -> bool:
    """這個 `if` 的條件是不是**明寫的** `TYPE_CHECKING` 或 `typing.TYPE_CHECKING`。

    只認這兩種寫法。任何其他 `<某物>.TYPE_CHECKING`（例如 `設定.TYPE_CHECKING`）
    都可能是執行期才決定真假的旗標，照那種條件放行等於在閘上留一道
    「自己定一個叫 TYPE_CHECKING 的屬性就過」的門。
    """
    if isinstance(條件, ast.Name):
        return 條件.id == "TYPE_CHECKING"
    return (
        isinstance(條件, ast.Attribute)
        and 條件.attr == "TYPE_CHECKING"
        and isinstance(條件.value, ast.Name)
        and 條件.value.id == "typing"
    )


def _這個檔的套件(路徑: str) -> tuple[str, ...]:
    """這個檔所在的套件：`src/nova/迴圈/工作流.py` → `("nova", "迴圈")`。

    相對 import 的第一個 `.` 就是從這裡算起（`__init__.py` 照目錄算也對，
    它本來就代表那個套件）。
    """
    return _從nova數起的片段們(路徑)[:-1]


def _相對import解成絕對(所在套件: tuple[str, ...], 節點: ast.ImportFrom) -> tuple[str, ...]:
    """點開頭的寫法照來源檔的位置解成絕對全名：`從迴圈/ 寫 ..載體.x` → `nova.載體.x`。

    第一個 `.` 指的就是所在套件本身，之後每多一個點各再往上退一層。
    退到 `src/` 外面去就回空的：那裡指不到這棵樹裡的任何一層。
    """
    往上退幾層 = 節點.level - 1
    if 往上退幾層 > len(所在套件):
        return ()
    基底 = 所在套件[: len(所在套件) - 往上退幾層]
    if 節點.module is not None:
        return (".".join([*基底, 節點.module]),)
    return tuple(".".join([*基底, 名.name]) for 名 in 節點.names)  # `from . import 載體`


def _這個節點import了哪些模組(路徑: str, 節點: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    """一個 import 節點碰到的模組全名。相對 import 先解析成絕對的才比。

    `import nova.載體.x`、`from nova.載體.x import y`、`from ..載體.x import y`
    一樣算——不然換個寫法就繞過去了。
    """
    if isinstance(節點, ast.Import):
        return tuple(名.name for 名 in 節點.names)
    if 節點.level == 0:  # 絕對寫法：`節點.module` 已經是全名了
        return (節點.module,) if 節點.module else ()
    return _相對import解成絕對(_這個檔的套件(路徑), 節點)


def _被import的nova模組們(路徑: str, 樹: ast.Module) -> list[tuple[int, str]]:
    """檔裡每一個 `nova.*` 的 import：(行號, 模組全名)。TYPE_CHECKING 主體裡的不算。"""
    放行 = _型別檢查主體裡的import們(樹)
    return [
        (節點.lineno, 模組)
        for 節點 in ast.walk(樹)
        if isinstance(節點, ast.Import | ast.ImportFrom) and 節點 not in 放行
        for 模組 in _這個節點import了哪些模組(路徑, 節點)
        if 模組.startswith("nova.")
    ]


def _模組住哪一層(模組: str) -> str:
    """`nova.<層>.<...>` 裡的那個 `<層>`。呼叫端已經保證開頭是 `nova.`。"""
    片段 = 模組.split(".")
    return 片段[1] if len(片段) > 1 else ""


def _一個檔的違規們(路徑: str, 原始碼: str) -> list[str]:
    """這個檔踩到的每一句：哪個檔、哪一行、違反哪一條、越界到哪個模組。"""
    層 = _住哪一層(路徑)
    if 層 is None:  # 不住在 `src/nova/<層>/` 底下，沒有哪一條管得到它
        return []
    不准的層們 = _每一層不准import的層們.get(層)
    if 不准的層們 is None:  # 不受限的層（例如最外圈的 `載體`），那是設計
        return []
    return [
        f"{路徑}:{行號}：{_說法(層, 不准的層們)}——這裡 import 了 {模組}"
        for 行號, 模組 in _被import的nova模組們(路徑, ast.parse(原始碼))
        if _模組住哪一層(模組) in 不准的層們
    ]


def 判定架構落點(檔們: Mapping[str, str]) -> tuple[bool, str]:
    """把「路徑 → 原始碼」判成綠紅。純函式，不碰硬碟。

    紅的訊息要說得出**哪個檔、哪一行、違反哪一條、越界到哪個模組**——
    只說「有越界」的訊息等於沒說，收到的人還得自己再掃一次。
    """
    違規們 = [句 for 路徑 in sorted(檔們) for 句 in _一個檔的違規們(路徑, 檔們[路徑])]
    if 違規們:
        return False, "三層落點被越界了：\n" + "\n".join(違規們)
    return True, f"三層落點沒有越界（掃了 {len(檔們)} 個檔）"


def 檢查架構落點(根目錄: Path) -> tuple[bool, str]:
    """掃 `src/nova/` 底下每一個 `.py`。純 AST，毫秒級，所以提交閘也跑得起。"""
    來源 = 根目錄 / "src" / "nova"
    檔們 = {
        str(檔.relative_to(根目錄)): 檔.read_text(encoding="utf-8")
        for 檔 in sorted(來源.rglob("*.py"))
        if "__pycache__" not in 檔.parts
    }
    return 判定架構落點(檔們)

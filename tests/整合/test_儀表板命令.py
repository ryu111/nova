"""`nova 儀表板`：契約 → 一頁 HTML（寫到狀態目錄）／`--json`（只吐資料）。

資料層那支（`test_儀表板資料.py`）釘的是「每個數字從哪個讀取器來」；
這一支釘的是**那份契約到了磁碟上還是同一份**：

* 契約裡沒有的格子在模板上喊「未接線」，**不准長出假數字**。
  設計稿的數字是主 agent 10:05 手拼寫死的，整份留在模板裡的話，
  儀表板會變成一張「看起來很準的靜態圖」——那比沒有儀表板更糟。
* 「還沒做」（未接線）跟「壞了」（`None`／查不到）要**在畫面上分得出來**。
  長得一樣的話，人會把沒接線的格子當成「今天剛好是 0」。
* 落點在狀態目錄，**不准寫進工作目錄**（CLAUDE.md：會被餵回模型的東西，
  執行者不准碰）。
* 票標題與護欄原因是自由文字，兩個新的磁碟落點（`.html` 與 `--json`）
  漏遮一個字都不會有人說——所以假憑證在兩邊都要 grep 不到，
  而 `<script>` 要變成 `&lt;script&gt;`。

跑真的 CLI、開真的 git worktree，所以住整合層。

被釘的介面（現在還不存在，這個檔是紅的）：`剖析器` 的 `儀表板` 子命令、
`載體/儀表板/命令.py`、`呈現.py`、`模板.html`。
"""

import json
import re
from collections.abc import Callable
from html import escape as _跳脫
from pathlib import Path
from typing import Any

import pytest

from nova.契約.儀表板 import 儀表板轉字典
from nova.載體.儀表板 import 組儀表板
from nova.載體.命令列 import 主程式
from nova.載體.專案脈絡 import 建專案執行脈絡
from nova.載體.帳本 import 專案識別
from nova.載體.收件 import 收件目錄, 處理中目錄
from nova.載體.狀態 import 狀態根目錄
from tests.單元.test_儀表板契約 import _契約說的落盤鍵樹, _對不上的鍵層, _這份落盤的鍵樹
from tests.單元.test_儀表板模板 import _沒釘好的格子
from tests.整合.test_儀表板資料 import _git, _假憑證, _造狀態目錄

#: 設計稿裡手拼寫死的數字與白話文。**一個都不准活到輸出裡。**
#: 只挑不會跟 fixture 撞的字串——裸小整數當哨兵會變成假紅。
_設計稿哨兵 = (
    "995M",
    "1,298",
    "932,374,108",
    "2,109,443",
    "US$375.56",
    "318 秒",
    "九億九千五百萬",
    "375 塊美金",
    "41 張紙條",
    "24 張是重複",
    "8 個機器人",
    "210 本",
    "228 倍",
)

#: 設計稿外面那層 design runtime 的殼。去殼沒去乾淨的話 HTML 開不起來。
_殼 = ("support.js", "<x-dc", "<helmet")

#: 契約裡**沒有這一格**：今日合併、負控閘分子、自己動手件數、鬼影、已併入、
#: 閘鎖排隊、閘鎖門檻、一次閘多久、佔住的檔名、刀數、合法階段分子、
#: 結果未知的原話、harvest_state。
_未接線格數 = 13

_沒有這一格 = "契約裡沒有這一格"
_這次查不到 = "契約有這格、這次查不到"

_跨站腳本 = "<script>alert(1)</script>"


def _開一條線(專案: Path, 工作區: Path, 分支: str, 題目: str) -> None:
    """開一條真的 worktree，並在它自己的收件匣 `處理中/` 放一張票。

    線的現況要由真的 `查並行現況` 問出來——CLI 那條路沒有注入點，
    而「線列渲染成什麼」正是這支要看的東西。
    """
    _git(專案, "worktree", "add", "-q", "-b", 分支, str(工作區))
    處理中 = 處理中目錄(收件目錄(工作區))
    處理中.mkdir(parents=True, exist_ok=True)
    (處理中 / "20260902T0930.md").write_text(f"# {題目}\n\n內文\n", encoding="utf-8")


def _造現場(tmp_path: Path) -> Path:
    """資料層那支的同一份 fixture，外加兩條真的 worktree。

    一條的票標題帶假憑證（遮罩要吃掉），一條帶 `<script>`（跳脫要吃掉）。
    """
    專案, _sha, _假查線們 = _造狀態目錄(tmp_path)
    _開一條線(專案, tmp_path / "線甲", "甲", f"修好收件匣 {_假憑證}")
    _開一條線(專案, tmp_path / "線戊", "戊", f"修 {_跨站腳本} 的洞")
    return 專案


def _檔案樹(根: Path) -> list[str]:
    """根底下的相對路徑清單。

    `.git` 內部不算——git 自己會動索引的 mtime，
    而這支問的是「有沒有多長出檔案給模型看到」。
    """
    return sorted(str(路徑.relative_to(根)) for 路徑 in 根.rglob("*") if ".git" not in 路徑.parts)


def _每一格(值: object, 路徑: str = "") -> list[tuple[str, object]]:
    """把 `儀表板轉字典` 攤成 `(ASCII 路徑, 值)` 的窮舉清單。

    **抽查會漏。** 抽三個數字驗過去，模板上刪掉收件匣、可見度或負控的
    任何一個 `${…}` 都還是全綠——那一格會安靜地不見，而沒有人記得它本來在那裡。
    所以「有」的每一格都從契約自己數出來，一格一個斷言。
    """
    if isinstance(值, dict):
        return [
            一格
            for 鍵, 內 in 值.items()
            for 一格 in _每一格(內, f"{路徑}.{鍵}" if 路徑 else str(鍵))
        ]
    if isinstance(值, list):
        return [(路徑, 值)] + [
            一格 for 序, 內 in enumerate(值) for 一格 in _每一格(內, f"{路徑}[{序}]")
        ]
    return [(路徑, 值)]


#: 只有這一格比不了值：時鐘會走，測試組那份跟命令跑出來那份的秒數本來就可以不同。
#: **不比值的欄位要寫得出理由**，不然「這格不驗」會慢慢吃掉整圈窮舉。
_不比值的 = frozenset({"elapsed_s"})

#: 幾格不照通則比：畫面上本來就寫成別的講法（百分比、兩位小數、短 sha）。
_特例: dict[str, Callable[[Any], tuple[str, ...]]] = {
    # 命令跑的時刻跟測試自己組那份差幾秒，只比得了日期。
    "generated_at": lambda 值: (str(值)[:10],),
    # 短 sha 也算數：設計稿上就是七碼。
    "head": lambda 值: (str(值)[:7],),
    "gate_green": lambda 值: ("綠",) if 值 else ("紅",),
    "cost_usd": lambda 值: (f"{float(值):.2f}",),
    "share": lambda 值: (f"{float(值) * 100:.1f}%",),
}


def _該長成的樣子(路徑: str, 值: object) -> tuple[str, ...]:
    """這一格在 HTML 上該長成什麼字。回空的代表這一格不驗值（理由見 `_特例`）。

    型別的講法要跟 `呈現` 對得起來——**這是第二份意見不是複製**：
    契約說 `True`、畫面上要說「在跑」；契約說 `None`、畫面上要說「查不到」，
    不准是 0、也不准是空白。
    """
    # 整串的值在它自己那幾列驗；`None` 那格由「查不到」那段驗，這裡沒有值可以比。
    if 值 is None or isinstance(值, list):
        return ()
    末 = 路徑.rsplit(".", 1)[-1]
    if 末 in _不比值的:
        return ()
    if 末 in _特例:
        return _特例[末](值)
    if isinstance(值, bool):
        return ("在跑",) if 值 else ("收工了",)
    if isinstance(值, int):
        return (str(值),)
    return (_跳脫(str(值)),)


def _說得出從哪來(html: str, 路徑: str) -> bool:
    """那一格說不說得出自己從哪個 json 鍵來（整格或整區都算）。"""
    區 = 路徑.split(".", maxsplit=1)[0].split("[", maxsplit=1)[0]
    return any(
        re.search(r"--json 的 " + re.escape(候選) + r"(?![\w.])", html) for 候選 in (路徑, 區)
    )


def _未接線的(html: str, 標題: str) -> list[str]:
    """挑出帶指定 `title` 的未接線格子，回它們的內文。"""
    樣式 = re.compile(
        r'<span[^>]*class="[^"]*未接線[^"]*"[^>]*title="'
        + re.escape(標題)
        + r'"[^>]*>(.*?)</span>',
        re.DOTALL,
    )
    反過來 = re.compile(
        r'<span[^>]*title="'
        + re.escape(標題)
        + r'"[^>]*class="[^"]*未接線[^"]*"[^>]*>(.*?)</span>',
        re.DOTALL,
    )
    return 樣式.findall(html) + 反過來.findall(html)


def test_產出的HTML含28格未接線13格且不含假數字(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """一頁 HTML：數字全來自契約，沒接線的格子要**說自己沒接線**。

    四件事一起守：

    1. **落點在狀態目錄**，工作目錄一個檔都不准多。
    2. **未接線的 13 格各自渲染成 `.未接線` 且格子裡沒有數字**——
       設計稿那些手拼數字一個都不准留下來。
    3. **「還沒做」跟「壞了」長得不一樣**：兩個 `title` 分開。
    4. **自由文字先遮再跳脫**：假憑證 grep 不到、`<script>` 變成實體。
    """
    專案 = _造現場(tmp_path)
    一份 = 組儀表板(專案)
    工作目錄樹 = _檔案樹(專案)

    碼 = 主程式(["--根目錄", str(專案), "儀表板"])

    assert 碼 == 0
    落點 = 狀態根目錄() / "專案" / 專案識別(專案) / "儀表板.html"
    assert 落點.is_file(), "儀表板落在狀態目錄，不是工作目錄——會被餵回模型的東西執行者不准碰"
    assert str(落點) in capsys.readouterr().out, "寫完要說寫到哪，不然人找不到那個檔"
    assert _檔案樹(專案) == 工作目錄樹, "工作目錄一個檔都不准多"

    html = 落點.read_text(encoding="utf-8")

    # 去殼：純靜態、不連外、沒有 JS；模板變數全部代換掉。
    assert '<meta charset="utf-8">' in html
    for 殼 in _殼:
        assert 殼 not in html, f"設計稿的殼沒去乾淨：{殼}"
    assert "${" not in html, "`substitute()` 少一個變數要當場炸，不准把 `${…}` 印出來"

    # 數字來自契約，不是設計稿：**契約裡的每一格窮舉一遍**，一格一個斷言。
    格子們 = _每一格(儀表板轉字典(一份))
    assert 格子們, "契約攤不出格子的話，下面那圈什麼都沒驗到"
    for 路徑, 值 in 格子們:
        for 該有 in _該長成的樣子(路徑, 值):
            assert 該有 in html, f"契約有這一格、頁面上沒有：{路徑}={值!r} 該長成 {該有!r}"
        assert _說得出從哪來(html, 路徑), f"這一格說不出自己從哪個 json 鍵來：{路徑}"

    for 哨兵 in _設計稿哨兵:
        assert 哨兵 not in html, f"設計稿手拼的數字活到輸出裡了：{哨兵}"

    # 線列：真的 worktree 問出來的兩條，票標題取處理中那張票的第一個 `# ` 行。
    assert "甲" in html and "戊" in html
    assert "修好收件匣" in html
    assert "quota_exhausted" in html, "失敗碼那張表是從帳本的 `failure_code` 數出來的"

    # 未接線 vs 查不到：同一個樣式、兩個 title，畫面上分得出來。
    沒有這一格 = _未接線的(html, _沒有這一格)
    assert len(沒有這一格) >= _未接線格數, (
        f"契約裡沒有的格子要每一格都喊出來（至少 {_未接線格數} 個），實際 {len(沒有這一格)} 個"
    )
    # **數量證明不了任何一格是誠實的**：徽章全掃到頁尾也是 13 個。
    # 每一格的徽章要跟那一格黏在一起，那一格才說得出「我這個數字沒有」。
    沒釘好的 = _沒釘好的格子(html)
    assert not 沒釘好的, "未接線的徽章沒有釘在自己那一格上：\n" + "\n".join(
        f"  {一句}" for 一句 in 沒釘好的
    )
    for 內文 in 沒有這一格:
        assert not re.search(r"\d", 內文), f"未接線的格子不准長出數字：{內文!r}"
    assert _未接線的(html, _這次查不到), (
        "查不到的格子要用另一個 title——跟『還沒做』長得一樣的話，人會當成今天剛好是 0"
    )
    assert "查不到" in html, "`目前階段 is None` 要渲染成「查不到」，不是空白"

    # 每格說得出自己從哪來（寫 json 鍵，不寫 file:line）。
    assert "inbox.waiting" in html
    assert "failure_codes" in html

    # 自由文字：先遮罩、再跳脫。
    assert _假憑證 not in html, "儀表板是新的磁碟落點，漏遮一個字都不會有人說"
    assert _跨站腳本 not in html
    assert "&lt;script&gt;" in html, "票標題是自由文字，所有字串值都要 `html.escape`"


def test_json跟契約欄位一一對應且鍵是ASCII(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--json` 就是那份契約，**只印到 stdout、一個檔都不落**。

    頂層鍵集合就是「儀表板有哪幾格」：少一格代表下游少一個數字，
    而下游不會知道自己少了什麼。
    """
    專案 = _造現場(tmp_path)
    工作目錄樹 = _檔案樹(專案)
    狀態樹 = _檔案樹(狀態根目錄())

    碼 = 主程式(["--根目錄", str(專案), "儀表板", "--json"])

    assert 碼 == 0
    出 = capsys.readouterr().out
    一份 = json.loads(出)
    assert isinstance(一份, dict)
    # **落盤有哪幾格是契約自己說的**（`落盤鍵樹`，形狀怎麼守見 `test_儀表板契約.py`）。
    # 這裡手抄一份 ASCII 鍵集合的話，那份跟契約的對照表出自同一隻手：
    # 契約長出一欄而兩邊一起漏，兩邊還是相等的。
    # 比的是**整棵樹**不是頂層：`lanes`／`families`／`failure_codes` 底下少一格
    # 一樣是下游少一個數字，而那幾層只有真的跑過一次 CLI 才看得到。
    assert 一份["lanes"] and 一份["families"] and 一份["failure_codes"], (
        "這份 fixture 要讓每一層都有內容，不然序列底下那幾格根本沒被比到"
    )
    對不上的 = _對不上的鍵層(_這份落盤的鍵樹(一份), _契約說的落盤鍵樹())
    assert not 對不上的, "落盤的鍵層對不起契約說的形狀：\n" + "\n".join(
        f"  {一句}" for 一句 in 對不上的
    )
    assert set(一份) == set(儀表板轉字典(組儀表板(專案))), (
        "`--json` 的形狀就是 `儀表板轉字典`，不准另外拼一份"
    )

    鍵們: list[str] = []

    def _收鍵(值: object) -> None:
        if isinstance(值, dict):
            for 鍵, 內 in 值.items():
                鍵們.append(str(鍵))
                _收鍵(內)
        elif isinstance(值, list):
            for 內 in 值:
                _收鍵(內)

    _收鍵(一份)
    assert 鍵們, "巢狀那幾層也要落盤，不然 lanes／inbox 只剩空殼"
    assert all(鍵.isascii() for 鍵 in 鍵們), (
        f"中文鍵在 shell 裡很難打：{[鍵 for 鍵 in 鍵們 if not 鍵.isascii()]}"
    )

    assert _檔案樹(專案) == 工作目錄樹
    assert _檔案樹(狀態根目錄()) == 狀態樹, "`--json` 只吐到 stdout，不准順手落一份 HTML"
    assert _假憑證 not in 出, "第二個磁碟落點，同樣要先遮再吐"


def test_相對根目錄下的工作目錄跟專案脈絡是同一份(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """**「工作目錄」這一格只有一個來源**：CLI 已經建好的 `專案脈絡.根目錄`。

    上面兩支都拿絕對暫存路徑呼叫，所以「自己再 `Path(參數.根目錄)` 一次」
    看起來跟脈絡沒有差別。人真的在敲的是預設的 `--根目錄 .` 或一個相對路徑——
    那時候儀表板會說自己的工作目錄是 `.`，而同一次執行的其他落點
    （收件匣、帳本、已處理）用的是 resolve 過的那一份。
    **同一份儀表板上出現兩個「這是哪個專案」的答案**，看的人無從分辨哪個是真的。
    """
    專案 = _造現場(tmp_path)
    脈絡的答案 = str(建專案執行脈絡(專案).根目錄)
    寫法們 = ((專案, ["儀表板", "--json"]), (tmp_path, ["--根目錄", "主線", "儀表板", "--json"]))

    for 站在, 參數們 in 寫法們:
        monkeypatch.chdir(站在)
        主程式(參數們)

        assert json.loads(capsys.readouterr().out)["workdir"] == 脈絡的答案, (
            f"在 {站在} 敲 {參數們}：工作目錄跟 `專案脈絡.根目錄` 不是同一份"
        )

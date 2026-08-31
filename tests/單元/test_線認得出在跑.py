"""餵真實的 `ps` 輸出，確認 `nova 線` 認得出一條確實在跑的線。

`tests/資料/` 底下那兩個檔是 2026-09-01 從 `ps -axo pid=,etime=,lstart=,command=`
**原樣抓下來**的，沒有整理成「乾淨」的樣子——這條漏報的成因就藏在真實輸入的形狀裡：
一條線同時有 `uv run nova 工作流 …` 與 `…/python3 …/nova 工作流 …` 兩個程序，
兩個都不是「`nova` 開頭」也不是「`python -m nova`」。

三值語意（是／否／查不到）在這裡一起釘住：斷言一律用 `is True` / `is False`，
不用 `assert 在跑嗎`——那種寫法會把 `None`（查不到）跟 `False`（確定沒在跑）混掉。
"""

from pathlib import Path

from nova.載體.線 import _是否在跑, _程序清查, _程序資料, _解析一行ps

資料夾 = Path(__file__).parent.parent / "資料"

#: 兩個 fixture 檔裡的 `--工作目錄` 都指這條線。
在跑的工作樹 = Path("/Users/sbu/nova-wt-線漏報")

#: 隨便挑一個不會撞到 fixture 裡任何 pid 的假 pid，只是為了填 `_解析一行ps` 的參數。
本身pid = 999999


def _清查(檔名: str) -> tuple[_程序清查, list[tuple[_程序資料 | None, bool]]]:
    """把一個 fixture 檔逐行餵給 `_解析一行ps`，湊出 `_程序清查`。

    回傳 (清查, 每一行的原始解析結果)，後者留給「哪一行被怎麼判」的斷言用。
    """
    行們 = (資料夾 / 檔名).read_text(encoding="utf-8").splitlines()
    每行結果 = [_解析一行ps(行, 本身pid) for 行 in 行們]
    程序們 = [程序 for 程序, 未定位 in 每行結果 if 程序 is not None and not 未定位]
    有無法定位 = any(未定位 for _, 未定位 in 每行結果)
    return _程序清查(程序們=程序們, 有無法定位工作目錄的程序=有無法定位), 每行結果


def test_真實ps裡一條在跑的線不准被判成沒在跑() -> None:
    """`uv run nova 工作流 …` 與 `python3 …/nova 工作流 …` 這對真實程序要認得出來。

    現況是兩行都被 `_是nova命令` 擋掉，於是這條線被判成「確定沒在跑」（`False`），
    `nova 線` 就印「在跑嗎：否」——而它其實在跑。
    """
    清查, 每行結果 = _清查("ps一條線的兩個程序.txt")

    # 先確認走的不是「查不到」那條路：這條線是被判成「確定沒在跑」，不是資訊不足。
    assert 清查.有無法定位工作目錄的程序 is False

    # 收件匣 daemon（`nova-inbox …`）本來就抓得到，拿它當控制組：
    # fixture 不是整批都解析失敗，只有那條線漏掉。
    assert Path("/Users/sbu/nova") in [程序.工作目錄 for 程序 in 清查.程序們]

    # 真正要的：那條線在跑。
    assert 在跑的工作樹 in [程序.工作目錄 for 程序 in 清查.程序們]
    assert _是否在跑(在跑的工作樹, 清查) is True

    # 兩個程序都要認得，不是只靠其中一個矇到。
    認得的行數 = sum(
        1 for 程序, _ in 每行結果 if 程序 is not None and 程序.工作目錄 == 在跑的工作樹
    )
    assert 認得的行數 == 2

    # 順帶釘住欄位有對齊：`跑多久` 是 etime 那欄，不是被 lstart 擠掉的東西。
    那條線 = [程序 for 程序 in 清查.程序們 if 程序.工作目錄 == 在跑的工作樹]
    assert 那條線[0].跑多久 == "00:28"
    assert 那條線[0].啟動時間 == "二  9月/ 1 02:23:13 2026"


def test_混一行超長又引號沒配對的claude程序不准害別的行漏掉() -> None:
    """同一批輸入裡混一行 4900 字元、含反引號與落單單引號的 `claude` 子程序行。

    那一行 `shlex.split` 會丟 `ValueError`，`_解析一行ps` 得退回 `欄[7].split()`；
    退回歸退回，**不准害同一批裡別的行漏掉**，也不准把它自己算成
    「無法定位工作目錄的 nova 程序」——那會把整份清查降級成「查不到」（`None`），
    等於用一條 claude 子程序把所有線的「在跑嗎」都變成問號。
    """
    清查, 每行結果 = _清查("ps混超長claude行.txt")

    # 那行 claude 本身：既不是 nova 線，也不是「定位不到的 nova 程序」。
    claude那行 = 每行結果[1]
    assert claude那行 == (None, False)
    assert 清查.有無法定位工作目錄的程序 is False

    # 夾在它前後的兩行 nova 程序不准被連累。
    assert _是否在跑(在跑的工作樹, 清查) is True
    assert [程序.工作目錄 for 程序 in 清查.程序們] == [在跑的工作樹, 在跑的工作樹]


def test_沒出現在ps裡的線還是判成沒在跑() -> None:
    """負向：不准為了不漏報就把所有不確定都當「是」。

    清查得出來（`有無法定位工作目錄的程序` 是 `False`）、而這條線不在裡面，
    那就是確定沒在跑，要回 `False` 而不是 `True` 也不是 `None`。
    """
    清查, _ = _清查("ps一條線的兩個程序.txt")

    assert _是否在跑(Path("/Users/sbu/nova-wt-根本沒這條"), 清查) is False

"""守「餵給 pytest 的只能是 pytest 收得到的活著的測試檔」的兩把刀。

真因（2026-09-02 09:50 run 92cfcd）：護欄的「動過的測試檔」故意不看檔名，
`tests/資料/儀表板設計稿CSS.css` 一路走到 pytest 命令列 → 沒有 collector →
exit 4 → 判準終局.跑不起來 → 步驟終局「結果未知」→ 工作流停掉，一支測試都沒跑。
同一類的洞開過三次（09-01 登記們 exit 5、09-02 01:34 實錄/*.json、09-02 09:50 CSS），
前兩次都是補一條排除項收場。這兩把刀分別砍真因的兩半：
**檔名要 pytest 收得到**、**檔要還在工作樹上**（改名 ＝ 刪＋加，舊路徑一樣 exit 4）。
"""

from pathlib import Path

from tests.負控.登記 import 替換一次, 變異

登記 = (
    #: allow-list 拿掉＝`.css`／`.json`／`.md` 又會被接上 pytest 命令列，就是 494 那條路。
    變異(
        識別="指定測試目標不再看檔名是否為pytest收得到的",
        目標檔=Path("src/nova/載體/判準.py"),
        操作=替換一次(
            '    return 檔名.endswith(".py") and '
            '(檔名.startswith("test_") or 檔名.endswith("_test.py"))\n',
            "    return True\n",
        ),
        該紅=(
            (
                "tests/單元/test_指定測試目標政策.py::Test不能當指定目標的非測試檔"
                "::test_pytest收集不到的檔不能當目標"
            ),
            (
                "tests/整合/test_驗證紅只餵pytest收集得到的檔.py"
                "::test_動過的測試檔含fixture與已刪檔時工廠只收到活著的測試檔"
            ),
        ),
        最多秒=120.0,
    ),
    #: 存在性判斷拿掉＝改名前的舊路徑又會被餵下去，pytest 回 `ERROR: not found`。
    變異(
        識別="驗證紅不再確認測試檔還在工作樹上",
        目標檔=Path("src/nova/迴圈/工作流.py"),
        操作=替換一次(
            "    return (工作目錄 / 檔).is_file()\n",
            "    return True\n",
        ),
        該紅=(
            (
                "tests/整合/test_驗證紅只餵pytest收集得到的檔.py"
                "::test_動過的測試檔含fixture與已刪檔時工廠只收到活著的測試檔"
            ),
            (
                "tests/整合/test_驗證紅只餵pytest收集得到的檔.py"
                "::test_證據那行只列真的餵給pytest的那幾支"
            ),
        ),
        最多秒=120.0,
    ),
    #: 上面兩把砍真因，這一把另外算：它守的是**被釘住、刻意不改**的那半邊——
    #: 轉義的中文參數 id（`[儀表板]`）查證後不是 494 的真因，所以不解碼、
    #: 不關 pytest 的轉義選項，只用測試把「兩種長相都抽得出完整 nodeid」釘住。
    #: 釘子一寫就綠，證明它守著東西的是這把刀：樣式縮成只吃 ASCII，
    #: 反斜線與中文都會在 `[` 那裡截斷，連紅比對就開始拿殘缺 nodeid 去比。
    變異(
        識別="失敗行樣式只認ASCII的nodeid",
        目標檔=Path("src/nova/迴圈/狀態機.py"),
        操作=替換一次(
            r'_失敗行樣式 = re.compile(r"^(?:\[[^\n]+\][^\S\n]*)?FAILED[^\S\n]+(\S+::\S+)")'
            "\n",
            r"_失敗行樣式 = re.compile("
            r'r"^(?:\[[^\n]+\][^\S\n]*)?FAILED[^\S\n]+([A-Za-z0-9_./:\[\]-]+::[A-Za-z0-9_\[\]-]+)"'
            ")\n",
        ),
        #: 錨點是模組層的單一名稱賦值，coverage 的行只在 import 時走到、不落在
        #: 測試的 context 裡；空集合是「沒有可追的覆蓋行，固定測試直接驗值」的標記。
        必須覆蓋=frozenset(),
        該紅=(
            ("tests/單元/test_狀態機.py::test_失敗行的nodeid帶轉義或未轉義的中文參數id都抽得完整"),
        ),
        最多秒=120.0,
    ),
)

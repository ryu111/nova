"""CLAUDE.md 規則的 typed 登記與同步檢查。"""

import subprocess
import sys
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from re import compile as 編譯
from typing import assert_never

_標題模式 = 編譯(r"^(#{2,6})\s+(.+?)\s*$")
_粗體宣告模式 = 編譯(r"^\s*(?:(?:[-*+]|\d+[.)])\s+)?\*\*(.+?)\*\*")
_nodeid模式 = 編譯(r"^tests/.+\.py::.+$")
_有效替代方案模式 = 編譯(r"^用.+scheduled canary.+；人工驗收期限 \d{4}-\d{2}-\d{2}。$")
_日期模式 = 編譯(r"^\d{4}-\d{2}-\d{2}$")


class 規範狀態(StrEnum):
    """規範目前的落點。"""

    已成閘 = "已成閘"
    有測試背書 = "有測試背書"
    還是懇求 = "還是懇求"
    搬不動 = "搬不動"


@dataclass(frozen=True, slots=True)
class 規範登記:
    """CLAUDE.md 中一條規則的登記。"""

    識別: str
    狀態: 規範狀態
    理由: str
    閘代碼: str = ""
    測試nodeid: str = ""
    替代方案: str = ""
    到期日: str = ""
    標籤: str = ""


@dataclass(frozen=True, slots=True)
class _文件規則:
    """文件中一條規則的穩定識別與可讀標籤。"""

    識別: str
    標籤: str


def _擷取規則(文件: str) -> tuple[_文件規則, ...]:
    """以標題與行首粗體宣告切規則，識別不依賴文字內容。"""
    結果: list[_文件規則] = []
    標題序號: Counter[int] = Counter()
    宣告序號 = 0
    程式碼區 = False
    for 行 in 文件.splitlines():
        if 行.strip().startswith("```"):
            程式碼區 = not 程式碼區
            continue
        if 程式碼區:
            continue
        標題 = _標題模式.match(行)
        if 標題:
            層級 = len(標題.group(1))
            標題序號[層級] += 1
            結果.append(_文件規則(f"標題:{層級}:{標題序號[層級]}", 標題.group(2).strip()))
            continue
        宣告 = _粗體宣告模式.match(行)
        if 宣告:
            宣告序號 += 1
            結果.append(_文件規則(f"宣告:{宣告序號}", 宣告.group(1).strip()))
    return tuple(結果)


def _閘證據錯誤(項目: 規範登記, 閘代碼們: set[str]) -> str:
    """回報已成閘登記缺的證據。"""
    if not 項目.閘代碼:
        return f"{項目.識別} 標成已成閘卻沒有閘代碼"
    if 項目.閘代碼 not in 閘代碼們:
        return f"{項目.識別} 指到不存在的閘代碼：{項目.閘代碼}"
    return ""


def _測試證據錯誤(項目: 規範登記, 測試nodeid們: set[str]) -> str:
    """回報有測試背書登記缺的證據。"""
    if not 項目.測試nodeid:
        return f"{項目.識別} 標成有測試背書卻沒有測試 nodeid"
    if 項目.測試nodeid not in 測試nodeid們:
        return f"{項目.識別} 指到不存在的測試 nodeid：{項目.測試nodeid}"
    return ""


def _搬不動證據錯誤(項目: 規範登記) -> str:
    """回報搬不動登記缺的替代方案或期限。"""
    缺少: list[str] = []
    if not 項目.理由.strip():
        缺少.append("理由")
    if not 項目.替代方案.strip():
        缺少.append("替代方案")
    elif not _有效替代方案模式.fullmatch(項目.替代方案.strip()):
        缺少.append("有效替代方案")
    if not 項目.到期日.strip():
        缺少.append("到期日")
    elif not _日期模式.fullmatch(項目.到期日.strip()):
        缺少.append("有效到期日")
    elif 項目.到期日 < datetime.now(UTC).date().isoformat():
        缺少.append("到期日已過期")
    return f"{項目.識別} 標成搬不動卻缺少：{'、'.join(缺少)}" if 缺少 else ""


def _狀態錯誤(
    項目: 規範登記,
    閘代碼們: set[str],
    測試nodeid們: set[str],
) -> str:
    """檢查一筆登記依狀態應有的證據。"""
    match 項目.狀態:
        case 規範狀態.已成閘:
            return _閘證據錯誤(項目, 閘代碼們)
        case 規範狀態.有測試背書:
            return _測試證據錯誤(項目, 測試nodeid們)
        case 規範狀態.還是懇求:
            return f"{項目.識別} 還是懇求卻沒有說明理由" if not 項目.理由.strip() else ""
        case 規範狀態.搬不動:
            return _搬不動證據錯誤(項目)
        case _:  # pragma: no cover - 型別已窮盡
            assert_never(項目.狀態)


def 規範落點摘要(登記表: Sequence[規範登記]) -> str:
    """產生可直接印出的轉移進度。"""
    各狀態數量 = Counter(項目.狀態 for 項目 in 登記表)
    return (
        f"規範落點：{各狀態數量[規範狀態.已成閘]} 已成閘、"
        f"{各狀態數量[規範狀態.有測試背書]} 有測試背書、"
        f"{各狀態數量[規範狀態.還是懇求]} 還是懇求、"
        f"{各狀態數量[規範狀態.搬不動]} 搬不動（共 {len(登記表)} 條）"
    )


def _標籤錯誤(登記表: Sequence[規範登記], 文件標籤: dict[str, str]) -> list[str]:
    """找出同一機械識別下，登記與文件的標籤錯位。"""
    return [
        f"{項目.識別} 標籤不符：登記表「{項目.標籤}」、文件「{文件標籤[項目.識別]}」"
        for 項目 in 登記表
        if 項目.識別 in 文件標籤 and 項目.標籤 and 項目.標籤 != 文件標籤[項目.識別]
    ]


def _文件登記錯誤(文件規則: Sequence[_文件規則], 登記表: Sequence[規範登記]) -> list[str]:
    """找出文件規則與登記表的涵蓋、重複及錯位。

    文件規則的識別由切分器產生，登記表必須逐筆保存同一個機械識別。
    標籤只是給人看的交叉核對資料，不是另一套可以涵蓋文件的鍵。
    固定負控使用漏登記判斷的錨點，確保拔掉這個判斷時測試會紅。
    """
    文件標籤 = {規則.識別: 規則.標籤 for 規則 in 文件規則}
    文件識別 = set(文件標籤)
    登記識別 = [項目.識別 for 項目 in 登記表]
    登記集合 = set(登記識別)
    錯誤清單: list[str] = []
    重複識別 = sorted(識別 for 識別, 次數 in Counter(登記識別).items() if 次數 > 1)
    if 重複識別:
        錯誤清單.append(f"登記表識別重複：{'、'.join(重複識別)}")
    漏登記: list[str] = []
    for 規則 in 文件規則:
        # 固定負控的錨點；標籤只能用來拒絕冒充識別，不能作為涵蓋鍵。
        # 第一個分支處理正常的缺失識別，第二個分支處理標籤誤填成識別。
        # 兩條路都只會報錯，不會把標籤當成文件規則的涵蓋。
        if 規則.識別 not in 登記集合 and 規則.標籤 not in 登記集合:
            漏登記.append(規則.標籤)
        else:
            if 規則.識別 in 登記集合 or 規則.標籤 not in 登記集合:
                continue
            漏登記.append(規則.標籤)
    多登記 = sorted(識別 for 識別 in 登記集合 if 識別 not in 文件識別)
    if 漏登記:
        錯誤清單.append(f"文件未登記：{'、'.join(漏登記)}")
    if 多登記:
        錯誤清單.append(f"登記表多出：{'、'.join(多登記)}")
    錯誤清單.extend(_標籤錯誤(登記表, 文件標籤))
    return 錯誤清單


def 檢查文件與登記(
    文件: str,
    登記表: Sequence[規範登記],
    閘代碼們: Collection[str] = (),
    測試nodeid們: Collection[str] = (),
) -> tuple[bool, str]:
    """以純資料檢查文件、登記與兩種外部證據是否恰好對上。"""
    文件規則 = _擷取規則(文件)
    閘代碼集合 = set(閘代碼們)
    測試nodeid集合 = set(測試nodeid們)
    錯誤清單 = _文件登記錯誤(文件規則, 登記表)

    for 項目 in 登記表:
        錯誤 = _狀態錯誤(項目, 閘代碼集合, 測試nodeid集合)
        if 錯誤:
            錯誤清單.append(錯誤)
    if 錯誤清單:
        return False, "\n".join(錯誤清單)
    return True, 規範落點摘要(登記表)


規範登記表: tuple[規範登記, ...] = (
    規範登記(
        "標題:2:1",
        規範狀態.還是懇求,
        "架構說明尚未拆成可獨立判定的保證。",
        標籤="nova 是什麼",
    ),
    規範登記(
        "宣告:1",
        規範狀態.還是懇求,
        "宿主反轉架構尚未有獨立的機械 oracle。",
        標籤="宿主反轉架構",
    ),
    規範登記(
        "標題:2:2",
        規範狀態.還是懇求,
        "起手式的操作約束尚未由單一閘完整覆蓋。",
        標籤="起手式",
    ),
    規範登記(
        "宣告:2",
        規範狀態.還是懇求,
        "執行方式尚未有可在所有環境決定的閘。",
        標籤="一律走 `uv run`，不要先 activate venv",
    ),
    規範登記(
        "標題:2:3",
        規範狀態.還是懇求,
        "這組陷阱尚未逐條拆成可重播的判準。",
        標籤="這個 repo 的坑",
    ),
    規範登記(
        "標題:3:1",
        規範狀態.有測試背書,
        "單元層不可 fork 已有驗收測試。",
        測試nodeid="tests/驗收/test_專案骨架.py::test_單元層不准fork子程序",
        標籤="分層是時間預算，不是分類學",
    ),
    規範登記(
        "標題:3:2",
        規範狀態.還是懇求,
        "規則唯一來源尚未有專門的同步閘。",
        標籤="規則只寫一份",
    ),
    規範登記(
        "宣告:3",
        規範狀態.還是懇求,
        "設定檔不可藏邏輯尚未有獨立的機械 oracle。",
        標籤="不要往 YAML／JSON 裡塞邏輯",
    ),
    規範登記(
        "標題:3:3",
        規範狀態.還是懇求,
        "三個假保證尚未逐條接上可重播證據。",
        標籤="三個會讓你以為有保證、其實沒有的地方",
    ),
    規範登記(
        "標題:3:4",
        規範狀態.已成閘,
        "ruff-check 會執行 pyproject.toml 的靜態判準。",
        閘代碼="ruff-check",
        標籤="`pyproject.toml` 停用的那幾組 ruff 規則不要「修好」",
    ),
    規範登記(
        "標題:3:5",
        規範狀態.已成閘,
        "機密掃描已掛在 CI 規則表。",
        閘代碼="no-secrets",
        標籤="repo 是 public",
    ),
    規範登記(
        "宣告:4",
        規範狀態.搬不動,
        "遠端 GitHub ruleset 的決定不在本機 oracle 內。",
        替代方案=(
            "用隔離 sandbox repo 的 scheduled canary 驗證，沒有環境就標 NOT_RUN；"
            "人工驗收期限 2026-09-30。"
        ),
        到期日="2026-09-30",
        標籤="squash 合併的 commit 訊息繞過 commit-msg hook",
    ),
    規範登記(
        "宣告:5",
        規範狀態.搬不動,
        "main 保護規則的 required check context 屬於遠端設定。",
        替代方案=("用隔離 repo 的 scheduled canary 驗證 context；人工驗收期限 2026-09-30。"),
        到期日="2026-09-30",
        標籤="`gates` 這個 job 名稱是 main 保護規則的 required check context",
    ),
    規範登記(
        "宣告:6",
        規範狀態.有測試背書,
        "三種快取的閘參數已有針對性測試。",
        測試nodeid="tests/整合/test_閘不准吃快取.py::test_閘的mypy規則不會被假快取騙過去",
        標籤="三種快取的鍵都不含內容",
    ),
    規範登記(
        "宣告:7",
        規範狀態.有測試背書,
        "等長同 mtime 的快取陷阱已有重現測試。",
        測試nodeid="tests/整合/test_閘不准吃快取.py::test_ruff的快取真的會給假綠",
        標籤="同一秒內改兩次、長度剛好一樣就中",
    ),
    規範登記(
        "標題:2:4",
        規範狀態.還是懇求,
        "三層落點尚未由一個完整的結構判定器保證。",
        標籤="三層在這個 repo 的落點",
    ),
    規範登記(
        "宣告:8",
        規範狀態.還是懇求,
        "Graph 層暫不建立的條件尚未有獨立閘。",
        標籤="Graph 層現在故意不存在。",
    ),
    規範登記(
        "標題:2:5",
        規範狀態.已成閘,
        "規範涵蓋與證據引用由本同步閘檢查。",
        閘代碼="claude-location",
        標籤="判準：保證住在哪",
    ),
    規範登記(
        "宣告:9",
        規範狀態.已成閘,
        "每條文件規範現在都必須出現在 typed 登記。",
        閘代碼="claude-location",
        標籤="只以文件或 skill 形式存在的規範等於不存在。",
    ),
    規範登記(
        "宣告:10",
        規範狀態.已成閘,
        "自動保證的閘代碼與測試背書由本同步閘檢查。",
        閘代碼="claude-location",
        標籤="文件若宣稱某件事「會被自動擋下」，把關器就必須存在且有測試背書。",
    ),
    規範登記(
        "宣告:11",
        規範狀態.搬不動,
        "真 CLI 的認證、額度、網路與 token 消耗不在本機 oracle 內。",
        替代方案=("用隔離帳號的 scheduled canary 留下環境與時間戳；人工驗收期限 2026-09-30。"),
        到期日="2026-09-30",
        標籤="墊片證明的是轉遞形狀，不是可達性。",
    ),
    規範登記(
        "宣告:12",
        規範狀態.還是懇求,
        "不以規避換綠尚未有完整的獨立判定器。",
        標籤="用規避換來的綠是假綠。",
    ),
    規範登記(
        "標題:2:6",
        規範狀態.有測試背書,
        "專案歸屬與存放位置已有跨專案驗收。",
        測試nodeid="tests/整合/test_命令列.py::Test帳本按專案分::test_在不同專案跑會指向不同目錄",
        標籤="載體的狀態住哪：歸屬與完整性是兩條軸",
    ),
    規範登記(
        "宣告:13",
        規範狀態.有測試背書,
        "帳本落點不進專案已有驗收測試。",
        測試nodeid="tests/整合/test_命令列.py::Test帳本按專案分::test_落點不在專案裡面",
        標籤="「屬於某個專案」跟「存在那個專案裡面」是兩件事。",
    ),
    規範登記(
        "宣告:14",
        規範狀態.有測試背書,
        "進度檔落在工作目錄會被 CLI 驗收擋下。",
        測試nodeid="tests/整合/test_命令列.py::Test進度檔在工作目錄裡要被擋下來::test_CLI要真的擋",
        標籤="會被餵回模型的東西，執行者不准碰。",
    ),
    規範登記(
        "宣告:15",
        規範狀態.有測試背書,
        "不同專案的索引鍵已有跨專案驗收。",
        測試nodeid="tests/整合/test_命令列.py::Test帳本按專案分::test_在不同專案跑會指向不同目錄",
        標籤="只給人看的東西，要按專案分。",
    ),
    規範登記(
        "標題:2:7",
        規範狀態.還是懇求,
        "硬規則各自的執法點尚未全部登記。",
        標籤="硬規則",
    ),
    規範登記(
        "宣告:16",
        規範狀態.還是懇求,
        "外部規格原文不可改尚未有專門的變異驗證。",
        標籤="`docs/AGENT_ARCHITECTURE.md` 是外部規格原文，一個字都不准改。",
    ),
    規範登記(
        "宣告:17",
        規範狀態.還是懇求,
        "停止條件不可由模型宣稱尚未有完整的機械判準。",
        標籤="不得以「模型說完成了」當停止條件",
    ),
    規範登記(
        "宣告:18",
        規範狀態.還是懇求,
        "診斷順序尚未有能決定每一層的單一閘。",
        標籤="診斷順序：環境 → 回饋 → 流程。",
    ),
    規範登記(
        "宣告:19",
        規範狀態.已成閘,
        "固定負控已由 CI 的 registered-mutation 執行。",
        閘代碼="registered-mutation",
        標籤="新增保證要做一次固定負控",
    ),
    規範登記(
        "標題:2:8",
        規範狀態.有測試背書,
        "退出碼的四種語意已有整合測試。",
        測試nodeid="tests/整合/test_命令列.py::Test工作流的退出碼要分得出護欄與壞掉::test_四個碼互不相同",
        標籤="退出碼有四種語意",
    ),
    規範登記(
        "宣告:20",
        規範狀態.有測試背書,
        "四個退出碼必須互異已有整合測試。",
        測試nodeid="tests/整合/test_命令列.py::Test工作流的退出碼要分得出護欄與壞掉::test_四個碼互不相同",
        標籤="0 成功、1 確定失敗、3 結果未知、4 護欄生效",
    ),
    規範登記(
        "宣告:21",
        規範狀態.有測試背書,
        "護欄與壞掉的收場已有四碼整合測試。",
        測試nodeid="tests/整合/test_命令列.py::Test工作流的退出碼要分得出護欄與壞掉::test_四種收場四個碼",
        標籤="4 不是壞了",
    ),
    規範登記(
        "宣告:22",
        規範狀態.有測試背書,
        "結果未知蓋過其他收場已有整合測試。",
        測試nodeid="tests/整合/test_命令列.py::Test工作流的退出碼要分得出護欄與壞掉::test_結果未知蓋過一切",
        標籤="3 是「不知道工作做了沒」",
    ),
    規範登記(
        "標題:2:9",
        規範狀態.有測試背書,
        "設計文件連結已有文件存在性驗收。",
        測試nodeid="tests/驗收/test_文件即事實.py::test_文件提到的檔案都真的存在",
        標籤="設計文件在哪",
    ),
    規範登記(
        "宣告:23",
        規範狀態.有測試背書,
        "各家載體最小化已有模型轉接測試。",
        測試nodeid="tests/整合/test_模型轉接.py::Test把各家載體關到最小::test_claude關掉工具與家目錄設定",
        標籤="各家自帶的載體一律關到最小",
    ),
    規範登記(
        "宣告:24",
        規範狀態.還是懇求,
        "旗標與型號的單一文件來源尚未有同步閘。",
        標籤="旗標與型號全在 02，不要抄一份到這裡。",
    ),
)


def _收集測試nodeid(根目錄: Path) -> tuple[bool, set[str], str]:
    """用 pytest collection 取得真的存在的 nodeid；這層不做判斷。"""
    try:
        結果 = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:randomly", "--collect-only", "-q"],
            cwd=根目錄,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as 錯:
        return False, set(), f"pytest collection 失敗：{錯}"
    if 結果.returncode != 0:
        return False, set(), f"pytest collection 失敗：{結果.stdout}{結果.stderr}".strip()
    nodeid們 = {行.strip() for 行 in 結果.stdout.splitlines() if _nodeid模式.fullmatch(行.strip())}
    return True, nodeid們, ""


def 檢查規範落點(根目錄: Path, 閘代碼們: Collection[str]) -> tuple[bool, str]:
    """讀取本 repo 的 CLAUDE.md，執行同步檢查。"""
    try:
        規範全文 = (根目錄 / "CLAUDE.md").read_text(encoding="utf-8")
    except OSError as 錯:
        return False, f"讀取 CLAUDE.md 失敗：{錯}"
    nodeid收集成功, 測試nodeid們, nodeid收集錯誤 = _收集測試nodeid(根目錄)
    if not nodeid收集成功:
        return False, nodeid收集錯誤
    return 檢查文件與登記(規範全文, 規範登記表, 閘代碼們, 測試nodeid們)

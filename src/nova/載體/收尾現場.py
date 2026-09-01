"""收尾現場查詢與結果正規化。

把 `git`／`gh` 子程序的自由文字輸出正規化成私有、不可變的收尾快照：
- 狀態只做「觀測」，未知值落到 UNKNOWN，不冒充任何可合併狀態；
- PR 身分靠分支名唯一比對，比不出唯一目標就回未知碼 3 停止，
  未知之後不發任何會改遠端的指令；
- 所有命令一律以 argv list 執行，不經過 shell 字串。
"""

from __future__ import annotations

import dataclasses
import enum
import json
import subprocess
from pathlib import Path

from nova.契約.退出碼 import 放行, 未知, 護欄碼, 閘紅

_要的欄位: tuple[str, ...] = (
    "number",
    "url",
    "headRefName",
    "headRefOid",
    "baseRefName",
    "mergeStateStatus",
)
"""向 `gh --json` 指名的欄位；查編號與查資料共用同一份，兩邊才不會各自漂移。"""

_必備字串欄位: tuple[str, ...] = (
    "url",
    "headRefName",
    "headRefOid",
    "baseRefName",
    "mergeStateStatus",
)
"""少任何一欄就不能證明目標；`number` 不在此列是因為它是整數，另外驗型別。"""


class 收尾狀態(enum.Enum):
    """`gh` 觀測到的 PR 狀態；值必須是 ASCII，跨程序傳遞不跑調。"""

    DIRTY = "DIRTY"
    BEHIND = "BEHIND"
    CLEAN = "CLEAN"
    BLOCKED = "BLOCKED"
    UNSTABLE = "UNSTABLE"
    DRAFT = "DRAFT"
    UNKNOWN = "UNKNOWN"


@dataclasses.dataclass(frozen=True)
class 收尾指令結果:
    """一條以 argv list 執行的子程序的不可變結果。"""

    argv: tuple[str, ...]
    退出碼: int
    stdout: str
    stderr: str
    逾時: bool
    子程序退出碼: int | None = None
    """子程序的原始退出碼；逾時或工具不存在時沒有原始碼，留 None。"""


@dataclasses.dataclass(frozen=True)
class 收尾快照:
    """一次收尾現場查詢的不可變快照；查不到時各欄留空、狀態為 UNKNOWN。"""

    PR編號: int = 0
    PR網址: str = ""
    head分支: str = ""
    head_sha: str = ""
    base分支: str = ""
    狀態: 收尾狀態 = 收尾狀態.UNKNOWN
    退出碼: int = 未知
    證據: str = ""
    目標已證明: bool = False


def _未知結果(指令: tuple[str, ...], *, stderr: str, 逾時: bool) -> 收尾指令結果:
    """指令沒能跑到有意義的結束（逾時、工具不存在）時的統一出口：未知碼、不准重跑。"""
    return 收尾指令結果(argv=tuple(指令), 退出碼=未知, stdout="", stderr=stderr, 逾時=逾時)


def 跑收尾指令(根目錄: Path, *指令: str, 逾時秒: float | None = None) -> 收尾指令結果:
    """以 argv list（不走 shell）執行一條收尾子程序。

    退出碼契約：成功回 0（放行）；已知命令確定失敗回 1（閘紅）；
    工具不存在或逾時回 3（未知），外圈不准重跑。
    """
    try:
        完成 = subprocess.run(  # noqa: S603 —— 參數由收尾節點組成，走 argv list
            指令,
            cwd=根目錄,
            capture_output=True,
            text=True,
            timeout=逾時秒,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _未知結果(指令, stderr=f"逾時（>{逾時秒} 秒）", 逾時=True)
    except FileNotFoundError as 錯誤:
        return _未知結果(指令, stderr=f"找不到指令：{錯誤}", 逾時=False)
    return 收尾指令結果(
        argv=tuple(指令),
        退出碼=放行 if 完成.returncode == 0 else 閘紅,
        stdout=完成.stdout,
        stderr=完成.stderr,
        逾時=False,
        子程序退出碼=完成.returncode,
    )


def _未知快照(分支: str, 原因: str) -> 收尾快照:
    """查不到或不能證明時的統一出口：未知狀態、未知碼、寫明「目前不知道」。"""
    return 收尾快照(
        head分支=分支,
        狀態=收尾狀態.UNKNOWN,
        退出碼=未知,
        證據=f"目前不知道：{原因}",
    )


def _觀測狀態(原始值: str) -> 收尾狀態:
    """把 `mergeStateStatus` 字串觀測成收尾狀態；未定義的字串只落 UNKNOWN。"""
    try:
        return 收尾狀態(原始值)
    except ValueError:
        return 收尾狀態.UNKNOWN


def _查gh(根目錄: Path, *指令: str, 逾時秒: float | None, 來源: str) -> tuple[object, str]:
    """跑一條 gh 查詢並把 stdout 解析成 JSON。

    回傳「解析結果、失敗原因」；原因非空才代表失敗——查詢本身可能合法地回 JSON null，
    所以不能拿解析結果是不是 None 當成敗判準。
    """
    結果 = 跑收尾指令(根目錄, *指令, 逾時秒=逾時秒)
    if 結果.退出碼 != 放行:
        return None, f"{來源} 查不到（退出碼 {結果.退出碼}）：{結果.stderr.strip()}"
    try:
        解析後: object = json.loads(結果.stdout)
    except json.JSONDecodeError:
        return None, f"{來源} 回傳壞 JSON：{結果.stdout.strip()[:120]}"
    return 解析後, ""


def _攤成PR候選(原始: object) -> list[dict[str, object]]:
    """把 gh 的回傳攤成 PR 候選清單。

    `gh pr list` 可能回陣列，也可能回單一物件；其餘型別一律視為沒有候選，
    寧可比不到而停在未知，也不猜。
    """
    if isinstance(原始, dict):
        項目: list[object] = [原始]
    elif isinstance(原始, list):
        項目 = list(原始)
    else:
        項目 = []
    return [項 for 項 in 項目 if isinstance(項, dict)]


def _查PR編號(根目錄: Path, 分支: str, 逾時秒: float | None) -> tuple[int | None, str]:
    """向 gh pr list 依分支名唯一比對 PR 編號。"""
    原始, 原因 = _查gh(
        根目錄,
        "gh",
        "pr",
        "list",
        "--json",
        ",".join(_要的欄位),
        逾時秒=逾時秒,
        來源="gh pr list",
    )
    if 原因:
        return None, 原因
    匹配 = [pr for pr in _攤成PR候選(原始) if pr.get("headRefName") == 分支]
    if len(匹配) != 1:
        return None, f"比不到唯一對應該分支的開啟 PR（比到 {len(匹配)} 筆），不猜"
    編號 = 匹配[0].get("number")
    if not isinstance(編號, int):
        return None, "比到的 PR 沒有 number 欄位"
    return 編號, ""


def _查PR資料(根目錄: Path, 編號: int, 逾時秒: float | None) -> tuple[dict[str, str] | None, str]:
    """向 gh pr view 取得目標 PR 的結構化欄位。"""
    資料, 原因 = _查gh(
        根目錄,
        "gh",
        "pr",
        "view",
        str(編號),
        "--json",
        ",".join(_要的欄位),
        逾時秒=逾時秒,
        來源="gh pr view",
    )
    if 原因:
        return None, 原因
    if not isinstance(資料, dict):
        return None, "gh pr view 回傳的不是物件"
    for 欄 in _必備字串欄位:
        if not isinstance(資料.get(欄), str):
            return None, f"gh pr view 缺欄位 {欄}"
    return {欄: str(資料[欄]) for 欄 in _必備字串欄位}, ""


def _由PR資料組快照(
    編號: int,
    資料: dict[str, str],
    *,
    狀態: 收尾狀態,
    退出碼: int,
    證據: str,
) -> 收尾快照:
    """把查到的 PR 身分欄位固定成快照；只有狀態、退出碼與證據隨判讀不同。"""
    return 收尾快照(
        PR編號=編號,
        PR網址=資料["url"],
        head分支=資料["headRefName"],
        head_sha=資料["headRefOid"],
        base分支=資料["baseRefName"],
        狀態=狀態,
        退出碼=退出碼,
        證據=證據,
    )


def _解析PR目標(PR目標: int | str) -> int | None:
    """把 PR 編號或 PR URL 解析成編號；解析不出來就回 None，不猜。"""
    尾段 = str(PR目標).rstrip("/").rsplit("/", 1)[-1]
    數字 = "".join(字 for 字 in 尾段 if 字.isdigit())
    return int(數字) if 數字 else None


def 查收尾現場(  # noqa: PLR0913 六個參數都是查詢邊界的一部分，拆開反而要多一層搬運物件
    根目錄: Path,
    *,
    分支: str,
    PR目標: int | str | None = None,
    HEAD_SHA: str = "",
    逾時秒: float | None = None,
    要求可合併: bool = False,
) -> 收尾快照:
    """查詢收尾現場並正規化成不可變快照。

    有明確 `PR目標`（編號或 URL）就直接 view 它，不先列清單挑第一筆；
    沒有就靠分支名唯一比對。給了 `HEAD_SHA` 時還要求查到的 headRefOid 與之相符，
    比不出唯一目標、資料壞或缺欄、狀態未定義、SHA 不符時一律回未知碼 3 停止，
    之後不發任何改遠端的指令。
    """
    if PR目標 is not None:
        編號 = _解析PR目標(PR目標)
        錯誤 = f"認不出 PR 目標「{PR目標}」的編號"
    else:
        編號, 錯誤 = _查PR編號(根目錄, 分支, 逾時秒)
    if 編號 is None:
        return _未知快照(分支, 錯誤)

    資料, 錯誤 = _查PR資料(根目錄, 編號, 逾時秒)
    if 資料 is None:
        return _未知快照(分支, 錯誤)

    目標已證明 = bool(HEAD_SHA) and 資料["headRefOid"] == HEAD_SHA
    if HEAD_SHA and not 目標已證明:
        return _由PR資料組快照(
            編號,
            資料,
            狀態=收尾狀態.UNKNOWN,
            退出碼=未知,
            證據=(
                f"目前不知道：PR 的 headRefOid「{資料['headRefOid']}」"
                f"不是本次工作樹的 HEAD「{HEAD_SHA}」，證明不了目標"
            ),
        )

    狀態原始 = 資料["mergeStateStatus"]
    狀態 = _觀測狀態(狀態原始)
    if 狀態 is 收尾狀態.UNKNOWN:
        return _由PR資料組快照(
            編號,
            資料,
            狀態=收尾狀態.UNKNOWN,
            退出碼=未知,
            證據=f"目前不知道：未定義的 mergeStateStatus「{狀態原始}」",
        )
    if 要求可合併 and 狀態 is not 收尾狀態.CLEAN:
        return _由PR資料組快照(
            編號,
            資料,
            狀態=狀態,
            退出碼=護欄碼,
            證據=f"要求可合併但觀測到 {狀態.value}，安全前置不滿足",
        )
    快照 = _由PR資料組快照(
        編號,
        資料,
        狀態=狀態,
        退出碼=放行,
        證據=f"mergeStateStatus={狀態原始}",
    )
    return dataclasses.replace(快照, 目標已證明=目標已證明)

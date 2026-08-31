"""nova 的命令列介面：所有執行點唯一的入口。

pre-commit、CI、agent 的 hook 全部呼叫這裡的同一支程式，所以換模型、換工具，
受到的約束完全一樣。設定檔裡只准放一行呼叫，不准塞邏輯——設定檔沒辦法測試。

退出碼：0 放行／成功、1 閘紅／確定失敗、2 阻擋（agent hook 的約定）、3 結果未知。
"""

import argparse
import contextlib
import dataclasses
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from nova import 家族額度, 額度
from nova.契約.工作流 import (
    任務,
    停止條件,
    執行器,
    步驟結果,
    結束,
    結束代碼,
    階段代碼,
    階段定義,
    預設單次最多token,
)
from nova.契約.帳本 import 一條規則的帳, 摘要
from nova.契約.成果 import 成果
from nova.契約.模型回應 import 回應, 終局
from nova.契約.檢查結果 import 檢查結果
from nova.契約.派工 import 工作種類, 派法
from nova.契約.角色 import 呼叫選項, 權限, 角色, 語言模型
from nova.契約.觸發 import 喚醒來源
from nova.載體.git查詢 import 目前commit
from nova.載體.判準 import 判準指令, 建判準, 建重構判準
from nova.載體.剖析器 import 建剖析器, 處理型
from nova.載體.單例 import 只准一個, 拿不到鎖
from nova.載體.專案脈絡 import 專案執行脈絡, 建專案執行脈絡
from nova.載體.已處理 import 列出成果, 歸檔
from nova.載體.帳本 import (
    不記帳本,
    專案識別,
    帳本,
    指定識別碼的環境變數,
    新執行識別碼,
    開帳本,
)
from nova.載體.帳本讀取 import 列出執行, 統計規則, 讀一次執行, 讀原始事件, 還在跑的有哪些
from nova.載體.排程 import 啟動器名, 怎麼跑, 排程標籤, 排程設定, 排程預算, 確保啟動器在
from nova.載體.提示來源 import 提示走錯路, 讀提示
from nova.載體.收件 import (
    丟一件,
    你敲,
    完成一件,
    待處理,
    接著排,
    收下一件,
    收件單,
    最多輪次,
)
from nova.載體.模型.接力 import 接力腦
from nova.載體.模型.本地 import 審查資格理由
from nova.載體.模型.記帳 import 記帳每一顆
from nova.載體.模型.轉接 import 家族, 建立或缺席
from nova.載體.殘骸 import 加上寫檔指示, 撿回殘骸
from nova.載體.派工表 import 怎麼派
from nova.載體.熔斷 import 該跳過嗎
from nova.載體.狀態 import 狀態根目錄
from nova.載體.狀態檔 import (
    做完了,
    出不了生,
    在忙,
    寫下現況,
    形容,
    沒事做,
    狀態檔,
    現在幾點,
    現況,
    被預算擋,
    讀現況,
)
from nova.載體.生圖 import 生圖, 生圖選項, 生圖那家
from nova.載體.禁令 import 檢查指令
from nova.載體.秘密 import 看不懂的祕密檔, 祕密檔, 載入到
from nova.載體.線 import 執行線
from nova.載體.自己動手 import 在管轄範圍嗎, 擋的話要說什麼, 記下繞過, 說得出理由了嗎
from nova.載體.規則表 import 建規則表
from nova.載體.規則表 import 版本 as 規則表版本
from nova.載體.角色 import 組提示
from nova.載體.語言 import 找非繁體字
from nova.載體.跑驗收 import 跑驗收
from nova.載體.進度 import 一步上限, 檢查進度檔位置, 讀進度, 進度執行器
from nova.載體.遮罩 import 遮罩
from nova.載體.重構護欄 import 動到測試了嗎, 拍全樹快照, 拍快照, 跑出範圍了嗎
from nova.載體.閘 import 跑閘
from nova.載體.閘紅成票 import 落成閘紅票們
from nova.載體.閘鎖 import 佔不到, 佔住
from nova.載體.階段記帳 import 記帳執行器
from nova.載體.預算 import 上限, 花了多少, 超支了嗎
from nova.迴圈 import 角色提示
from nova.迴圈.工作流 import 建TDD執行器, 工作流結果, 跑工作流
from nova.迴圈.角色工廠 import TDD角色藍圖 as TDD角色藍圖資料
from nova.迴圈.角色工廠 import 建角色表, 角色藍圖

放行, 閘紅, 阻擋 = 0, 1, 2
#: 護欄生效：**按設計停了，不是壞了。** 外圈看到這個碼不准去「修」——
#: 護欄最省事的修法是把上限調高，那是自己拆執法點。要放寬是人的決定。
護欄碼 = 4
# 結果未知要跟確定失敗分開，腳本才知道「這個不准重跑」。
未知 = 3
_終局的退出碼 = {終局.成功: 放行, 終局.確定失敗: 閘紅, 終局.結果未知: 未知}


def _專案脈絡(參數: argparse.Namespace) -> 專案執行脈絡:
    """同一個 CLI 參數只建立一次專案執行脈絡。"""
    脈絡 = getattr(參數, "專案脈絡", None)
    if isinstance(脈絡, 專案執行脈絡):
        return 脈絡
    工作目錄 = getattr(參數, "工作目錄", None) or getattr(參數, "根目錄", None)
    脈絡 = 建專案執行脈絡(工作目錄)
    參數.專案脈絡 = 脈絡
    return 脈絡


@dataclasses.dataclass(slots=True)
class _醒來:
    """這一次醒來發生了什麼。**由各個出口自己填，不從退出碼反推。**

    反推不出來：`0` 同時是「做完了」「收件匣是空的」「撞到鎖讓開」，
    而那三件正是最需要分開的三件——「排程壞掉了」跟「排程好好的但沒事做」
    在退出碼上長得一模一樣。
    """

    結果: str = 做完了
    理由: str = ""
    執行識別碼: str = ""


#: 閘紅時印幾行證據。**頭尾都要留**：頭是規則自己的開場（哪個工具、跑了什麼），
#: 尾是失敗細節與摘要。中間那一大段（pytest 的進度點）才是可以丟的。
_印開頭幾行 = 3
_印結尾幾行 = 40


def _證據挑幾行(證據: str) -> list[str]:
    """從證據挑幾行印。太長就砍中間，**頭尾都留**。

    **原本是 `[:20]`，而那等於永遠印不出失敗細節**：pytest 的前 20 行是
    `bringing up nodes` 與進度點，FAILURES 段在它們後面。
    實測 2026-08-31：PR #184 的 CI 紅了，日誌裡只看得到進度點停在 73%，
    一個失敗的測試名都沒有——「CI 為什麼紅」查不出來，只能重跑碰運氣。

    不印全部是因為 `_截斷證據` 已經把證據壓在 20000 字元（約 250 行）以內，
    整份印出來會洗掉前面幾條規則的結果；而閘紅時最需要看的是
    「哪一條紅」加「為什麼」。

    **省略要明講省了幾行。** 靜默省略等於騙人：看起來像完整輸出，
    其實中間缺了一段。
    """
    行們 = 證據.splitlines()
    if len(行們) <= _印開頭幾行 + _印結尾幾行:
        return 行們
    省了 = len(行們) - _印開頭幾行 - _印結尾幾行
    return [
        *行們[:_印開頭幾行],
        f"……（中間省略 {省了} 行，多半是進度點；完整證據在收件票與帳本裡）",
        *行們[-_印結尾幾行:],
    ]


def _印結果(結果表: list[檢查結果]) -> int:
    for 結果 in 結果表:
        記號 = "綠" if 結果.通過 else "紅"
        print(f"[{記號}] {結果.代碼:<16} {結果.名稱}")
        if not 結果.通過:
            print(f"       負責層：{結果.負責層}")
            for 行 in _證據挑幾行(結果.證據):
                print(f"       {行}")
    紅的 = [結果.代碼 for 結果 in 結果表 if not 結果.通過]
    if 紅的:
        print(f"\n閘紅：{'、'.join(紅的)}", file=sys.stderr)
        return 閘紅
    print(f"\n全部通過（{len(結果表)} 條）")
    return 放行


def _子命令_閘(參數: argparse.Namespace) -> int:
    根目錄 = _專案脈絡(參數).根目錄
    try:
        # **佔住整台機器再跑。** 三個 nova 各自開一個閘的話，三份 pytest
        # 同時吃滿 CPU，而負控執行器對每把刀的 `最多秒` 是 2.0——
        # 跑不完就被殺，判成「這把刀沒被殺掉」。那是假紅，而假紅的下一步
        # 通常是有人去把那支好好的測試「修好」。
        with 佔住("閘"), _開帳(參數) as 帳:
            結果表 = 跑閘(參數.閘點, 建規則表(根目錄), 提前停止=not 參數.全部跑完, 帳=帳)
    except 佔不到 as 錯:
        # **不是閘紅，是閘沒跑。** 回 3（結果未知）才不會讓「機器很忙」
        # 長得跟「程式壞了」一樣——而 3 的意思正是「不知道做了沒」。
        print(str(錯), file=sys.stderr)
        return 未知
    except ValueError as 錯:
        print(str(錯), file=sys.stderr)
        return 閘紅
    落成閘紅票們(
        結果表,
        閘點=參數.閘點,
        喚醒來源=參數.喚醒來源,
        專案=根目錄,
    )
    return _印結果(結果表)


def _取出指令(參數: argparse.Namespace) -> tuple[str | None, str, str]:
    """回傳 (要檢查的指令, 會話識別碼, 錯誤訊息)。指令是 None 代表沒有東西要檢查。

    **會話識別碼要一起帶出來**：擋下來的訊息要告訴人怎麼記繞過理由，
    而那句話裡的 `--會話` 填佔位符等於沒給——照抄會失敗，
    而且佔位符含角括號的話，照抄下來執行還會被護欄自己擋掉。
    """
    if not 參數.stdin:
        return " ".join(參數.命令), "", ""
    try:
        載荷 = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as 錯:
        return None, "", f"stdin 不是合法 JSON（{錯}）——讀不懂就不放行"
    工具輸入 = 載荷.get("tool_input") or 載荷
    指令 = 工具輸入.get("command")
    會話 = 載荷.get("session_id")
    return (
        指令 if isinstance(指令, str) else None,
        會話 if isinstance(會話, str) else "",
        "",
    )


def _子命令_檢查指令(參數: argparse.Namespace) -> int:
    指令, 會話, 錯誤 = _取出指令(參數)
    if 錯誤:
        print(錯誤, file=sys.stderr)
        return 阻擋
    if not 指令:
        return 放行
    專案 = _專案脈絡(參數).根目錄
    通過, 原因 = 檢查指令(指令, 專案=專案, 會話=會話)
    if 通過:
        return 放行
    print(f"nova 阻擋：{原因}", file=sys.stderr)
    return 阻擋


def _該擋的理由(載荷: object) -> str | None:
    """要擋就回訊息，不擋回 None。**看不懂的一律回 None（放行）。**

    跟 `檢查指令` 剛好相反，而且是刻意的：那一支守的是不可逆的動作
    （繞過閘門、跳過 required check），讀不懂就該 fail-closed；
    這一支守的是一個**預設值**，而它掛在 Edit／Write 上——
    **修 nova 的唯一辦法就是編輯 nova 的檔案。**
    """
    if not isinstance(載荷, dict):
        return None
    工具輸入 = 載荷.get("tool_input")
    檔 = 工具輸入.get("file_path") if isinstance(工具輸入, dict) else None
    if not isinstance(檔, str) or not 檔:
        return None
    專案 = 建專案執行脈絡().根目錄
    if not 在管轄範圍嗎(Path(檔), 根目錄=專案):
        return None
    會話 = 載荷.get("session_id")
    # 沒有 session id 就說不出那行指令給人照抄，擋了也沒用——放行。
    if not isinstance(會話, str) or not 會話:
        return None
    if 說得出理由了嗎(會話, 專案=專案):
        return None
    return 擋的話要說什麼(會話)


def _子命令_檢查編輯(參數: argparse.Namespace) -> int:
    """agent hook 問「這個編輯可以嗎」。**退出碼永遠是 0。**

    擋不擋看的是**有沒有印出那段 JSON**，不是退出碼——`uv run` 自己失敗時
    也會回非零，跟「故意擋下」在退出碼上分不開，於是 nova 一壞
    （import 錯、venv 沒建好）就變成全部編輯都擋住，而那時候
    **修 nova 需要的正是編輯**。今晚真的踩過兩次（那次掛在 Bash 上，
    還能用 Edit 逃出來；這一支掛在 Edit 上，沒有逃生口）。
    """
    del 參數
    try:
        擋 = _該擋的理由(json.load(sys.stdin))
    except Exception as 錯:  # noqa: BLE001 —— 保證就是「絕不因為自己爆掉而擋住編輯」
        print(f"nova 檢查編輯自己出錯了，放行：{錯}", file=sys.stderr)
        return 放行
    if 擋 is not None:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": 擋,
                    }
                },
                ensure_ascii=False,
            )
        )
    return 放行


def _子命令_繞過(參數: argparse.Namespace) -> int:
    """記下「這次為什麼自己動手」。**理由才是這條規則真正的產出。**"""
    try:
        落點 = 記下繞過(參數.會話, 參數.因為, 專案=_專案脈絡(參數).根目錄)
    except ValueError as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    print(f"記下來了：{落點}")
    return 放行


def _子命令_檢查提交訊息(參數: argparse.Namespace) -> int:
    文字 = Path(參數.檔案).read_text(encoding="utf-8")
    命中 = 找非繁體字(文字)
    if not 命中:
        return 放行
    for 行號, 字, 整行 in 命中:
        print(f"commit 訊息第 {行號} 行出現「{字}」：{整行.strip()}", file=sys.stderr)
    print("commit 訊息一律繁體中文（CLAUDE.md 最高原則二）", file=sys.stderr)
    return 閘紅


def _摘要(家: str, 答: 回應) -> str:
    """一行給人看的結果。放 stderr，stdout 留給模型講的話，才能直接 pipe。"""
    用 = 答.用量
    量 = f"{用.輸入token}→{用.輸出token} token"
    if 用.成本美金 is not None:
        量 += f" · US${用.成本美金:.4f}"
    對話 = f" · sid {答.對話識別碼}" if 答.對話識別碼 else ""
    if 答.終局 is 終局.成功:
        return f"[{家}] 完成 · {量}{對話}"
    如何 = "確定失敗" if 答.終局 is 終局.確定失敗 else "結果未知（不准自動重跑）"
    return f"[{家}] {如何} {答.失敗代碼}（結束碼 {答.原始結束碼}）· {量}{對話}"


@dataclasses.dataclass(frozen=True, slots=True)
class _要問的東西:
    """前置檢查全部過了之後，這次要打出去的東西。"""

    提示: str
    用: str
    模: str | None
    思考深度: str | None
    可以做什麼: 權限
    屍: Path | None


def _問的提示(參數: argparse.Namespace) -> str | int:
    """這次要問什麼。**回 int ＝ 問不出來，那個數字就是退出碼。**

    抽出來是因為 ruff `PLR0911`（回傳點太多），而那條規則說的是對的：
    `_問的前置` 一次要管三件事（讀題目、挑腦、備權限），每件都有自己的
    失敗出口。讀題目自成一件，拆出來就少三個出口。
    """
    try:
        提示 = 讀提示(argv片段=參數.提示, 提示檔=參數.提示檔)
    except (提示走錯路, OSError) as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    if not 提示.strip():
        print("沒有提示可以問（用參數給、--提示檔、或從 stdin 餵）", file=sys.stderr)
        return 阻擋
    return 提示


def _問的前置(參數: argparse.Namespace) -> _要問的東西 | int:
    """打出去之前要檢查與準備的全部。**回 int ＝ 別打了，那個數字就是退出碼。**

    抽出來不只為了 C901——「檢查與準備」跟「打出去並回報」是兩件事，
    而且**只有這一段有權力讓那個請求不要發生**。
    """
    提示 = _問的提示(參數)
    if isinstance(提示, int):
        return 提示
    挑法 = _挑腦(參數)
    if 挑法 is None:
        return 阻擋
    沒憑證 = _秘密先交出去(_專案脈絡(參數).根目錄)
    if 沒憑證 is not None:
        return 沒憑證
    擋 = _預算先擋一下(參數)
    if 擋 is not None:
        return 擋
    可以做什麼 = _挑權限(參數)
    屍 = Path(參數.輸出檔) if 參數.輸出檔 else None
    if 屍 is not None:
        if 可以做什麼 is 權限.唯讀:
            print("--輸出檔 要它寫檔，就得給 --可編輯（或 --全開）", file=sys.stderr)
            return 阻擋
        提示 = 加上寫檔指示(提示, 屍)
    用, 模, 深度 = 挑法
    return _要問的東西(提示=提示, 用=用, 模=模, 思考深度=深度, 可以做什麼=可以做什麼, 屍=屍)


#: 背景輸出放哪。跟帳本、收件匣同一個專案資料夾——住專案外面、用專案當鍵。
_背景資料夾 = "背景"


def _丟到背景(參數: argparse.Namespace) -> int:
    """把同一條指令重新發射成一個獨立的背景程序，立刻回。

    **背景化要內聚在 nova 自己，不能靠外面的殼。** 2026-08-30 我用
    `nohup uv run nova 問 … &` 派了兩份研究，使用者的介面上什麼都看不到；
    我的修法是「以後改用 harness 的背景任務功能」——**那是懇求**，
    而且那個功能是 Claude Code 的，換一個 harness 就整個消失。

    重新發射走 `sys.argv`（真實命令列）而不是重組參數：重組會漏掉旗標，
    而漏掉的那次剛好就是最難查的那次。
    """
    參 = [格 for 格 in sys.argv[1:] if 格 != "--背景"]
    if len(參) == len(sys.argv[1:]):
        print("--背景 只能從命令列用（重新發射靠的是 sys.argv）", file=sys.stderr)
        return 阻擋
    落點目錄 = 狀態根目錄() / "專案" / 專案識別(_專案脈絡(參數).根目錄) / _背景資料夾
    落點目錄.mkdir(parents=True, exist_ok=True)
    # **一件事只准有一個號碼。** 這裡編一個、帳本另外編一個的話，
    # 使用者拿到的識別碼在 `nova 帳本` 上查不到——而那看起來像「帳沒記」。
    識別 = 新執行識別碼()
    落點 = 落點目錄 / f"{識別}.md"
    with 落點.open("x", encoding="utf-8") as 手:
        subprocess.Popen(  # noqa: S603 —— 就是這支自己，參數原封不動
            [sys.executable, "-m", "nova", *參],
            stdout=手,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # 父程序結束不會把它一起帶走
            cwd=Path.cwd(),
            env={**os.environ, 指定識別碼的環境變數: 識別},
        )
    print(f"丟到背景了。識別碼：{識別}")
    print(f"輸出寫在：{落點}")
    print("看還在跑什麼：nova 狀態")
    return 放行


def _子命令_問(參數: argparse.Namespace, *, 角色: str = "") -> int:
    """把一件事委派給別家 LLM CLI。

    這是統一介面的第一個真實呼叫端——用 codex／agy 接手工作，
    分擔 Claude 的壓力與使用額度。

    `角色` 是**單節點子命令**用的：`nova 重構` 就是這條路前面加一段角色提示
    （見 `docs/設計/07-節點是一等公民.md`：CLI 是薄適配器）。
    **不另開一條委派路徑**——各自包一套 prompt／預算／終局的話，
    `--預算token` 這種護欄遲早只剩一邊有。
    """
    if 參數.背景:
        return _丟到背景(參數)
    這次 = _問的前置(參數)
    if isinstance(這次, int):
        return 這次
    if 角色:
        這次 = dataclasses.replace(這次, 提示=組提示(角色, 這次.提示))
    try:
        with _開帳(參數) as 帳:
            答 = _建腦(
                這次.用,
                Path(參數.執行檔) if 參數.執行檔 else None,
                帳,
                熔斷了=_這個專案誰熔斷了(_帳本目錄(參數), 啟用=參數.熔斷),
                記全文=not 參數.不記全文,
            ).詢問(
                這次.提示,
                選項=呼叫選項(
                    模型=這次.模,
                    思考深度=這次.思考深度,
                    工作目錄=_專案脈絡(參數).根目錄,
                    逾時秒=參數.逾時,
                    權限=這次.可以做什麼,
                    隔離設定=not 參數.不隔離設定,
                    續接=參數.續接,
                    保留對話=參數.保留對話 or bool(參數.續接),
                ),
            )
    except (ValueError, FileNotFoundError) as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    if 這次.屍 is not None:
        答 = 撿回殘骸(答, 這次.屍)
    if 參數.json:
        # 原始輸出是行程內的逃生艙，不往 CLI 吐——它可能有上千行事件。
        證據 = {鍵: 值 for 鍵, 值 in dataclasses.asdict(答).items() if 鍵 != "原始輸出"}
        print(json.dumps(證據, ensure_ascii=False, indent=2))
    else:
        print(答.文字)
    print(_摘要(這次.用, 答), file=sys.stderr)
    return _終局的退出碼[答.終局]


def _子命令_重構(參數: argparse.Namespace) -> int:
    """單獨叫重構員這一個節點。**動到測試檔就回護欄（4）。**

    ## 為什麼要有它

    在它存在之前，要重構只有兩條路：跑整條 TDD 七階段（貴、慢，而且
    表達不了「只整理這個模組」），或者自己動手。**第二條便宜一個數量級**，
    所以護欄擋不擋得住不重要——沒有人會走那條貴的。
    給路跟補洞是同一件事的兩半。

    ## 護欄的判準是「跑之前 vs 跑之後」，不是「模型說它沒改」

    重構員的提示第一條就寫著「不准改任何測試檔」，但那是**懇求**：
    模型可以忽略，而且忽略了沒有人會發現——測試被改掉之後跑起來還是綠的。
    這裡拍兩張快照比對（`載體/重構護欄.py`），差在哪個檔就是誰被動了。

    **回 4 不是壞了**，是停止規則按設計生效。外圈不准去「修」它。

    ## 停止政策（單獨跑不等於沒有 stop rule）

    | 上限 | 由誰給 |
    |---|---|
    | 最多模型呼叫數＝1 | 這個函式的形狀（只 `詢問` 一次） |
    | 最多 token／美金 | `--預算token`／`--預算美金`（預設不鎖） |
    | 最多秒數 | `--逾時`（預設 1800） |
    | 結果未知不重跑 | 終局映射回 3，腳本照規矩不准重跑 |
    """
    根 = _專案脈絡(參數).根目錄
    # **給了 `--範圍` 才拍全樹。** 範圍護欄看不到 `src/` 就等於沒有護欄；
    # 但沒給範圍時拍全樹是白付錢——`動到測試了嗎` 只看 `tests/`。
    拍 = 拍全樹快照 if 參數.範圍 else 拍快照
    前 = 拍(根)
    碼 = _子命令_問(參數, 角色=角色提示.重構員)
    後 = 拍(根)
    動了 = 動到測試了嗎(前, 後)
    if 動了:
        print("護欄：重構員動到測試檔了，這一步不算數。", file=sys.stderr)
        for 檔 in 動了:
            print(f"  {檔}", file=sys.stderr)
        print("測試是驗收機制，動它等於自己給自己發及格證。要改測試請走測試員。", file=sys.stderr)
        return 護欄碼
    # **不給 `--範圍` 就不檢查**——既有呼叫端一個都不准壞掉。
    出界 = 跑出範圍了嗎(前, 後, tuple(參數.範圍)) if 參數.範圍 else ()
    if 出界:
        這次的範圍 = ", ".join(參數.範圍)
        print(f"護欄：重構員動到範圍外的檔了（這次只准動 {這次的範圍}）。", file=sys.stderr)
        for 檔 in 出界:
            print(f"  {檔}", file=sys.stderr)
        print("範圍是呼叫端指名的，撐開它要由人決定，不是模型順手。", file=sys.stderr)
        return 護欄碼
    return 碼


def _挑腦(參數: argparse.Namespace) -> tuple[str, str | None, str | None] | None:
    """決定這次用哪條鏈、哪顆模型、哪種思考深度。回 None ＝ 參數矛盾，呼叫端該退出。

    `--工作` 查派工表（策略寫在表裡不是寫在我腦裡）；`--用` 是手動指定。
    **兩個都給是矛盾不是「其中一個優先」**——猜一個會讓策略被無聲推翻。
    """
    if 參數.工作 and (參數.用 or 參數.模型 or 參數.思考深度):
        print(
            "--工作 已經決定了要用誰、哪顆模型與思考深度，不要同時給 --用、--模型 或 --思考深度",
            file=sys.stderr,
        )
        return None
    if 參數.工作:
        派 = 怎麼派(工作種類(參數.工作))
        return ",".join(派.腦們), 派.模型, 派.思考深度
    if not 參數.用:
        print("要給 --用（哪一家）或 --工作（照派工表挑）", file=sys.stderr)
        return None
    return 參數.用, 參數.模型, 參數.思考深度


def _挑權限(參數: argparse.Namespace) -> 權限:
    """全開蓋過可編輯。兩個都沒給就是唯讀——忘了設不會變成放行。"""
    if 參數.全開:
        return 權限.全開
    return 權限.可編輯 if 參數.可編輯 else 權限.唯讀


def _帳本目錄(參數: argparse.Namespace) -> Path:
    """這次要讀寫哪一份帳本。**寫端與讀端共用一個答案**——

    兩邊各算一次的話，改了帳本落點只改到一邊，
    症狀是「明明記了卻讀不到」，而那看起來像帳本壞了。
    """
    if 參數.帳本目錄:
        return Path(參數.帳本目錄)
    return _專案脈絡(參數).帳本


#: 帳本檔名開頭的時戳格式。**跟 `帳本.新執行識別碼` 是同一個格式**——
#: 兩邊走散的話，窗口過濾會靜默地濾掉全部（看起來像「從來沒花過」）。
_檔名時戳 = "%Y%m%dT%H%M%SZ"


def _秘密先交出去(專案: Path) -> int | None:
    """把這個專案的祕密塞進 `os.environ`，子程序就繼承得到。回退出碼 ＝ 別出生。

    **為什麼是 `os.environ` 不是只給子程序的那份**：`遮罩` 讀的是 `os.environ`。
    只塞給子程序的話，祕密會被用、但不會被遮——它會以明文躺進帳本，
    而那是一個沒有任何症狀的洩漏（`tests/驗收/test_載進去的秘密不進帳本.py` 守著）。

    **沒有祕密檔就是沒有祕密要載**（回 None）——預設關閉，跟熔斷與預算鎖同一條。
    """
    try:
        載入到(os.environ, 專案=專案)
    except 看不懂的祕密檔 as 錯:
        # **出生前就擋。** 打出去之後才發現，祕密已經在子程序裡了。
        print(str(錯), file=sys.stderr)
        return 阻擋
    return None


def _預算先擋一下(參數: argparse.Namespace, 這次: _醒來 | None = None) -> int | None:
    """超支就印原因並回退出碼，沒超回 None。**在打出去之前叫**——

    打完再判就只是事後記錄，一塊錢都沒省。

    兩個上限都沒給就是**不鎖**：「我主要是要看帳，但不要讓帳去把流程關閉。」
    熔斷是這樣，預算也是這樣。
    """
    限 = 上限(token=參數.預算token, 美金=參數.預算美金)
    if 限.token is None and 限.美金 is None:
        return None
    現在 = datetime.now(UTC)
    try:
        花 = 花了多少(
            _窗口內的執行(_帳本目錄(參數), 現在=現在, 幾小時=參數.預算幾小時),
            現在=現在,
            幾小時=參數.預算幾小時,
        )
    except ValueError as 錯:
        # **旗標給錯是用法錯誤（2），不是護欄生效（4）。** 壓成同一個碼的話，
        # 外圈會把「人打錯字」當成「按設計停了」，然後去調上限。
        print(str(錯), file=sys.stderr)
        return 阻擋
    擋 = 超支了嗎(花, 限)
    if 擋 is None:
        return None
    訊息 = f"預算鎖：{擋}"
    print(訊息, file=sys.stderr)
    if 這次 is not None:
        # **護欄生效不是壞了，但它要看得見。** 只留一行 stderr 在 launchd 的
        # log 裡的話，「排程從昨晚就一直被擋著」會是一個沒有人發現的狀態。
        這次.結果, 這次.理由 = 被預算擋, 訊息
    return 護欄碼


def _窗口內的執行(帳本目錄: Path, *, 現在: datetime, 幾小時: float) -> list[摘要]:
    """窗口內的執行摘要。**先用檔名的時戳濾，再開檔**——

    檔名開頭就是 UTC 時戳，字典序就是時序，所以「三個月前那幾千次」
    連開都不用開。每次呼叫前把整個專案的帳本讀完會變成新的成本漏洞。

    讀不動的檔跳過（不是整段算不出來）：一筆壞掉就整個算不出來
    等於沒有預算鎖。
    """
    if 幾小時 <= 0:
        return []  # 由 `花了多少` 統一報錯，這裡不重複那句話
    起點 = (現在 - timedelta(hours=幾小時)).strftime(_檔名時戳)
    執行們 = []
    for 檔 in 列出執行(帳本目錄):
        if 檔.stem < 起點:
            break  # 新的在前，遇到第一個舊的就不必再看了
        with contextlib.suppress(OSError):
            執行們.append(讀一次執行(檔))
    return 執行們


#: 熔斷往回看幾次執行。門檻是連續 3 次，看 10 次夠判斷而且讀得快。
_熔斷看幾次 = 10


def _這個專案誰熔斷了(帳本目錄: Path, *, 啟用: bool = False) -> Callable[[str], bool]:
    """讀這個專案的帳本歷史，做一個「這一家熔斷了嗎」的判斷。

    **預設關閉**：看帳跟關流程是兩件事。帳本要繼續記、繼續讀得到，
    但不准因為帳本裡的歷史而不去叫某一家腦；只有明確打開才啟用過濾。

    **只讀最近幾次**：熔斷看的是「連續」，而歷史一長，
    每次呼叫前都把整個專案的帳本讀完就變成新的成本漏洞。

    讀不到帳本就一律不熔斷（fail-open）：**熔斷是省錢的最佳化，不是安全防護**。
    讀不到就當沒事，比讓使用者卡在一個他不知道怎麼解的狀態好。
    """
    if not 啟用:
        return lambda _: False
    try:
        檔們 = 列出執行(帳本目錄)[:_熔斷看幾次]
        執行們 = [讀一次執行(檔) for 檔 in 檔們]
    except OSError:
        return lambda _: False
    現在 = datetime.now(UTC)
    return lambda 家: 該跳過嗎(執行們, 家, 現在) is not None


def _拆腦來源(來源: str) -> tuple[str, ...]:
    """把 `--用 codex,agy` 這種逗號字串拆成家名，順手去空白、丟掉空欄位。"""
    return tuple(家.strip() for 家 in 來源.split(",") if 家.strip())


def _濾掉熔斷的(來源: str, 熔斷了: Callable[[str], bool]) -> list[str]:
    """把連續失敗的家從接力鏈裡拿掉。**在建腦之前濾**——

    熔斷的意思是「不要打出去」，等打完再判就只是事後記錄，一點都沒省。

    **不准濾成空的**：全部都熔斷時留最後一顆讓它去試。
    清空會讓使用者拿到「至少要指定一家」這種看不懂的錯誤，
    而真正的原因（每一家都連續失敗了）完全沒被講出來——
    寧可撞牆一次拿到真的錯誤訊息。
    """
    家們 = list(_拆腦來源(來源))
    留 = [家 for 家 in 家們 if not 熔斷了(家)]
    return 留 or 家們[-1:]


def _建腦(  # noqa: PLR0913 —— 記帳的旋鈕就是這麼多，包成資料類別會讓呼叫端更難讀
    來源: str,
    執行檔: Path | None,
    帳: 帳本,
    *,
    熔斷了: Callable[[str], bool] = lambda _: False,
    記全文: bool = True,
    單次最多token: int = 預設單次最多token,
) -> 語言模型:
    """`--用 codex,agy` 就是接力：前一顆失敗換下一顆。

    **記帳包在接力鏈裡面**——包在外面的話換腦這件事整個消失。

    `熔斷了` 在**建腦之前**把連續失敗的家濾掉。預設不熔斷任何一家：
    這一層是機構，判斷誰熔斷了是呼叫端的事（它才知道要讀哪個專案的帳本）。
    """
    家們 = _濾掉熔斷的(來源, 熔斷了)
    if not 家們:
        訊息 = "至少要指定一家"
        raise ValueError(訊息)
    # 少裝一家不該讓整串垮掉（見 `缺席腦`）。只指定一家卻沒裝則當場炸。
    原始 = tuple(
        建立或缺席(
            cast(家族, 家),
            執行檔=執行檔,
            可以缺席=len(家們) > 1,
            記=帳.記一筆,
        )
        for 家 in 家們
    )
    腦們 = 記帳每一顆(原始, 帳, 記全文=記全文, 單次最多token=單次最多token)
    return 腦們[0] if len(腦們) == 1 else 接力腦(名稱="→".join(家們), 腦們=腦們)


#: 哪一階算動腦。**照 `工作種類` 自己的定義分，不是憑感覺**：
#: 測試／實作／重構是「照現成樣子寫、答案對不對看得出來」；
#: 審查是「設計取捨、找漏洞、答案對不對要靠推理」。
#:
#: 這個分法順帶就省 codex——**多次的便宜呼叫給 agy，一次的難題給 sol**。
_階段的工作 = {
    階段代碼.測試: 工作種類.例行,
    階段代碼.實作: 工作種類.例行,
    階段代碼.重構: 工作種類.例行,
    階段代碼.審查: 工作種類.推理,
}


def _階段的工作種類(階段: 階段代碼) -> 工作種類 | None:
    """這一階算例行還是推理。表裡沒有回 `None`——由窮舉測試抓，不在這裡猜。"""
    return _階段的工作.get(階段)


def _階段的派法(階段: 階段代碼) -> 派法:
    """這一階派給誰、用哪顆型號。**沒配到就當場炸，不猜**——

    猜一個預設的代價是每一次都派錯家，而且沒有人會發現：
    輸出看起來一樣，只是慢、貴、或笨。
    """
    種 = _階段的工作種類(階段)
    if 種 is None:
        訊息 = f"派工表不知道 {階段.value} 算例行還是推理"
        raise ValueError(訊息)
    return 怎麼派(種)


def _這次的TDD角色藍圖(參數: argparse.Namespace) -> tuple[角色藍圖, ...]:
    """把命令列的腦來源與逾時套到 TDD 藍圖，保留派工表的模型設定。"""
    結果: list[角色藍圖] = []
    for 藍圖 in TDD角色藍圖資料:
        指名 = 參數.審查用 if 藍圖.識別碼 == 階段代碼.審查.value else 參數.用
        if 指名:
            結果.append(
                dataclasses.replace(
                    藍圖,
                    派法=dataclasses.replace(藍圖.派法, 腦們=_拆腦來源(指名)),
                    模型=None,
                    思考深度=None,
                )
            )
            continue
        結果.append(dataclasses.replace(藍圖, 模型=藍圖.派法.模型, 思考深度=藍圖.派法.思考深度))
    if 參數.逾時 is not None:
        結果 = [dataclasses.replace(藍圖, 逾時秒=參數.逾時) for 藍圖 in 結果]
    if getattr(參數, "模型", None):
        結果 = [dataclasses.replace(藍圖, 模型=參數.模型) for 藍圖 in 結果]
    return tuple(結果)


def _建TDD角色表(
    藍圖們: tuple[角色藍圖, ...],
    *,
    執行檔: Path | None,
    帳: 帳本,
    記全文: bool,
    單次最多token: int = 預設單次最多token,
) -> Mapping[階段代碼, 角色]:
    """依藍圖建立 TDD 角色，讓每個角色共用同一條建腦路徑。"""

    def 建腦(角色派法: 派法) -> 語言模型:
        return _建腦(
            ",".join(角色派法.腦們),
            執行檔,
            帳,
            記全文=記全文,
            單次最多token=單次最多token,
        )

    return cast(Mapping[階段代碼, 角色], 建角色表(藍圖們, 建腦=建腦))


@contextmanager
def _開帳(參數: argparse.Namespace, *, 執行識別碼: str | None = None) -> Iterator[帳本]:
    """CLI **預設記帳**：它是程式不是函式庫，程式留執行紀錄是正常的。

    而且 opt-in 的帳本等於沒有帳本——真的需要事後追查的那次，
    通常就是沒想到要先打開它的那次。用 `--不記帳` 關掉。

    **兩條軸都要顧**：帳本按專案分（歸屬），但存在專案外面（完整性）。
    落在工作目錄裡的話，被 nova 驅動的模型會順手把它 commit 進去，而且改得到。
    「屬於哪個專案」是索引問題，不是存放位置問題——見 `預設帳本目錄`。
    """
    if 參數.不記帳:
        yield 不記帳本()
        return
    with 開帳本(_帳本目錄(參數), 執行識別碼=執行識別碼) as 帳:
        yield 帳


def _邊跑邊印(內層: 執行器) -> 執行器:
    """包一層只為了印進度。工作流本身不負責輸出——那是 CLI 的事。"""

    def 執行一步(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
        print(f"→ {定義.代碼.value:<13} {定義.名稱}", file=sys.stderr, flush=True)
        結果 = 內層(定義, 任, 軌跡)
        記號 = {None: "·", True: "綠", False: "紅"}[結果.判準綠]
        print(f"  {記號} {結果.終局.value}", file=sys.stderr, flush=True)
        if 結果.終局 is not 終局.成功 and 結果.證據:
            print(f"    {結果.證據.splitlines()[0][:160]}", file=sys.stderr, flush=True)
        return 結果

    return 執行一步


def _哪幾家(旗標: str | None, 階段: 階段代碼) -> set[str]:
    """這一階實際上會叫到哪幾家。旗標沒給就問派工表。"""
    來源 = 旗標 or ",".join(_階段的派法(階段).腦們)
    return set(_拆腦來源(來源))


def _工作流前置檢查(參數: argparse.Namespace, 工作目錄: Path, 進度檔: Path | None) -> str | None:
    """開跑之前只靠參數就判得出來的事。有問題回訊息，沒問題回 `None`。

    **便宜的驗證要先跑。** 這一段搬到建腦前面是被 CI 教的：
    CI 沒裝三家 CLI，建腦當場 `FileNotFoundError`，路徑檢查根本走不到——
    本機綠、CI 紅，而且紅的理由跟這些檢查無關。
    只要參數就判得出來的東西，不該等到花了力氣之後才判。

    這裡也守本地腦的資格：它是 9B 唯讀模型，不能成為工作流唯一的審查點。
    """
    # **不給旗標時要拿派工表挑出來的家去比**，不是跳過檢查——
    # 硬規則 5 守的是「誰真的被叫」，不是「使用者打了什麼字」。
    #
    # 家族名重疊**不再是錯**（`#140`）：判準是對話不是家族名，
    # 三家不給續接時本來就都是新對話。真正的自寫自評是跑在同一個對話裡，
    # 而那在結構上不可能（`固定提示角色` 沒有續接欄位）。
    審查家們 = _哪幾家(參數.審查用, 階段代碼.審查)
    if (不合格理由 := 審查資格理由(審查家們)) is not None:
        return 不合格理由
    if 進度檔 is not None:
        # 模型動得到工作目錄整棵樹。進度檔住在裡面的話，
        # 它會往裡面寫，而那份東西下一輪會被當成前情餵回去。
        try:
            檢查進度檔位置(進度檔, 工作目錄)
        except ValueError as 錯:
            return str(錯)
    return None


@dataclasses.dataclass(frozen=True, slots=True)
class _題目:
    """這一輪要做什麼，以及它是不是從收件匣來的。

    `收件` 不是 None 的話，做完要把原始請求搬到成果旁邊——
    成果帳本說「這件收在護欄」，你要看得到當初丟進來的是什麼。
    """

    描述: str
    收件: 收件單 | None


def _這次要做什麼(參數: argparse.Namespace) -> _題目 | int:
    """決定題目從哪來。**回 int ＝ 沒得做，那個數字就是退出碼。**

    題目可以從收件匣來——檔案就是事件。不另外開一條執行路徑，
    因為預算、判準、歸檔各一份的話，兩份遲早會不一樣。

    **空收件匣回 0，沒給題目回 2。** 兩者不一樣：排程每小時醒來一次，
    多數時候收件匣本來就是空的，那是正常狀態不是錯誤；
    「你什麼都沒給」才是使用者打錯。回同一個碼的話，
    排程的 log 會被永遠不會有人修的錯誤塞滿。
    """
    if 參數.從收件匣:
        匣 = _專案脈絡(參數).收件
        收件 = 收下一件(匣)
        if 收件 is None:
            print(f"收件匣是空的（{匣}）", file=sys.stderr)
            return 放行
        return _題目(描述=收件.任務, 收件=收件)
    try:
        描述 = 讀提示(argv片段=參數.任務, 提示檔=參數.提示檔)
    except (提示走錯路, OSError) as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    if not 描述.strip():
        print("沒有任務可以做（用參數給、從 stdin 餵，或丟進收件匣）", file=sys.stderr)
        return 阻擋
    return _題目(描述=描述, 收件=None)


def _子命令_跑(參數: argparse.Namespace) -> int:
    """敲一句話就開始做。**先落成收件檔，再走 `工作流 --從收件匣`。**

    路線圖觸發層那四格裡，「檔案出現」的副標是**唯一的橋**——另外三格
    （你敲、時鐘、協定）最後都該收斂成「往收件匣丟一個檔」。所以這一格
    不是一條新的執行路徑，是**把你敲的字變成事件**的那一步。

    另開一條的話，預算鎖、祕密載入、判準、單例鎖、歸檔各會有兩份，
    而兩份遲早會不一樣——**而且不一樣的那天沒有人會發現**。

    **先落檔再跑，順序是有意義的**：排程 15 分鐘一次而一輪可能跑 40 分鐘，
    所以撞上鎖是常態。先落檔的話，撞到那一次題目還在佇列上，
    下一次醒來就做得到；先搶鎖的話撞到就整個掉了，
    而使用者以為他派出去了。
    """
    try:
        描述 = 讀提示(argv片段=參數.任務, 提示檔=參數.提示檔)
    except (提示走錯路, OSError) as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    try:
        丟一件(描述, 來源=你敲, 目錄=_專案脈絡(參數).收件)
    except (ValueError, OSError) as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    參數.從收件匣 = True
    參數.喚醒來源 = 喚醒來源.人手動敲.value
    return _子命令_工作流(參數)


def _子命令_工作流(參數: argparse.Namespace) -> int:
    """跑一輪 TDD：測試 → 驗證紅 → 實作 → 驗證綠 → 審查。

    `--審查用` 可以跟 `--用` 同一家（`#140`）——判準是**對話**不是家族名，
    三家不給續接時本來就都是新對話。真正要擋的自寫自評是跑在同一個對話裡，
    而那在結構上不可能：`固定提示角色` 組呼叫選項時沒有續接這個欄位。

    **一次只准跑一個**（見 `載體.單例`）。排程每 15 分鐘叫一次而一輪可能跑
    40 分鐘，沒有這道鎖就會三個一起燒預算、一起改同一份原始碼。
    """
    這次 = _醒來()
    try:
        with 只准一個(_工作流鎖(參數)):
            碼 = _工作流跑一輪(參數, 這次)
    except 拿不到鎖 as 忙:
        print(str(忙), file=sys.stderr)
        這次.結果, 這次.理由 = 在忙, str(忙)
        # **排程撞到就安靜讓開（0），其他喚醒來源是真衝突（2）。**
        # 排程本來就會在忙的時候醒來；把它印成錯誤的話，log 會被永遠
        # 不會有人修的錯誤塞滿，然後真的錯誤就被淹掉了。
        碼 = (
            放行
            if getattr(參數, "喚醒來源", 喚醒來源.人手動敲.value) == 喚醒來源.排程到期.value
            else 阻擋
        )
    _記下這次醒來(參數, 這次, 碼)
    return 碼


def _記下這次醒來(參數: argparse.Namespace, 這次: _醒來, 碼: int) -> None:
    """把這一次醒來寫進狀態檔。**覆寫，不是 append。**

    歷史已經有兩本了（事件帳本、成果帳）；再開第三本 append-only 的東西
    只會跟前兩本漂移。這裡答的是「現在怎麼樣」。
    """
    專案 = _專案脈絡(參數).根目錄
    寫下現況(
        現況(
            上次醒來=現在幾點(),
            上次結果=這次.結果,
            上次退出碼=碼,
            上次理由=這次.理由,
            上次執行識別碼=這次.執行識別碼,
        ),
        路徑=狀態檔(專案),
    )


def _工作流鎖(參數: argparse.Namespace) -> Path:
    """鎖按專案分——兩個不同的專案本來就該可以同時跑。"""
    return _專案脈絡(參數).鎖


def _工作流開跑前(
    參數: argparse.Namespace, 工作目錄: Path, 進度檔: Path | None, 這次: _醒來
) -> int | None:
    """開跑前的兩道檢查。**回退出碼 ＝ 別跑了。**

    **順序有意義**：用法錯誤（2）先講完，再談護欄（4）。指令本身打錯的時候
    先說「超支了」，會把人帶去調上限——而真正的問題是那行指令。

    **排程自己跑的是工作流，不是 `nova 問`**：預算鎖只接在 `問` 上的話，
    它剛好在最需要它的那條路徑上不存在。

    從簡: 只在開跑前查一次跨執行預算。跑到一半超支由工作流自己的
    token stop rule 收，所以缺口的上界就是那一輪的上限，不是無限。
    """
    這次.結果 = 出不了生
    擋住 = _工作流前置檢查(參數, 工作目錄, 進度檔)
    if 擋住 is not None:
        print(擋住, file=sys.stderr)
        這次.理由 = 擋住
        return 阻擋
    沒憑證 = _秘密先交出去(工作目錄)
    if 沒憑證 is not None:
        這次.理由 = "祕密檔有問題（看 stderr）"
        return 沒憑證
    擋 = _預算先擋一下(參數, 這次)
    if 擋 is not None:
        return 擋
    這次.結果 = 做完了
    return None


def _工作流跑一輪(參數: argparse.Namespace, 這次: _醒來) -> int:
    """真正的那一輪。拆出來只為了讓鎖包住它，行為完全沒變。

    `這次` 由沿路的出口自己填。**沒有任何一條出口可以不填**——
    預設是「做完了」，所以漏填會讓一次被擋下的醒來記成做完了，
    那比不記更糟。由 `tests/驗收/test_需要你的事都在這.py` 守著。
    """
    工作目錄 = _專案脈絡(參數).根目錄
    # **起點要在動手之前拍**：工作流跑完之後 HEAD 可能已經被它自己推走了，
    # 那時候拍到的是終點，而帳上那一欄的用途正是「要退回去的話退到哪」。
    起點 = 目前commit(工作目錄)
    進度檔 = None if 參數.進度檔 is None else Path(參數.進度檔)
    擋 = _工作流開跑前(參數, 工作目錄, 進度檔, 這次)
    if 擋 is not None:
        return 擋
    題 = _這次要做什麼(參數)
    if isinstance(題, int):
        # 空收件匣（0）跟沒給題目（2）是兩回事：前者是排程最常見的正常狀態。
        這次.結果 = 沒事做 if 題 == 放行 else 出不了生
        return 題
    描述, 收件 = 題.描述, 題.收件
    # **兩本帳共用同一個識別碼**：成果上的識別碼就是事件帳本那個
    # `<執行識別碼>.jsonl` 的檔名，走散了就對不回去。
    識別 = 新執行識別碼()
    這次.執行識別碼 = 識別
    try:
        with _開帳(參數, 執行識別碼=識別) as 帳:
            執行 = 建TDD執行器(
                角色表=_建TDD角色表(
                    _這次的TDD角色藍圖(參數),
                    執行檔=Path(參數.執行檔) if 參數.執行檔 else None,
                    帳=帳,
                    記全文=not 參數.不記全文,
                    單次最多token=參數.單次最多token,
                ),
                跑判準=建判準(判準指令(參數.判準)),
                跑重構判準=建重構判準(),
            )
            # **同一個旗標做兩件事**：讀上一輪當前情、寫這一輪。
            # 拆成兩個旗標的話，一定有人只給其中一個，然後以為自己接上了。
            #
            # **前情有兩個來源，優先權要明講**：`--進度檔` 是使用者指定的跨輪記憶，
            # 它每一階都 append，是全部輪次的超集；接續票只帶上一輪。
            # 給了進度檔就用它——兩份接起來會讓上一輪在提示裡出現兩次。
            走過的 = 讀進度(進度檔) if 進度檔 is not None else _接來的前情(收件)
            內層 = _邊跑邊印(執行) if 進度檔 is None else 進度執行器(_邊跑邊印(執行), 進度檔)
            果 = 跑工作流(
                任務(描述=描述, 工作目錄=工作目錄, 前情=走過的),
                執行一步=記帳執行器(內層, 帳, 單次最多token=參數.單次最多token),
                停止=停止條件(
                    最多步數=參數.最多步數,
                    最多token=參數.最多token,
                    單次最多token=參數.單次最多token,
                ),
                起點=階段代碼(參數.起點),
            )
    except (ValueError, FileNotFoundError) as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    for 步 in 果.軌跡:
        print(f"[{步.階段.value}] {步.終局.value}\n{步.證據}\n")
    print(f"\n{果.結束.代碼.value}：{果.結束.原因}", file=sys.stderr)
    碼 = _驗收說了算(收件, 碼=_工作流退出碼(果.結束, 果.軌跡), 工作目錄=工作目錄)
    # **跑起來的那些直接用 `結束代碼` 的值**，不另立一套詞彙——
    # 成果帳的 `outcome` 就是這組字。兩套會讓人不知道哪個是真的。
    這次.結果 = 果.結束.代碼.value
    _歸檔成果(參數, 這次=_這次執行(識別=識別, 起點commit=起點), 題=題, 果=果, 退出碼=碼)
    if 收件 is not None:
        # **成果要對得回請求**：兩邊都用執行識別碼當檔名，所以看到
        # 「這件收在護欄」的時候，旁邊就是當初丟進來的原文。
        完成一件(收件, 執行識別碼=識別, 已處理=_已處理目錄(參數))
        _也許接著排(收件, 果=果, 識別=識別, 碼=碼, 這次=這次)
    return 碼


def _驗收說了算(收件: 收件單 | None, *, 碼: int, 工作目錄: Path) -> int:
    """票宣告的驗收指令說了算，不是模型說了算。回**修正過的**退出碼。

    **只有 `碼 == 0` 才跑驗收。** 工作流自己都摔了還去跑，除了多燒一次時間，
    更糟的是那條驗收剛好綠的時候（例如它跟這次的工作無關），
    一個失敗的回合會被改寫成成功。

    **驗收紅回 4（護欄）不回 1。** 4 的定義是「停止規則按設計生效」，
    本來就含「重構改壞行為」那一類；驗收紅是同一種東西——工作流跑完了，
    但它沒做到。而且回 4 之後**不必新增任何流程**：`_也許接著排` 已經在看
    `碼 == 護欄碼`，`最多輪次 = 3` 已經是那個重試迴圈的停止規則。
    回 1 會停在那裡等人；回 3 更糟，3 的意思是「不知道做了沒」，腳本不准重跑。

    沒有收件單、或票沒宣告驗收，都原樣回去——**人在現場的票不必帶驗收**
    （`收件.要驗收嗎`），因為沒宣告就判它沒做完的話，每一張手丟的票都會退回重做。
    """
    if 收件 is None or 碼 != 0 or not 收件.驗收:
        return 碼
    果 = 跑驗收(收件.驗收, 工作目錄=工作目錄)
    if 果.綠:
        return 碼
    for 一條 in 果.每一條:
        print(f"[驗收] {一條.指令} → {一條.退出碼}\n{一條.證據}\n", file=sys.stderr)
    print("驗收沒過，這一輪不算做完", file=sys.stderr)
    return 護欄碼


def _接來的前情(收件: 收件單 | None) -> str:
    """接續票帶來的前情。**排程醒來沒有 `--進度檔`，所以這是它唯一的來源。**"""
    return "" if 收件 is None else 收件.前情


def _走到哪(軌跡: tuple[步驟結果, ...]) -> str:
    """把這一輪的軌跡壓成下一輪的前情。**只給證據，不給結論。**

    每一步截斷（跟進度檔同一個上限）：不截的話，第 3 輪的提示會膨脹回
    原本要解決的那個問題。
    """
    return "\n\n".join(f"## {步.階段.value} · {步.終局.value}\n{步.證據[:一步上限]}" for 步 in 軌跡)


def _也許接著排(收件: 收件單, *, 果: 工作流結果, 識別: str, 碼: int, 這次: _醒來) -> None:
    """撞到上限停下來的那件，排回收件匣讓下一次醒來接著做。

    **判準是最終退出碼等於 4，不是「收場分類是護欄」。** 兩者不一樣：
    `3` 蓋過收場分類（見 `_工作流退出碼`），而 `3` 的意思是「不知道工作
    做了沒」——自動重排會把可能已經做過的事再做一次。`1` 是東西壞了，
    接著做只會再壞一次。這兩種都留給人看，那正是使用者要的分法。

    被殺掉的那一輪走不到這裡（檔案留在 `處理中/`），所以「按設計停下」
    跟「當掉」在收件匣上就分得開。
    """
    if 碼 != 護欄碼:
        return
    票 = 接著排(
        收件,
        前情=_走到哪(果.軌跡),
        上一輪=識別,
        目錄=收件.處理中路徑.parent.parent,
    )
    if 票 is None:
        # **輪次用完要看得見。** 靜靜不排的話，「做不完」跟「做完了」
        # 在 nova 狀態 上長得一模一樣，而那正是最貴的那種看不見。
        這次.理由 = f"接續輪次用完了（{最多輪次} 輪），這件要你自己看一下"
        return
    這次.理由 = f"撞到上限，已排回收件匣接著做：{票.name}"


@dataclasses.dataclass(frozen=True, slots=True)
class _這次執行:
    """一次執行的身分與起點。

    收成一個物件不是為了少打字：`_歸檔成果` 的參數過了 ruff `PLR0913` 的門檻，
    而門檻的解法是拆，不是調高。這兩格本來就是一組——**識別碼是兩本帳對得回去的鍵，
    起點是要退回去的那個點**，都在講「這一次執行本身」，不是它要做的題目。
    """

    識別: str
    起點commit: str | None


def _歸檔成果(
    參數: argparse.Namespace,
    *,
    這次: _這次執行,
    題: _題目,
    果: 工作流結果,
    退出碼: int,
) -> None:
    """把一次工作的收場寫進成果帳本。

    事件帳本答不出「做完了沒」——那要從軌跡自己推，而推的規則
    （`3` 蓋過 `4`）住在 `_工作流退出碼`。所以收場與退出碼直接寫在成果上。

    **帳寫不下去不准把工作結果吃掉。** 磁碟滿了、權限不對，都只是少一筆帳；
    把它變成非零退出碼會讓外圈以為工作失敗了。
    """
    摘 = _這次的摘要(參數, 這次.識別)
    try:
        歸檔(
            成果(
                執行識別碼=這次.識別,
                # **使用者打進去的那句話也要遮**——它跟模型講的話一樣會落盤，
                # 而且比模型那份活得更久（`已處理/` 沒有截斷也沒有輪替）。
                任務=遮罩(題.描述.strip()).文字,
                收場=果.結束.代碼.value,
                退出碼=退出碼,
                起=摘.起 if 摘 else "",
                迄=摘.迄 if 摘 else "",
                走了幾階=len(果.軌跡),
                總token=摘.總token if 摘 else 0,
                總成本美金=摘.總成本美金 if 摘 else None,
                # **來源是「誰造了這個收件檔」，不是「誰醒來把它撈起來」**——
                # 排程把一個手丟的檔案做掉，那一件的來源仍然是檔案。
                來源=題.收件.來源 if 題.收件 is not None else 你敲,
                # 這兩欄一起答「這次爛掉是不是因為規則變了、該退回哪」。
                規則表版本=規則表版本(),
                起點commit=這次.起點commit,
            ),
            目錄=_已處理目錄(參數),
        )
    except OSError as 錯:
        print(f"成果沒記成（{錯}）", file=sys.stderr)


def _這次的摘要(參數: argparse.Namespace, 識別: str) -> 摘要 | None:
    """起訖與 token 從剛寫完的事件帳本讀回來，不在這裡再算一次。

    `--不記帳` 的時候沒有檔案，那些格子就留空——**留空不准假裝成 0**，
    所以起訖是空字串不是某個假時間。
    """
    檔 = _帳本目錄(參數) / f"{識別}.jsonl"
    if not 檔.is_file():
        return None
    try:
        return 讀一次執行(檔)
    except OSError:
        return None


def _已處理目錄(參數: argparse.Namespace) -> Path:
    """跟 `_帳本目錄` 用同一個專案鍵——兩本帳要住在同一個專案資料夾底下。"""
    if 參數.帳本目錄:
        return Path(參數.帳本目錄).parent / "已處理"
    return _專案脈絡(參數).已處理


def _子命令_已處理(參數: argparse.Namespace) -> int:
    """看成果帳本：哪幾件工作做完了、收在哪種結局。

    **有讀取端才算補了成果帳本**——只有寫端的話那是寫檔案給沒人看。
    """
    目錄 = _專案脈絡(參數).已處理
    筆們 = 列出成果(目錄, 上限=參數.最近)
    if not 筆們:
        print(f"還沒有任何成果（會寫在 {目錄}）")
        return 放行
    for 筆 in 筆們:
        print(_一行成果(筆))
    return 放行


def _一行成果(筆: 成果) -> str:
    階 = f"{筆.走了幾階} 階" if 筆.走了幾階 else "沒走到任何一階"
    成本 = f" · US${筆.總成本美金:.4f}" if 筆.總成本美金 is not None else ""
    前段 = f"{筆.執行識別碼}  {筆.收場}（碼 {筆.退出碼}）  {階}"
    return f"{前段}  {筆.總token} token{成本}  {筆.任務}"


_收場的退出碼 = {
    結束代碼.完成: 放行,
    結束代碼.護欄: 護欄碼,
    結束代碼.中止: 閘紅,
}


def _工作流退出碼(收場: 結束, 軌跡: tuple[步驟結果, ...]) -> int:
    """一輪工作流收在哪，變成外圈看得懂的碼。**純函式，所以測得動。**

    | 碼 | 意思 | 外圈該做什麼 |
    |---|---|---|
    | 0 | 完成 | 收工 |
    | 4 | 護欄生效（預算／步數／卡住／結果未知／重構改壞行為） | 改題目或起點，**放寬是人的決定** |
    | 1 | 東西壞了（角色確定失敗） | 照硬規則 6 診斷：環境 → 回饋 → 流程 |
    | 3 | 軌跡裡有一步結果未知 | **不准重跑** |

    **`3` 蓋過收場分類**：`4` 說的是「按設計停了，改個題目再跑就好」，
    但只要有一步可能做了一半，重跑就會重做副作用。保守的那個要贏。
    """
    if any(步.終局 is 終局.結果未知 for 步 in 軌跡):
        return 未知
    return _收場的退出碼[收場.代碼]


def _子命令_排程(參數: argparse.Namespace) -> int:
    """印出 launchd 設定。**只印不裝。**

    `launchctl load` 下去之後 BTM（背景項目管理）就會留紀錄，`unload` 也清不乾淨
    ——那是使用者系統上的狀態，不是 nova 的。跟「不准自動改使用者的設定檔」
    同一條界線：nova 產生，人安裝。
    """
    專案 = _專案脈絡(參數).根目錄
    # **在自己的 venv 裡建一個看得出是誰的啟動器**，不是使用者系統上的狀態，
    # 所以這一步 nova 自己做（`launchctl load` 那一步才是人的）。
    # 每次重印都建一次：`uv sync` 之類的動作可能把它清掉，而清掉之後
    # launchd 的 job 會永久壞掉，背景項目卻還在那裡。
    try:
        執行檔 = 確保啟動器在(Path(sys.executable))
    except OSError as 錯:
        print(f"建不出啟動器 {啟動器名}：{錯}", file=sys.stderr)
        return 阻擋
    print(f"啟動器：{執行檔}（活動監視器會顯示 {啟動器名}）", file=sys.stderr)
    try:
        設定 = 排程設定(
            # **執行檔與 PATH 綁在一起**：launchd 不跑登入 shell，
            # 少了 PATH 判準指令就找不到，而那個錯會被當成「測試紅了」。
            跑法=怎麼跑(執行檔=執行檔, 路徑環境=os.environ.get("PATH", "")),
            專案=專案,
            狀態根=狀態根目錄(),
            每幾分=參數.每幾分,
            預算=排程預算(
                上限=上限(token=參數.預算token, 美金=參數.預算美金),
                幾小時=參數.預算幾小時,
            ),
        )
    except ValueError as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    print(設定)
    標籤 = 排程標籤(專案)
    print(
        "\n".join(
            [
                "",
                f"# 存起來（檔名要跟 Label 一致）：nova 排程 > ~/Library/LaunchAgents/{標籤}.plist",
                f"# 裝上去：launchctl load ~/Library/LaunchAgents/{標籤}.plist",
                f"# 拆掉：  launchctl unload ~/Library/LaunchAgents/{標籤}.plist",
                "# nova 不會自己裝——裝上去是你系統上的狀態，那是你的決定。",
            ]
        ),
        file=sys.stderr,
    )
    return 放行


def _子命令_秘密(參數: argparse.Namespace) -> int:
    """祕密檔在哪、載得到哪幾個鍵。**只印路徑與鍵名，一個值都不印。**

    印值的話這個子命令自己就變成洩漏管道——而它存在的理由是讓人查得動
    「為什麼子程序沒拿到憑證」，那個問題只需要鍵名。
    """
    專案 = _專案脈絡(參數).根目錄
    路徑 = 祕密檔(專案)
    print(f"祕密檔：{路徑}")
    if not 路徑.is_file():
        print("  （沒有。要載入憑證就寫一份 KEY=VALUE，然後 chmod 600）")
        return 放行
    try:
        鍵們 = sorted(載入到({}, 專案=專案))
    except 看不懂的祕密檔 as 錯:
        print(f"  {錯}", file=sys.stderr)
        return 阻擋
    print(f"  載得到 {len(鍵們)} 個鍵：{'、'.join(鍵們)}")
    return 放行


def _印還在跑的(帳本目錄: Path) -> None:
    """把「發出去了但沒寫下結果」的執行列出來。**沒有就一個字都不印。**

    每次都印一行「還在跑 0 筆」會讓真的有事那一次被忽略。

    **分不出「還在跑」與「被殺掉」是刻意的**：兩者在帳本上長得一模一樣，
    而硬猜（去看 pid 還在不在）會在跨機器、跨重開機的時候說謊。
    多久了交給人判斷，所以起始時間一定要印。
    """
    跑著的 = 還在跑的有哪些(帳本目錄)
    if not 跑著的:
        return
    print(f"  還在跑 {len(跑著的)} 筆（有發出去、還沒寫下結果）：")
    for 一筆 in 跑著的:
        家 = "、".join(一筆.家們) or "還沒叫到模型"
        print(f"    {一筆.執行識別碼}  {家}  起 {一筆.起}")


def _子命令_狀態(參數: argparse.Namespace) -> int:
    """現在怎麼樣，以及**有什麼需要你**。

    無人看管跑起來之後，最貴的不是失敗，是看不出來失敗過。排程醒來的
    絕大多數（收件匣空的、被預算鎖擋下、撞到單例鎖）在事件帳本與成果帳上
    **一筆都不會留**，所以「排程到底有沒有在跑」今天只能去翻 launchd 的 log
    ——而那份 log 沒有人在看。

    **還沒有狀態不是錯誤**，回 0。回非零的話狀態列會一直閃紅。
    """
    脈絡 = _專案脈絡(參數)
    專案 = 脈絡.根目錄
    路徑 = 狀態檔(專案)
    print(f"狀態檔：{路徑}")
    現 = 讀現況(路徑)
    if 現 is None:
        print("  （還沒醒來過。跑一次 nova 跑 或 nova 工作流 --從收件匣 就會有）")
    else:
        _印上次醒來(現)
        _印佇列(脈絡)
    # **不管醒來過沒有都要印。** 背景派出去的活跟「排程有沒有醒過」無關——
    # 提早 return 的話，第一次用 nova 的人派了一份研究出去卻什麼都看不到。
    _印還在跑的(脈絡.帳本)
    return 放行


def _印上次醒來(現: 現況) -> None:
    print(f"  上次醒來 {現.上次醒來}：{形容(現.上次結果)}（退出碼 {現.上次退出碼}）")
    if 現.上次理由:
        print(f"    {現.上次理由}")
    if 現.上次執行識別碼:
        print(f"    帳在 nova 帳本 {現.上次執行識別碼}")


def _印佇列(脈絡: 專案執行脈絡) -> None:
    匣 = 脈絡.收件
    處理中 = 脈絡.處理中
    卡住的 = len([路 for 路 in 處理中.glob("*") if 路.is_file()]) if 處理中.is_dir() else 0
    print(f"  佇列上 {len(待處理(匣))} 件")
    if 卡住的:
        # **需要你的那一格。** `處理中/` 裡的不自動放回佇列（可能做了一半，
        # 重跑會把副作用再做一次），所以只能靠人決定。
        print(f"  ⚠ 卡住的 {卡住的} 件——收下了卻沒收尾，看 nova 收件")


def _子命令_收件(參數: argparse.Namespace) -> int:
    """看收件匣：丟一個檔進去就是派一次工，檔案內容就是題目。

    **這一格只讀不跑。** 要跑是 `nova 工作流 --從收件匣`——另外開一條執行路徑
    的話，預算、判準、歸檔就會有兩份，而兩份遲早會不一樣。
    """
    脈絡 = _專案脈絡(參數)
    目錄 = 脈絡.收件
    等著的 = 待處理(目錄)
    處理中目錄 = 脈絡.處理中
    處理中 = sorted(處理中目錄.glob("*")) if 處理中目錄.is_dir() else []
    print(f"收件匣：{目錄}")
    if not 等著的 and not 處理中:
        print("  （空的。丟一個檔進去就是派一次工，檔案內容就是題目）")
        return 放行
    for 路 in 等著的:
        print(f"  等著  {路.name}")
    for 路 in 處理中:
        # 留在這裡的是「收下了但沒收尾」——多半是程序被殺掉。
        # **不自動放回佇列**：它可能已經做了一半，重跑會把副作用再做一次
        # （跟退出碼 3「腳本不准重跑」同一條規則）。
        print(f"  ⚠ 沒收尾  {路.name}（收下了但沒寫下結果，可能做了一半）")
    return 放行


def _跑收尾指令(根目錄: Path, *指令: str, 逾時秒: float | None = None) -> tuple[int, str]:
    """在專案裡跑一個收尾指令，回傳 nova 退出碼與輸出。"""
    try:
        結果 = subprocess.run(  # noqa: S603 —— 收尾指令由這個節點固定組出
            list(指令),
            cwd=根目錄,
            capture_output=True,
            text=True,
            check=False,
            timeout=逾時秒,
        )
    except subprocess.TimeoutExpired:
        return 未知, f"指令等不到結果（{' '.join(指令)}）"
    except OSError as 錯:
        return 閘紅, f"指令跑不起來（{' '.join(指令)}）：{錯}"
    輸出 = (結果.stdout + 結果.stderr).strip()
    if 結果.returncode:
        return 閘紅, 輸出 or f"指令退出碼 {結果.returncode}：{' '.join(指令)}"
    return 放行, 輸出


def _跑並印收尾指令(根目錄: Path, *指令: str, 逾時秒: float | None = None) -> int:
    """跑一個收尾指令並印出它的輸出。"""
    碼, 輸出 = _跑收尾指令(根目錄, *指令, 逾時秒=逾時秒)
    if 輸出:
        print(輸出)
    return 碼


def _收尾閘(參數: argparse.Namespace, 根目錄: Path) -> int:
    """只跑提交閘；閘紅時不碰 git 與 gh。"""
    try:
        with _開帳(參數) as 帳:
            結果表 = 跑閘("提交", 建規則表(根目錄), 提前停止=True, 帳=帳)
    except (OSError, ValueError) as 錯:
        print(str(錯), file=sys.stderr)
        return 閘紅
    return _印結果(結果表)


def _子命令_收(參數: argparse.Namespace) -> int:
    """確定性收尾：閘 → commit → push → PR → required CI → merge。"""
    根 = _專案脈絡(參數).根目錄
    if (碼 := _收尾閘(參數, 根)) != 放行:
        return 碼

    訊息 = 參數.訊息 or " ".join(參數.提交訊息) or "nova：收尾"
    for 指令 in (
        ("git", "add", "-A"),
        ("git", "commit", "-m", 訊息),
        ("git", "push", "--set-upstream", "origin", "HEAD"),
        ("gh", "pr", "create", "--title", 訊息, "--body", 訊息),
    ):
        if (碼 := _跑並印收尾指令(根, *指令)) != 放行:
            return 碼

    if (
        碼 := _跑並印收尾指令(根, "gh", "pr", "checks", "--required", "--watch", 逾時秒=參數.等CI秒)
    ) != 放行:
        return 碼

    return _跑並印收尾指令(
        根,
        "gh",
        "pr",
        "merge",
        "--squash",
        "--delete-branch",
    )


def _子命令_帳本(參數: argparse.Namespace) -> int:
    """看帳本：不給識別碼就列出最近幾次，給了就看那一次。

    **有讀取端才算補了證據**——只有寫端的帳本是寫檔案給沒人看。
    """
    # 讀端也要按專案：在哪個專案下指令，就看那個專案的帳。
    目錄 = _帳本目錄(參數)
    if 參數.規則:
        return _印規則報表(統計規則(目錄), 目錄)
    檔們 = 列出執行(目錄)
    if 參數.執行識別碼:
        對的 = [檔 for 檔 in 檔們 if 檔.stem == 參數.執行識別碼]
        if not 對的:
            print(f"找不到 {參數.執行識別碼}（在 {目錄}）", file=sys.stderr)
            return 阻擋
        print(_一次的細節(讀一次執行(對的[0])))
        if 參數.全文:
            print(_模型講了什麼(讀原始事件(對的[0])))
        return 放行
    if not 檔們:
        print(f"還沒有任何帳本（會寫在 {目錄}）")
        return 放行
    for 檔 in 檔們[: 參數.最近]:
        print(_一行摘要(讀一次執行(檔)))
    return 放行


def _模型講了什麼(事件們: list[dict[str, Any]]) -> str:
    """把每一次呼叫講的話印出來。**遮罩過的**——`遮掉幾處` 一起印。

    少了那個數字，「這是原文」跟「這裡缺了三塊」長得一模一樣。
    """
    行們: list[str] = []
    for 事 in 事件們:
        文 = 事.get("text")
        if not isinstance(文, str):
            continue
        註 = []
        if 事.get("redactions"):
            註.append(f"遮掉 {事['redactions']} 處")
        if 事.get("text_truncated"):
            註.append(f"截斷（原本 {事.get('text_len')} 字）")
        抬頭 = f"── 呼叫 {事.get('call')} · {事.get('family')}"
        if 註:
            抬頭 += "（" + "、".join(註) + "）"
        行們.append(f"{抬頭}\n{文}")
    return "\n\n".join(行們) or "（這次沒有記全文——可能用了 --不記全文，或這次沒有模型呼叫）"


def _一行摘要(摘: 摘要) -> str:
    家們 = "、".join(f"{家.供應商}×{家.次數}" for 家 in 摘.各家) or "沒有模型呼叫"
    成本 = f" · US${摘.總成本美金:.4f}" if 摘.總成本美金 is not None else ""
    警告 = ""
    if 摘.沒收尾的呼叫:
        警告 += f" ⚠ {len(摘.沒收尾的呼叫)} 筆沒收尾"
    if 摘.壞掉的行:
        警告 += f" ⚠ {摘.壞掉的行} 行讀不動"
    return f"{摘.執行識別碼}  {家們}  {摘.總token} token{成本}{警告}"


def _一次的細節(摘: 摘要) -> str:
    行們 = [f"執行 {摘.執行識別碼}", f"  時間  {摘.起} → {摘.迄}"]
    行們.extend(
        f"  {家.供應商:<8}{家.次數} 次（成功 {家.成功} / 失敗 {家.失敗} / 未知 {家.未知}）"
        f" · {家.輸入token}→{家.輸出token} token"
        # 不印的話 claude 那列會顯示成「12→2285 token」而實際花了 21 美分——
        # 帳面上看起來幾乎免費，派工決策就會建立在那個數字上。
        f"{f'（＋快取讀取 {家.快取讀取token}）' if 家.快取讀取token else ''}"
        f"{f' · US${家.成本美金:.4f}' if 家.成本美金 is not None else ''}"
        for 家 in 摘.各家
    )
    if 摘.階段們:
        行們.append("  階段  " + " → ".join(摘.階段們))
    成本 = f" · US${摘.總成本美金:.4f}" if 摘.總成本美金 is not None else ""
    行們.append(f"  總計  {摘.總token} token{成本}")
    if 摘.沒收尾的呼叫:
        編號 = "、".join(str(號) for 號 in 摘.沒收尾的呼叫)
        行們.append(f"  ⚠ 沒收尾的呼叫：{編號}——發出去了但沒寫下結果，可能做了一半")
    if 摘.壞掉的行:
        行們.append(f"  ⚠ 有 {摘.壞掉的行} 行讀不動（證據不完整，不等於事情沒發生）")
    return "\n".join(行們)


#: 要跑過幾次才敢說「這條從來不紅」。**沒有這個下限，報表第一天就會誤導人**：
#: 跑過兩次沒紅根本不是證據，而「刪除候選」是個很有份量的標籤。
#: 20 是保守的起點，不是算出來的——真要調就等有幾百次資料再回頭看分布。
規則樣本下限 = 20


def _印規則報表(條們: tuple[一條規則的帳, ...], 目錄: Path) -> int:
    """跨執行的規則觸發率。

    **從來不紅的要主動標出來**，不要讓人自己看數字——但**樣本不夠就不准下結論**。
    """
    if not 條們:
        print(f"還沒有任何規則紀錄（會寫在 {目錄}）")
        return 放行
    for 條 in sorted(條們, key=lambda 條: (-條.紅過, 條.規則)):
        print(f"{條.規則:<18}{條.閘點:<6}跑過 {條.跑過:>4} 次 · 紅過 {條.紅過:>4} 次{_評語(條)}")
    return 放行


def _評語(條: 一條規則的帳) -> str:
    if 條.紅過:
        return ""
    if 條.跑過 < 規則樣本下限:
        return f"  ← 還沒紅過，但只跑過 {條.跑過} 次，不夠下結論"
    return "  ← 從來沒紅（刪除候選）"


def _子命令_生圖(參數: argparse.Namespace) -> int:
    """叫 agy 生一張圖，並且**自己確認檔案真的在**。

    沒有權限旗標是刻意的：可編輯下這條路會靜默假成功
    （見 `src/nova/載體/生圖.py` 的模組 docstring）。
    """
    try:
        描述 = 讀提示(argv片段=參數.描述, 提示檔=參數.提示檔)
    except (提示走錯路, OSError) as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    if not 描述.strip():
        print("沒有描述可以生（用參數給，或從 stdin 餵）", file=sys.stderr)
        return 阻擋
    目錄 = _專案脈絡(參數).根目錄
    try:
        with _開帳(參數) as 帳:
            果 = 生圖(
                描述,
                工作目錄=目錄,
                帳=帳,
                選項=生圖選項(
                    執行檔=Path(參數.執行檔) if 參數.執行檔 else None,
                    逾時秒=參數.逾時,
                    續接=參數.續接,
                ),
            )
    except (ValueError, FileNotFoundError) as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    for 圖 in 果.圖檔:
        print(圖)
    print(_摘要(生圖那家, 果.答), file=sys.stderr)
    if not 果.圖檔:
        print(果.答.文字.splitlines()[0], file=sys.stderr)
    return _終局的退出碼[果.答.終局]


def _子命令_額度(參數: argparse.Namespace) -> int:
    """查詢 codex 與 agy 額度並寫入快取。"""

    def _回報(家: 家族額度) -> None:
        if 家.失敗原因:
            sys.stderr.write(f"[{家.家}] 失敗：{家.失敗原因}\n")
        else:
            sys.stderr.write(f"[{家.家}] 成功取得額度\n")

    快照 = 額度(最舊秒=參數.最舊, 每家=_回報)
    return 0 if all(家.失敗原因 is None for 家 in 快照.家族們) else 1


#: 子命令 → 處理函式。**唯一的登記來源**：名字在剖析器宣告、處理函式在這裡，
#: 由 `建剖析器` 在宣告的當下綁起來。少一格會在建剖析器時就炸。
處理們: dict[str, 處理型] = {
    "閘": _子命令_閘,
    "檢查指令": _子命令_檢查指令,
    "檢查編輯": _子命令_檢查編輯,
    "繞過": _子命令_繞過,
    "檢查提交訊息": _子命令_檢查提交訊息,
    "問": _子命令_問,
    "重構": _子命令_重構,
    "工作流": _子命令_工作流,
    "跑": _子命令_跑,
    "排程": _子命令_排程,
    "秘密": _子命令_秘密,
    "狀態": _子命令_狀態,
    "線": 執行線,
    "收件": _子命令_收件,
    "收": _子命令_收,
    "帳本": _子命令_帳本,
    "已處理": _子命令_已處理,
    "生圖": _子命令_生圖,
    "額度": _子命令_額度,
}


def 主程式(argv: list[str] | None = None) -> int:
    """進入點。回傳退出碼：0 放行、1 閘紅／確定失敗、2 阻擋、3 結果未知。"""
    參數 = 建剖析器(處理們).parse_args(argv)
    _專案脈絡(參數)
    return int(參數.執行(參數))


if __name__ == "__main__":
    sys.exit(主程式())

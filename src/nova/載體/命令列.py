"""nova 的命令列介面：所有執行點唯一的入口。

pre-commit、CI、agent 的 hook 全部呼叫這裡的同一支程式，所以換模型、換工具，
受到的約束完全一樣。設定檔裡只准放一行呼叫，不准塞邏輯——設定檔沒辦法測試。

退出碼：0 放行／成功、1 閘紅／確定失敗、2 阻擋（agent hook 的約定）、3 結果未知。
"""

import argparse
import dataclasses
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from nova.契約.工作流 import (
    任務,
    停止條件,
    執行器,
    步驟結果,
    結束代碼,
    階段定義,
    預設最多token,
    預設最多步數,
)
from nova.契約.帳本 import 一條規則的帳, 摘要
from nova.契約.模型回應 import 回應, 終局
from nova.契約.檢查結果 import 檢查結果
from nova.契約.派工 import 工作種類
from nova.契約.角色 import 呼叫選項, 權限, 語言模型, 預設逾時秒
from nova.載體.判準 import 判準指令, 在哪跑, 建判準
from nova.載體.帳本 import 不記帳本, 帳本, 開帳本, 預設帳本目錄
from nova.載體.帳本讀取 import 列出執行, 統計規則, 讀一次執行
from nova.載體.模型.接力 import 接力腦
from nova.載體.模型.記帳 import 記帳每一顆
from nova.載體.模型.轉接 import 家族, 建立或缺席
from nova.載體.殘骸 import 加上寫檔指示, 撿回殘骸
from nova.載體.派工表 import 怎麼派
from nova.載體.生圖 import 生圖, 生圖選項, 生圖那家
from nova.載體.禁令 import 檢查指令
from nova.載體.規則表 import 建規則表
from nova.載體.角色 import 固定提示角色
from nova.載體.語言 import 找非繁體字
from nova.載體.閘 import 跑閘
from nova.載體.階段記帳 import 記帳執行器
from nova.迴圈 import 角色提示
from nova.迴圈.工作流 import 建TDD執行器, 跑工作流

放行, 閘紅, 阻擋 = 0, 1, 2
# 結果未知要跟確定失敗分開，腳本才知道「這個不准重跑」。
未知 = 3
_終局的退出碼 = {終局.成功: 放行, 終局.確定失敗: 閘紅, 終局.結果未知: 未知}


def _印結果(結果表: list[檢查結果]) -> int:
    for 結果 in 結果表:
        記號 = "綠" if 結果.通過 else "紅"
        print(f"[{記號}] {結果.代碼:<16} {結果.名稱}")
        if not 結果.通過:
            print(f"       負責層：{結果.負責層}")
            for 行 in 結果.證據.splitlines()[:20]:
                print(f"       {行}")
    紅的 = [結果.代碼 for 結果 in 結果表 if not 結果.通過]
    if 紅的:
        print(f"\n閘紅：{'、'.join(紅的)}", file=sys.stderr)
        return 閘紅
    print(f"\n全部通過（{len(結果表)} 條）")
    return 放行


def _子命令_閘(參數: argparse.Namespace) -> int:
    根目錄 = Path(參數.根目錄).resolve()
    try:
        with _開帳(參數) as 帳:
            結果表 = 跑閘(參數.閘點, 建規則表(根目錄), 提前停止=not 參數.全部跑完, 帳=帳)
    except ValueError as 錯:
        print(str(錯), file=sys.stderr)
        return 閘紅
    return _印結果(結果表)


def _取出指令(參數: argparse.Namespace) -> tuple[str | None, str]:
    """回傳 (要檢查的指令, 錯誤訊息)。指令是 None 代表沒有東西要檢查。"""
    if not 參數.stdin:
        return " ".join(參數.命令), ""
    try:
        載荷 = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as 錯:
        return None, f"stdin 不是合法 JSON（{錯}）——讀不懂就不放行"
    工具輸入 = 載荷.get("tool_input") or 載荷
    指令 = 工具輸入.get("command")
    return (指令 if isinstance(指令, str) else None), ""


def _子命令_檢查指令(參數: argparse.Namespace) -> int:
    指令, 錯誤 = _取出指令(參數)
    if 錯誤:
        print(錯誤, file=sys.stderr)
        return 阻擋
    if not 指令:
        return 放行
    通過, 原因 = 檢查指令(指令)
    if 通過:
        return 放行
    print(f"nova 阻擋：{原因}", file=sys.stderr)
    return 阻擋


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


def _子命令_問(參數: argparse.Namespace) -> int:
    """把一件事委派給別家 LLM CLI。

    這是統一介面的第一個真實呼叫端——用 codex／agy 接手工作，
    分擔 Claude 的壓力與使用額度。
    """
    提示 = " ".join(參數.提示) if 參數.提示 else sys.stdin.read()
    if not 提示.strip():
        print("沒有提示可以問（用參數給，或從 stdin 餵）", file=sys.stderr)
        return 阻擋
    挑法 = _挑腦(參數)
    if 挑法 is None:
        return 阻擋
    用, 模 = 挑法
    可以做什麼 = _挑權限(參數)
    屍 = Path(參數.輸出檔) if 參數.輸出檔 else None
    if 屍 is not None:
        if 可以做什麼 is 權限.唯讀:
            print("--輸出檔 要它寫檔，就得給 --可編輯（或 --全開）", file=sys.stderr)
            return 阻擋
        提示 = 加上寫檔指示(提示, 屍)
    try:
        with _開帳(參數) as 帳:
            答 = _建腦(用, Path(參數.執行檔) if 參數.執行檔 else None, 帳).詢問(
                提示,
                選項=呼叫選項(
                    模型=模,
                    工作目錄=Path(參數.工作目錄) if 參數.工作目錄 else None,
                    逾時秒=參數.逾時,
                    權限=可以做什麼,
                    隔離設定=not 參數.不隔離設定,
                    續接=參數.續接,
                    保留對話=參數.保留對話 or bool(參數.續接),
                ),
            )
    except (ValueError, FileNotFoundError) as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    if 屍 is not None:
        答 = 撿回殘骸(答, 屍)
    if 參數.json:
        # 原始輸出是行程內的逃生艙，不往 CLI 吐——它可能有上千行事件。
        證據 = {鍵: 值 for 鍵, 值 in dataclasses.asdict(答).items() if 鍵 != "原始輸出"}
        print(json.dumps(證據, ensure_ascii=False, indent=2))
    else:
        print(答.文字)
    print(_摘要(用, 答), file=sys.stderr)
    return _終局的退出碼[答.終局]


def _挑腦(參數: argparse.Namespace) -> tuple[str, str | None] | None:
    """決定這次用哪條鏈、哪顆模型。回 None ＝ 參數矛盾，呼叫端該退出。

    `--工作` 查派工表（策略寫在表裡不是寫在我腦裡）；`--用` 是手動指定。
    **兩個都給是矛盾不是「其中一個優先」**——猜一個會讓策略被無聲推翻。
    """
    if 參數.工作 and (參數.用 or 參數.模型):
        print("--工作 已經決定了要用誰跟哪顆模型，不要同時給 --用 或 --模型", file=sys.stderr)
        return None
    if 參數.工作:
        派 = 怎麼派(工作種類(參數.工作))
        return ",".join(派.腦們), 派.模型
    if not 參數.用:
        print("要給 --用（哪一家）或 --工作（照派工表挑）", file=sys.stderr)
        return None
    return 參數.用, 參數.模型


def _挑權限(參數: argparse.Namespace) -> 權限:
    """全開蓋過可編輯。兩個都沒給就是唯讀——忘了設不會變成放行。"""
    if 參數.全開:
        return 權限.全開
    return 權限.可編輯 if 參數.可編輯 else 權限.唯讀


def _建腦(來源: str, 執行檔: Path | None, 帳: 帳本) -> 語言模型:
    """`--用 codex,agy` 就是接力：前一顆失敗換下一顆。

    **記帳包在接力鏈裡面**——包在外面的話換腦這件事整個消失。
    """
    家們 = [家.strip() for 家 in 來源.split(",") if 家.strip()]
    if not 家們:
        訊息 = "至少要指定一家"
        raise ValueError(訊息)
    # 少裝一家不該讓整串垮掉（見 `缺席腦`）。只指定一家卻沒裝則當場炸。
    原始 = tuple(建立或缺席(cast(家族, 家), 執行檔=執行檔, 可以缺席=len(家們) > 1) for 家 in 家們)
    腦們 = 記帳每一顆(原始, 帳)
    return 腦們[0] if len(腦們) == 1 else 接力腦(名稱="→".join(家們), 腦們=腦們)


def _建角色(
    來源: str, 執行檔: str | None, 系統提示: str, 可以做什麼: 權限, 帳: 帳本
) -> 固定提示角色:
    腦 = _建腦(來源, Path(執行檔) if 執行檔 else None, 帳)
    return 固定提示角色(名稱=腦.名稱, 系統提示=系統提示, 腦=腦, 權限=可以做什麼)


@contextmanager
def _開帳(參數: argparse.Namespace) -> Iterator[帳本]:
    """CLI **預設記帳**：它是程式不是函式庫，程式留執行紀錄是正常的。

    而且 opt-in 的帳本等於沒有帳本——真的需要事後追查的那次，
    通常就是沒想到要先打開它的那次。用 `--不記帳` 關掉。

    預設落在 `預設帳本目錄()`，**刻意不在任何 repo 裡**：落在工作目錄的話，
    被 nova 驅動的模型會順手把它 commit 進去。
    """
    if 參數.不記帳:
        yield 不記帳本()
        return
    目錄 = Path(參數.帳本目錄) if 參數.帳本目錄 else 預設帳本目錄()
    with 開帳本(目錄) as 帳:
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


def _子命令_工作流(參數: argparse.Namespace) -> int:
    """跑一輪 TDD：測試 → 驗證紅 → 實作 → 驗證綠 → 審查。

    `--審查用` 必須跟 `--用` 不同家——自己審自己等於沒審（硬規則 4）。
    """
    做事的 = {家.strip() for 家 in 參數.用.split(",") if 家.strip()}
    審查的 = {家.strip() for 家 in 參數.審查用.split(",") if 家.strip()}
    if 做事的 & 審查的:
        重疊 = "、".join(sorted(做事的 & 審查的))
        print(f"審查要換一顆腦：{重疊} 同時出現在 --用 與 --審查用", file=sys.stderr)
        return 阻擋
    工作目錄 = 在哪跑(參數.工作目錄)
    描述 = " ".join(參數.任務) if 參數.任務 else sys.stdin.read()
    if not 描述.strip():
        print("沒有任務可以做（用參數給，或從 stdin 餵）", file=sys.stderr)
        return 阻擋

    try:
        with _開帳(參數) as 帳:
            執行 = 建TDD執行器(
                測試=_建角色(參數.用, 參數.執行檔, 角色提示.測試員, 權限.可編輯, 帳),
                實作=_建角色(參數.用, 參數.執行檔, 角色提示.實作員, 權限.可編輯, 帳),
                審查=_建角色(參數.審查用, None, 角色提示.審查員, 權限.唯讀, 帳),
                跑判準=建判準(判準指令(參數.判準)),
            )
            果 = 跑工作流(
                任務(描述=描述, 工作目錄=工作目錄),
                執行一步=記帳執行器(_邊跑邊印(執行), 帳),
                停止=停止條件(最多步數=參數.最多步數, 最多token=參數.最多token),
            )
    except (ValueError, FileNotFoundError) as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    for 步 in 果.軌跡:
        print(f"[{步.階段.value}] {步.終局.value}\n{步.證據}\n")
    print(f"\n{果.結束.代碼.value}：{果.結束.原因}", file=sys.stderr)
    if 果.結束.代碼 is 結束代碼.完成:
        return 放行
    有未知 = any(步.終局 is 終局.結果未知 for 步 in 果.軌跡)
    return 未知 if 有未知 else 閘紅


def _子命令_帳本(參數: argparse.Namespace) -> int:
    """看帳本：不給識別碼就列出最近幾次，給了就看那一次。

    **有讀取端才算補了證據**——只有寫端的帳本是寫檔案給沒人看。
    """
    目錄 = Path(參數.帳本目錄) if 參數.帳本目錄 else 預設帳本目錄()
    if 參數.規則:
        return _印規則報表(統計規則(目錄), 目錄)
    檔們 = 列出執行(目錄)
    if 參數.執行識別碼:
        對的 = [檔 for 檔 in 檔們 if 檔.stem == 參數.執行識別碼]
        if not 對的:
            print(f"找不到 {參數.執行識別碼}（在 {目錄}）", file=sys.stderr)
            return 阻擋
        print(_一次的細節(讀一次執行(對的[0])))
        return 放行
    if not 檔們:
        print(f"還沒有任何帳本（會寫在 {目錄}）")
        return 放行
    for 檔 in 檔們[: 參數.最近]:
        print(_一行摘要(讀一次執行(檔)))
    return 放行


def _一行摘要(摘: 摘要) -> str:
    家們 = "、".join(f"{家.供應商}×{家.次數}" for 家 in 摘.各家) or "沒有模型呼叫"
    警告 = ""
    if 摘.沒收尾的呼叫:
        警告 += f" ⚠ {len(摘.沒收尾的呼叫)} 筆沒收尾"
    if 摘.壞掉的行:
        警告 += f" ⚠ {摘.壞掉的行} 行讀不動"
    return f"{摘.執行識別碼}  {家們}  {摘.總token} token{警告}"


def _一次的細節(摘: 摘要) -> str:
    行們 = [f"執行 {摘.執行識別碼}", f"  時間  {摘.起} → {摘.迄}"]
    行們.extend(
        f"  {家.供應商:<8}{家.次數} 次（成功 {家.成功} / 失敗 {家.失敗} / 未知 {家.未知}）"
        f" · {家.輸入token}→{家.輸出token} token"
        for 家 in 摘.各家
    )
    if 摘.階段們:
        行們.append("  階段  " + " → ".join(摘.階段們))
    行們.append(f"  總計  {摘.總token} token")
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
    描述 = " ".join(參數.描述) if 參數.描述 else sys.stdin.read()
    if not 描述.strip():
        print("沒有描述可以生（用參數給，或從 stdin 餵）", file=sys.stderr)
        return 阻擋
    目錄 = 在哪跑(參數.工作目錄)
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


def 建剖析器() -> argparse.ArgumentParser:
    """建出 nova 的參數剖析器。抽出來是為了讓測試能不啟動程序就檢查介面。

    子命令按用途分三組加進去：**拆開不是為了好看，是 ruff `PLR0915` 會紅**
    （一個函式 50 個語句），而那條規則說的是對的——一長串平鋪的
    `add_argument` 沒有人讀得完。
    """
    剖析器 = argparse.ArgumentParser(prog="nova", description="nova：把規則降到載體層執行")
    剖析器.add_argument("--根目錄", default=".", help="要檢查的 repo 根目錄")
    子 = 剖析器.add_subparsers(dest="子命令", required=True)
    _加檢查類(子)
    _加委派類(子)
    _加觀測類(子)
    return 剖析器


def _加檢查類(子: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """閘、檢查指令、檢查提交訊息——**不叫模型**的那些。"""
    閘剖析 = 子.add_parser("閘", help="在某個執行點上跑規則")
    閘剖析.add_argument("閘點", help="提交 或 ci")
    閘剖析.add_argument(
        "--全部跑完", action="store_true", help="不提前停止，一次看到所有紅的（CI 用）"
    )
    閘剖析.add_argument(
        "--帳本目錄", default=None, help="帳本寫到哪。預設 ~/.local/state/nova/帳本"
    )
    閘剖析.add_argument("--不記帳", action="store_true", help="不要留執行紀錄")
    閘剖析.set_defaults(執行=_子命令_閘)

    指令剖析 = 子.add_parser("檢查指令", help="判斷一條 shell 指令是不是在繞過閘門")
    指令剖析.add_argument("命令", nargs="*", help="要檢查的指令字串")
    指令剖析.add_argument("--stdin", action="store_true", help="改從 stdin 讀 agent hook 的 JSON")
    指令剖析.set_defaults(執行=_子命令_檢查指令)

    訊息剖析 = 子.add_parser("檢查提交訊息", help="檢查 commit 訊息是不是繁體中文")
    訊息剖析.add_argument("檔案", help="commit 訊息檔（git 會傳 .git/COMMIT_EDITMSG）")
    訊息剖析.set_defaults(執行=_子命令_檢查提交訊息)


def _加委派類(子: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """問、工作流——把事情交給別家 LLM CLI。"""
    問剖析 = 子.add_parser("問", help="把一件事委派給別家 LLM CLI（分擔額度）")
    問剖析.add_argument("提示", nargs="*", help="要問的話。不給就從 stdin 讀")
    問剖析.add_argument(
        "--用",
        default=None,
        help="哪一家：claude、codex、agy。逗號分隔＝接力（前一顆失敗換下一顆）",
    )
    問剖析.add_argument(
        "--工作",
        default=None,
        choices=[種.value for 種 in 工作種類],
        help="照派工表自動挑腦：routine 給 agy（分擔額度）、reasoning 給 sol",
    )
    問剖析.add_argument("--模型", default=None, help="模型字串，原樣傳下去不翻譯")
    問剖析.add_argument("--執行檔", default=None, help="CLI 的絕對路徑。不給就自己找（不信 PATH）")
    問剖析.add_argument("--工作目錄", default=None, help="子程序的 cwd")
    問剖析.add_argument(
        "--逾時",
        type=float,
        default=預設逾時秒,
        help=f"幾秒沒回應就殺掉（預設 {預設逾時秒:.0f}）。砍太早會變成『結果未知』，那是不可回復的",
    )
    問剖析.add_argument("--json", action="store_true", help="輸出結構化證據而不是純文字")
    問剖析.add_argument(
        "--可編輯", action="store_true", help="讓它能改檔案（預設唯讀——忘了給不會變成放行）"
    )
    問剖析.add_argument(
        "--全開",
        action="store_true",
        help="跳過權限檢查並關掉沙箱。只在已經被隔離的環境裡用",
    )
    問剖析.add_argument("--續接", default=None, help="接回某段對話（給上一次輸出的 對話識別碼）")
    問剖析.add_argument(
        "--保留對話",
        action="store_true",
        help="把這段對話留在磁碟上，之後才續接得到（codex 預設不留）",
    )
    問剖析.add_argument(
        "--不隔離設定",
        action="store_true",
        help="讓它讀使用者家目錄的設定。claude 的 --bare 連 keychain 都不讀，訂閱登入要靠這個",
    )
    問剖析.add_argument(
        "--帳本目錄", default=None, help="帳本寫到哪。預設 ~/.local/state/nova/帳本"
    )
    問剖析.add_argument("--不記帳", action="store_true", help="不要留執行紀錄")
    問剖析.add_argument(
        "--輸出檔",
        default=None,
        help="叫它邊做邊寫進這個檔。逾時被殺之後還撿得回進度（要搭 --可編輯）",
    )
    問剖析.set_defaults(執行=_子命令_問)

    流剖析 = 子.add_parser("工作流", help="跑一輪 TDD：測試→驗證紅→實作→驗證綠→審查")
    流剖析.add_argument("任務", nargs="*", help="要做完的事。不給就從 stdin 讀")
    流剖析.add_argument("--用", required=True, help="測試員與實作員用哪一家。逗號分隔＝接力")
    流剖析.add_argument(
        "--審查用", required=True, help="審查員用哪一家。**必須跟 --用 不同**——自己審自己等於沒審"
    )
    流剖析.add_argument("--工作目錄", default=None, help="在哪裡工作。預設是現在這個目錄")
    流剖析.add_argument("--判準", default=None, help='判準指令，預設 "uv run pytest -q"')
    流剖析.add_argument("--執行檔", default=None, help="--用 那家 CLI 的絕對路徑")
    流剖析.add_argument(
        "--最多步數", type=int, default=預設最多步數, help="停止條件：走幾步就強制停"
    )
    流剖析.add_argument(
        "--最多token",
        type=int,
        default=預設最多token,
        help="停止條件：累計花到這麼多 token 就不再發下一次呼叫",
    )
    流剖析.add_argument(
        "--帳本目錄", default=None, help="帳本寫到哪。預設 ~/.local/state/nova/帳本"
    )
    流剖析.add_argument("--不記帳", action="store_true", help="不要留執行紀錄")
    流剖析.set_defaults(執行=_子命令_工作流)


def _加觀測類(子: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """帳本、生圖——看紀錄，以及只有 agy 有的那個能力。"""
    帳剖析 = 子.add_parser("帳本", help="看執行紀錄：誰被叫了、花多少、怎麼收場")
    帳剖析.add_argument("執行識別碼", nargs="?", default=None, help="不給就列出最近幾次")
    帳剖析.add_argument("--帳本目錄", default=None, help="從哪裡讀。預設 ~/.local/state/nova/帳本")
    帳剖析.add_argument("--最近", type=int, default=10, help="列出幾次（預設 10）")
    帳剖析.add_argument(
        "--規則",
        action="store_true",
        help="改看跨執行的規則觸發率：從來不紅的是刪除候選",
    )
    帳剖析.set_defaults(執行=_子命令_帳本)

    圖剖析 = 子.add_parser("生圖", help="叫 agy 生一張圖（三家裡只有它有）")
    圖剖析.add_argument("描述", nargs="*", help="要生什麼。不給就從 stdin 讀")
    圖剖析.add_argument("--工作目錄", default=None, help="圖要落在哪。預設是現在這個目錄")
    圖剖析.add_argument("--執行檔", default=None, help="agy CLI 的絕對路徑")
    圖剖析.add_argument("--逾時", type=float, default=預設逾時秒, help="秒。生圖比問話慢很多")
    圖剖析.add_argument(
        "--帳本目錄", default=None, help="帳本寫到哪。預設 ~/.local/state/nova/帳本"
    )
    圖剖析.add_argument("--不記帳", action="store_true", help="不要留執行紀錄")
    圖剖析.add_argument("--續接", default=None, help="接著改上一張圖（給上一次 stderr 印出的 sid）")
    圖剖析.set_defaults(執行=_子命令_生圖)


def 主程式(argv: list[str] | None = None) -> int:
    """進入點。回傳退出碼：0 放行、1 閘紅／確定失敗、2 阻擋、3 結果未知。"""
    參數 = 建剖析器().parse_args(argv)
    執行 = 參數.執行
    return int(執行(參數))


if __name__ == "__main__":
    sys.exit(主程式())

"""nova 的命令列介面：所有執行點唯一的入口。

pre-commit、CI、agent 的 hook 全部呼叫這裡的同一支程式，所以換模型、換工具，
受到的約束完全一樣。設定檔裡只准放一行呼叫，不准塞邏輯——設定檔沒辦法測試。

退出碼：0 放行、1 閘紅、2 阻擋（agent hook 的約定）。
"""

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from nova.契約.模型回應 import 回應
from nova.契約.檢查結果 import 檢查結果
from nova.載體.模型.轉接 import 建立
from nova.載體.禁令 import 檢查指令
from nova.載體.規則表 import 建規則表
from nova.載體.語言 import 找非繁體字
from nova.載體.閘 import 跑閘

放行, 閘紅, 阻擋 = 0, 1, 2


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
        結果表 = 跑閘(參數.閘點, 建規則表(根目錄), 提前停止=not 參數.全部跑完)
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
    if 答.執行成功:
        return f"[{家}] 完成 · {量}"
    return f"[{家}] 失敗 {答.失敗代碼}（結束碼 {答.原始結束碼}）· {量}"


def _子命令_問(參數: argparse.Namespace) -> int:
    """把一件事委派給別家 LLM CLI。

    這是統一介面的第一個真實呼叫端——用 codex／agy 接手工作，
    分擔 Claude 的壓力與使用額度。
    """
    try:
        模型 = 建立(參數.用, 執行檔=Path(參數.執行檔) if 參數.執行檔 else None)
    except (ValueError, FileNotFoundError) as 錯:
        print(str(錯), file=sys.stderr)
        return 阻擋
    提示 = " ".join(參數.提示) if 參數.提示 else sys.stdin.read()
    if not 提示.strip():
        print("沒有提示可以問（用參數給，或從 stdin 餵）", file=sys.stderr)
        return 阻擋

    答 = 模型.詢問(
        提示,
        模型=參數.模型,
        工作目錄=Path(參數.工作目錄) if 參數.工作目錄 else None,
        逾時秒=參數.逾時,
    )
    if 參數.json:
        # 原始輸出是行程內的逃生艙，不往 CLI 吐——它可能有上千行事件。
        證據 = {鍵: 值 for 鍵, 值 in dataclasses.asdict(答).items() if 鍵 != "原始輸出"}
        print(json.dumps(證據, ensure_ascii=False, indent=2))
    else:
        print(答.文字)
    print(_摘要(參數.用, 答), file=sys.stderr)
    return 放行 if 答.執行成功 else 閘紅


def 建剖析器() -> argparse.ArgumentParser:
    """建出 nova 的參數剖析器。抽出來是為了讓測試能不啟動程序就檢查介面。"""
    剖析器 = argparse.ArgumentParser(prog="nova", description="nova：把規則降到載體層執行")
    剖析器.add_argument("--根目錄", default=".", help="要檢查的 repo 根目錄")
    子 = 剖析器.add_subparsers(dest="子命令", required=True)

    閘剖析 = 子.add_parser("閘", help="在某個執行點上跑規則")
    閘剖析.add_argument("閘點", help="提交 或 ci")
    閘剖析.add_argument(
        "--全部跑完", action="store_true", help="不提前停止，一次看到所有紅的（CI 用）"
    )
    閘剖析.set_defaults(執行=_子命令_閘)

    指令剖析 = 子.add_parser("檢查指令", help="判斷一條 shell 指令是不是在繞過閘門")
    指令剖析.add_argument("命令", nargs="*", help="要檢查的指令字串")
    指令剖析.add_argument("--stdin", action="store_true", help="改從 stdin 讀 agent hook 的 JSON")
    指令剖析.set_defaults(執行=_子命令_檢查指令)

    訊息剖析 = 子.add_parser("檢查提交訊息", help="檢查 commit 訊息是不是繁體中文")
    訊息剖析.add_argument("檔案", help="commit 訊息檔（git 會傳 .git/COMMIT_EDITMSG）")
    訊息剖析.set_defaults(執行=_子命令_檢查提交訊息)

    問剖析 = 子.add_parser("問", help="把一件事委派給別家 LLM CLI（分擔額度）")
    問剖析.add_argument("提示", nargs="*", help="要問的話。不給就從 stdin 讀")
    問剖析.add_argument("--用", required=True, help="哪一家：claude、codex、agy")
    問剖析.add_argument("--模型", default=None, help="模型字串，原樣傳下去不翻譯")
    問剖析.add_argument("--執行檔", default=None, help="CLI 的絕對路徑。不給就自己找（不信 PATH）")
    問剖析.add_argument("--工作目錄", default=None, help="子程序的 cwd")
    問剖析.add_argument("--逾時", type=float, default=300.0, help="幾秒沒回應就殺掉")
    問剖析.add_argument("--json", action="store_true", help="輸出結構化證據而不是純文字")
    問剖析.set_defaults(執行=_子命令_問)

    return 剖析器


def 主程式(argv: list[str] | None = None) -> int:
    """進入點。回傳退出碼：0 放行、1 閘紅、2 阻擋。"""
    參數 = 建剖析器().parse_args(argv)
    執行 = 參數.執行
    return int(執行(參數))


if __name__ == "__main__":
    sys.exit(主程式())

"""nova 的命令列介面：所有執行點唯一的入口。

pre-commit、CI、agent 的 hook 全部呼叫這裡的同一支程式，所以換模型、換工具，
受到的約束完全一樣。設定檔裡只准放一行呼叫，不准塞邏輯——設定檔沒辦法測試。

退出碼：0 放行、1 閘紅、2 阻擋（agent hook 的約定）。
"""

import argparse
import json
import sys
from pathlib import Path

from nova.契約.檢查結果 import 檢查結果
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

    return 剖析器


def 主程式(argv: list[str] | None = None) -> int:
    """進入點。回傳退出碼：0 放行、1 閘紅、2 阻擋。"""
    參數 = 建剖析器().parse_args(argv)
    執行 = 參數.執行
    return int(執行(參數))


if __name__ == "__main__":
    sys.exit(主程式())

"""nova 的命令列參數剖析器。

把所有子命令的參數宣告集中在這裡，抽出來是為了讓測試能不啟動程序就檢查介面，
也讓命令列.py 專注在各子命令的執行邏輯與流程分派。
"""

import argparse
from collections.abc import Callable, Mapping

from nova.契約.工作流 import 階段代碼, 預設最多token, 預設最多步數
from nova.契約.派工 import 工作種類
from nova.契約.角色 import 預設逾時秒

#: 一個子命令的處理函式。`argparse.Namespace` → 退出碼。
處理型 = Callable[[argparse.Namespace], int]


def 建剖析器(處理們: Mapping[str, 處理型]) -> argparse.ArgumentParser:
    """建出 nova 的參數剖析器。抽出來是為了讓測試能不啟動程序就檢查介面。

    **處理函式由呼叫端傳進來**（依賴反轉），不是在這裡 import。
    這一層 import 命令列的話就是循環相依；而在命令列另設一張分派對照表
    會讓子命令的名字有**兩份**登記，漏掉一邊要到使用者真的打那個子命令
    才炸成 `KeyError`。傳進來就只有一份，而且少一格會在**這裡**就炸。

    子命令按用途分三組加進去：**拆開不是為了好看，是 ruff `PLR0915` 會紅**
    （一個函式 50 個語句），而那條規則說的是對的——一長串平鋪的
    `add_argument` 沒有人讀得完。
    """
    剖析器 = argparse.ArgumentParser(prog="nova", description="nova：把規則降到載體層執行")
    剖析器.add_argument("--根目錄", default=".", help="要檢查的 repo 根目錄")
    子 = 剖析器.add_subparsers(dest="子命令", required=True)
    _加檢查類(子, 處理們)
    _加委派類(子, 處理們)
    _加觀測類(子, 處理們)
    return 剖析器


def _加檢查類(
    子: "argparse._SubParsersAction[argparse.ArgumentParser]",
    處理們: Mapping[str, 處理型],
) -> None:
    """閘、檢查指令、檢查提交訊息——**不叫模型**的那些。"""
    閘剖析 = 子.add_parser("閘", help="在某個執行點上跑規則")
    閘剖析.set_defaults(執行=處理們["閘"])
    閘剖析.add_argument("閘點", help="提交 或 ci")
    閘剖析.add_argument(
        "--全部跑完", action="store_true", help="不提前停止，一次看到所有紅的（CI 用）"
    )
    閘剖析.add_argument(
        "--帳本目錄", default=None, help="帳本寫到哪。預設 ~/.local/state/nova/帳本"
    )
    閘剖析.add_argument("--不記帳", action="store_true", help="不要留執行紀錄")

    指令剖析 = 子.add_parser("檢查指令", help="判斷一條 shell 指令是不是在繞過閘門")
    指令剖析.set_defaults(執行=處理們["檢查指令"])
    指令剖析.add_argument("命令", nargs="*", help="要檢查的指令字串")
    指令剖析.add_argument("--stdin", action="store_true", help="改從 stdin 讀 agent hook 的 JSON")

    訊息剖析 = 子.add_parser("檢查提交訊息", help="檢查 commit 訊息是不是繁體中文")
    訊息剖析.set_defaults(執行=處理們["檢查提交訊息"])
    訊息剖析.add_argument("檔案", help="commit 訊息檔（git 會傳 .git/COMMIT_EDITMSG）")


def _加委派類(
    子: "argparse._SubParsersAction[argparse.ArgumentParser]",
    處理們: Mapping[str, 處理型],
) -> None:
    """問、工作流——把事情交給別家 LLM CLI。"""
    問剖析 = 子.add_parser("問", help="把一件事委派給別家 LLM CLI（分擔額度）")
    問剖析.set_defaults(執行=處理們["問"])
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
    問剖析.add_argument(
        "--熔斷",
        action="store_true",
        help="啟用跨執行熔斷（連續失敗時暫停呼叫該家）。預設關閉（看帳跟關流程是兩件事）",
    )

    流剖析 = 子.add_parser("工作流", help="跑一輪 TDD：測試→驗證紅→實作→驗證綠→審查")
    流剖析.set_defaults(執行=處理們["工作流"])
    流剖析.add_argument("任務", nargs="*", help="要做完的事。不給就從 stdin 讀")
    流剖析.add_argument(
        "--用",
        default=None,
        help="測試／實作／重構用哪一家。逗號分隔＝接力。不給就照派工表（例行＝agy 打頭）",
    )
    流剖析.add_argument(
        "--審查用",
        default=None,
        help="審查員用哪一家。必須跟 --用 不同。不給就照派工表（推理＝sol）",
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
    流剖析.add_argument(
        "--進度檔",
        default=None,
        help="跨輪的記憶：每跑完一階就寫進去，開跑前讀回來當前情。有模型全文，路徑自己挑",
    )
    流剖析.add_argument(
        "--起點",
        default=階段代碼.測試.value,
        choices=[代碼.value for 代碼 in 階段代碼],
        help="從哪個階段開始。refactor ＝ 只走重構流程（前提是本來就全綠）",
    )


def _加觀測類(
    子: "argparse._SubParsersAction[argparse.ArgumentParser]",
    處理們: Mapping[str, 處理型],
) -> None:
    """帳本、生圖、額度——看紀錄、生圖能力與查詢訂閱限額。"""
    帳剖析 = 子.add_parser("帳本", help="看執行紀錄：誰被叫了、花多少、怎麼收場")
    帳剖析.set_defaults(執行=處理們["帳本"])
    帳剖析.add_argument("執行識別碼", nargs="?", default=None, help="不給就列出最近幾次")
    帳剖析.add_argument("--帳本目錄", default=None, help="從哪裡讀。預設 ~/.local/state/nova/帳本")
    帳剖析.add_argument("--最近", type=int, default=10, help="列出幾次（預設 10）")
    帳剖析.add_argument(
        "--規則",
        action="store_true",
        help="改看跨執行的規則觸發率：從來不紅的是刪除候選",
    )

    圖剖析 = 子.add_parser("生圖", help="叫 agy 生一張圖（三家裡只有它有）")
    圖剖析.set_defaults(執行=處理們["生圖"])
    圖剖析.add_argument("描述", nargs="*", help="要生什麼。不給就從 stdin 讀")
    圖剖析.add_argument("--工作目錄", default=None, help="圖要落在哪。預設是現在這個目錄")
    圖剖析.add_argument("--執行檔", default=None, help="agy CLI 的絕對路徑")
    圖剖析.add_argument("--逾時", type=float, default=預設逾時秒, help="秒。生圖比問話慢很多")
    圖剖析.add_argument(
        "--帳本目錄", default=None, help="帳本寫到哪。預設 ~/.local/state/nova/帳本"
    )
    圖剖析.add_argument("--不記帳", action="store_true", help="不要留執行紀錄")
    圖剖析.add_argument("--續接", default=None, help="接著改上一張圖（給上一次 stderr 印出的 sid）")

    額度剖析 = 子.add_parser("額度", help="向 codex 與 agy 查詢限額並寫入狀態快取")
    額度剖析.set_defaults(執行=處理們["額度"])
    額度剖析.add_argument(
        "--最舊",
        type=float,
        default=0.0,
        metavar="秒",
        help="節流：快取比這麼多秒新就什麼都不做。不給就一律重新去問",
    )

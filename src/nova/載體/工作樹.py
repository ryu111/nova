"""工作樹隔離：並行的分支各自在自己的 git worktree 裡跑，互相看不到。

隔離的代價要講清楚：**分支只看得到已提交的狀態**。主工作區裡沒提交、
沒加進 index 的檔案，在工作樹裡不存在。這是隔離在做事，不是 bug——
但「任務依賴未提交的檔案」會因此神祕失敗，先在這裡寫明。
"""

from pathlib import Path

from nova.載體.git查詢 import 跑git

#: **`跑git` 要列進來**：mypy strict 的 `no_implicit_reexport` 之下，
#: 單純 import 進來的名字不算這個模組的公開屬性，測試 monkeypatch 它會紅。
#: 走 `__all__` 不走 `as 跑git`——後者會被 ruff 的 PLC0414 擋，
#: 而為了繞過它加 noqa 就得再去登記豁免，那條路比較長也比較沒說服力。
__all__ = ["收掉工作樹", "收集證據", "開一個工作樹", "跑git"]


def _跑git或報錯(工作目錄: Path, *參數: str, 出事時說: str) -> None:
    """跑一道 git，非零回傳碼就 raise，把 git 自己的 stderr 接在說明後面。

    這裡刻意不吞錯也不重試：這個模組的每一次失敗都代表「那個分支不該繼續跑」，
    呼叫端要的是當場炸掉，不是一個看起來成功的結果。
    """
    結果 = 跑git(工作目錄, *參數)
    if 結果.returncode != 0:
        訊息 = f"{出事時說}\n{結果.stderr.strip()}"
        raise OSError(訊息)


def 開一個工作樹(專案: Path, *, 落點: Path, 起點commit: str) -> Path:
    """在 `起點commit` 上開一個 detached 的 git worktree，回傳落點本身。

    起點是 commit 不是 HEAD：這樣它跟成果帳的 `rollback_point` 是同一個值，
    分支跑完回頭看「從哪裡長出來的」時兩邊對得起來。

    detached 是刻意的——不建分支就不會撞到「這個分支已經被別的 worktree 佔用」
    那種刪不掉的狀況。

    開不出來就 raise，**不准退回主工作區照跑**：靜默 fallback 是假隔離，
    比沒有隔離更糟，因為它看起來像有。開不出工作樹的分支就不要跑。
    """
    _跑git或報錯(
        專案, "worktree", "add", "--detach", str(落點), 起點commit, 出事時說=f"開不出工作樹：{落點}"
    )
    return 落點


def 收集證據(落點: Path) -> str:
    """把工作樹裡的改動抓成一份 diff，**含還沒被追蹤的新檔**。

    先 `add --intent-to-add` 再 diff 是關鍵：TDD 任務的產出常常整包都是新增的
    測試檔，光跑 `git diff` 一個字都看不到，那個分支的全部工作成果會從屏障的
    證據裡憑空消失。

    代價講清楚：`--intent-to-add` 會動到這個工作樹自己的 index，被登記的新檔
    從此算「有改動」。也就是說**收集過證據的工作樹就收不掉了**——`收掉工作樹`
    會拒絕它。這是刻意的副作用，不是疏忽：有產出的分支本來就該把現場留著，
    真的要收的是還沒動過、乾淨的工作樹。

    `core.quotepath=false` 也不能省：這個 repo 全是中文檔名，git 預設會把它們
    轉義成八進位，證據裡就找不到原本的路徑了。
    """
    跑git(落點, "add", "-A", "--intent-to-add")
    return 跑git(落點, "-c", "core.quotepath=false", "diff").stdout


def 收掉工作樹(落點: Path) -> None:
    """收掉一個跑完的工作樹。收不掉就 raise，**不加 `--force`**。

    `git worktree remove` 對還有改動或未追蹤檔的工作樹會拒絕，那是它的特性不是
    障礙：失敗的分支要把現場留著給人看，路徑就在例外訊息裡。硬 `--force` 過去
    等於把失敗現場當場銷毀。

    收證據要在收掉之前——見 `收集證據`。
    """
    _跑git或報錯(落點, "worktree", "remove", str(落點), 出事時說=f"收不掉工作樹，現場留在：{落點}")

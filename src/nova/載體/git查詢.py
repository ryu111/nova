"""跟 git 問話的共用出口。

所有規則都靠 git 決定「範圍」——被追蹤的檔案才算數。集中在這裡，
避免每條規則自己拼一次 subprocess 而拼得不一樣。
"""

import subprocess
from pathlib import Path


def 跑git(根目錄: Path, *參數: str) -> subprocess.CompletedProcess[str]:
    """在指定 repo 裡跑 git，不檢查回傳碼——呼叫端自己判讀。"""
    return subprocess.run(  # noqa: S603 —— 參數由規則表寫死，不吃外部輸入
        ["git", *參數],  # noqa: S607 —— 走 PATH 找 git 是刻意的，容器裡路徑不固定
        cwd=根目錄,
        capture_output=True,
        text=True,
        check=False,
    )


def 追蹤中的檔案(根目錄: Path) -> list[str]:
    r"""git 追蹤中的檔案清單。用它當掃描範圍就不必自己維護 .venv／快取的排除表。

    一定要用 `-z`：git 預設會把非 ASCII 檔名轉義成 `"src/\\347\\224\\262.py"`，
    這個 repo 全是中文檔名，不加 -z 會整個掃描範圍變成空的（靜默全綠，最危險的失敗）。
    """
    結果 = 跑git(根目錄, "ls-files", "-z")
    return [路徑 for 路徑 in 結果.stdout.split("\0") if 路徑]


def 會被忽略(根目錄: Path, 路徑: str) -> bool:
    """問 git 本人：這個路徑你會不會忽略？"""
    return 跑git(根目錄, "check-ignore", "-q", 路徑).returncode == 0


def 讀取版本(根目錄: Path, 路徑: str, *, ref: str = "HEAD") -> str | None:
    """讀某個 ref 上那一版的檔案內容；那一版沒有這個檔就回 None。"""
    結果 = 跑git(根目錄, "show", f"{ref}:{路徑}")
    return 結果.stdout if 結果.returncode == 0 else None


def ref存在(根目錄: Path, ref: str) -> bool:
    """這個 ref 指得到一個 commit 嗎？抓不到基準時要當場紅，不能默默退回跟自己比。"""
    return 跑git(根目錄, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}").returncode == 0


def ref裡的檔案(根目錄: Path, ref: str) -> list[str]:
    r"""某個 ref 上的檔案清單。

    跟 `追蹤中的檔案` 的差別很關鍵：那個看的是**工作區的 index**，
    所以 `git rm` 掉的檔案不會出現——拿它當基準會漏算被刪掉的東西（靜默全綠）。
    基準一律走這支。`-z` 的理由同 `追蹤中的檔案`。
    """
    結果 = 跑git(根目錄, "ls-tree", "-r", "--name-only", "-z", ref)
    return [路徑 for 路徑 in 結果.stdout.split("\0") if 路徑]

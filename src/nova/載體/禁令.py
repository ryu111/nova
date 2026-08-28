"""兩條禁令的機械化版本：不准繞過閘門。

這是**加速器不是保證**——agent 換掉、或直接在終端機打，這裡就攔不到。
真正的兜底是 CI 的 required check 與 GitHub ruleset（bypass 名單空的）。
"""

import shlex


def 檢查指令(命令: str) -> tuple[bool, str]:
    """判斷一條 shell 指令是不是在繞過閘門。回傳 (放行, 原因)。"""
    try:
        詞 = shlex.split(命令)
    except ValueError as 錯:
        return False, f"指令拆不開（{錯}）——拆不開就不放行（fail-closed）"

    詞集 = set(詞)

    if "--no-verify" in 詞集:
        return False, "禁令 --no-verify：繞過 pre-commit 快閘。要繞過閘門，先修閘門"

    if {"git", "commit"} <= 詞集 and "-n" in 詞集:
        return False, "禁令 git commit -n：`-n` 就是 `--no-verify` 的短寫"

    if "gh" in 詞集 and "merge" in 詞集 and "--admin" in 詞集:
        return False, "禁令 --admin：用管理員權限跳過 required check，等於自己拆掉執法點"

    return True, ""

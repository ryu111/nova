"""兩條禁令的機械化版本：不准繞過閘門。

這是**加速器不是保證**——agent 換掉、或直接在終端機打，這裡就攔不到。
真正的兜底是 CI 的 required check 與 GitHub ruleset（bypass 名單空的）。
"""

import shlex

#: 拆不開時用的關鍵詞掃描。這幾個字串夠獨特，直接在原文找不會誤傷。
_危險詞 = ("--no-verify", "--admin")


def _拆得開的判斷(詞集: set[str]) -> tuple[bool, str]:
    if "--no-verify" in 詞集:
        return False, "禁令 --no-verify：繞過 pre-commit 快閘。要繞過閘門，先修閘門"
    if {"git", "commit"} <= 詞集 and "-n" in 詞集:
        return False, "禁令 git commit -n：`-n` 就是 `--no-verify` 的短寫"
    if "gh" in 詞集 and "merge" in 詞集 and "--admin" in 詞集:
        return False, "禁令 --admin：用管理員權限跳過 required check，等於自己拆掉執法點"
    return True, ""


def _拆不開的判斷(命令: str) -> tuple[bool, str]:
    """`shlex` 拆不開時的退路：直接在原文找關鍵詞。

    **不硬擋**。硬擋看起來安全，實際上會把 heredoc、巢狀引號這種完全正常的
    指令全部誤擋掉——實測擋到過一次，而且擋在跟禁令毫無關係的地方。

    退成關鍵詞掃描不會變寬鬆：`--no-verify` 與 `--admin` 這種字串出現在
    原文裡就足以判定，反而比拆詞更容易命中（會多擋不會少擋）。
    唯一擋不住的是刻意混淆，而這裡的對象不是對手，是會手滑的執行者。
    """
    命中 = [詞 for 詞 in _危險詞 if 詞 in 命令]
    if 命中:
        return False, f"禁令 {命中[0]}（指令拆不開，退回關鍵詞掃描）：不准繞過閘門"
    return True, ""


def 檢查指令(命令: str) -> tuple[bool, str]:
    """判斷一條 shell 指令是不是在繞過閘門。回傳 (放行, 原因)。"""
    try:
        詞 = shlex.split(命令)
    except ValueError:
        return _拆不開的判斷(命令)
    return _拆得開的判斷(set(詞))

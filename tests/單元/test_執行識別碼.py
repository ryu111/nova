"""執行識別碼：誰生的、什麼形狀、父程序指定時要驗什麼。

## 為什麼要能被指定

`nova 問 --背景` 會重新發射一個子程序。父程序要印一個號碼給人看，
子程序要用一個號碼當帳本檔名——**那必須是同一個號碼**。
各編各的話，使用者拿到的識別碼在 `nova 帳本` 上查不到，
而那看起來像「帳沒記」，不像「號碼對不上」。

## 為什麼指定的要驗格式

`NOVA_RUN_ID` 是環境變數，環境變數會**殘留**。一個忘了清掉的值
會讓之後所有的執行共用同一個檔名——而帳本是 append 模式，
所以症狀不是報錯，是**兩次執行的事件交錯寫進同一個檔，靜默污染**。

fail-open（看不懂就自己生一個）而不是 fail-closed：這裡的失敗模式是
「少一個人為指定」，不是「放行了不該放行的事」，而炸掉會讓一個殘留的
環境變數把整個 CLI 弄到不能用。
"""

import re

import pytest

from nova.載體.帳本 import 指定識別碼的環境變數, 新執行識別碼

_形狀 = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{6}")


class Test自己生的:
    def test_形狀對(self) -> None:
        assert _形狀.fullmatch(新執行識別碼())

    def test_不會連兩次一樣(self) -> None:
        """尾巴的亂數就是為了同一秒不撞檔名。"""
        assert 新執行識別碼() != 新執行識別碼()


class Test父程序指定:
    def test_格式對就照用(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """**背景派工靠這條讓兩邊是同一個號碼。**"""
        monkeypatch.setenv(指定識別碼的環境變數, "20260830T012847Z-38fb89")

        assert 新執行識別碼() == "20260830T012847Z-38fb89"

    @pytest.mark.parametrize(
        "亂設的",
        [
            "",
            "隨便",
            "20260830T012847Z",  # 少了亂數段
            "20260830T012847Z-38FB89",  # 大寫十六進位不算
            "20260830T012847Z-38fb8",  # 少一位
            "20260830T012847Z-38fb890",  # 多一位
            "20260830T012847Z-38fb89/../別的地方",  # 想跑出目錄
            "2026-08-30T01:28:47Z-38fb89",  # 另一種時戳格式
        ],
    )
    def test_看不懂的一律自己生一個(self, 亂設的: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """**殘留的環境變數不准變成靜默的帳本污染。**

        帳本是 append 模式，撞檔名不會報錯——兩次執行的事件會交錯寫進
        同一個檔，而那是事後也修不回來的。
        """
        monkeypatch.setenv(指定識別碼的環境變數, 亂設的)

        生的 = 新執行識別碼()

        assert 生的 != 亂設的
        assert _形狀.fullmatch(生的)

    def test_不准夾帶路徑跑出去(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """識別碼會被當成檔名。**外面來的字串不准直接當路徑。**"""
        monkeypatch.setenv(指定識別碼的環境變數, "../../../etc/passwd")

        assert "/" not in 新執行識別碼()

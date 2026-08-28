"""角色 ＝ 固定的系統提示 ＋ 可換的腦。

最重要的一支是 `test_轉接器真的能當腦`：它證明「換腦」不是說說的——
三家 CLI 的轉接器在型別上真的裝得進 `語言模型` 這個洞。
"""

import dataclasses
from pathlib import Path

from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.契約.角色 import 角色, 語言模型
from nova.載體.模型.轉接 import 建立
from nova.載體.角色 import 固定提示角色, 組提示


class 假腦:
    名稱 = "假腦"

    def __init__(self) -> None:
        """記下收到的提示，好驗證系統提示真的被併進去了。"""
        self.收到: list[str] = []

    def 詢問(
        self,
        提示: str,
        *,
        模型: str | None = None,
        工作目錄: Path | None = None,
        逾時秒: float = 300.0,
    ) -> 回應:
        del 模型, 工作目錄, 逾時秒
        self.收到.append(提示)
        return 回應(
            文字="好",
            終局=終局.成功,
            失敗代碼=失敗代碼.無,
            原始結束碼=0,
            對話識別碼=None,
            用量=用量(輸入token=1, 輸出token=1),
        )


class Test組提示:
    def test_系統提示併在前面(self) -> None:
        """只有 claude 有 --system-prompt，codex 與 agy 沒有。

        走最小公倍數併進提示字串，三家收到的東西才一樣——換腦但行為一樣。
        """
        合 = 組提示("你是測試員", "幫我寫測試")
        assert 合.startswith("你是測試員")
        assert 合.endswith("幫我寫測試")

    def test_沒有系統提示就原樣回(self) -> None:
        assert 組提示("", "只有任務") == "只有任務"
        assert 組提示("   \n ", "只有任務") == "只有任務"


class Test固定提示角色:
    def test_每次都帶上系統提示(self) -> None:
        腦 = 假腦()
        角 = 固定提示角色(名稱="測試員", 系統提示="你只寫會紅的測試", 腦=腦)
        角.做("讓 X 變成 Y")
        角.做("再來一次")
        assert len(腦.收到) == 2
        assert all("你只寫會紅的測試" in 提示 for 提示 in 腦.收到)

    def test_是角色協定的實作(self) -> None:
        角 = 固定提示角色(名稱="測試員", 系統提示="x", 腦=假腦())
        assert isinstance(角, 角色)

    def test_不可變(self) -> None:
        角 = 固定提示角色(名稱="測試員", 系統提示="x", 腦=假腦())
        try:
            角.系統提示 = "被改了"  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            return
        msg = "角色的系統提示是它的身分，不准被改掉"
        raise AssertionError(msg)


class Test換腦:
    def test_假腦符合語言模型協定(self) -> None:
        assert isinstance(假腦(), 語言模型)

    def test_轉接器真的能當腦(self) -> None:
        """「換腦」的機械保證：三家 CLI 的轉接器都裝得進 `語言模型` 這個洞。

        mypy strict 會檢查簽章相容；這裡再用結構型檢查跑一次。
        """
        for 家 in ("claude", "codex", "agy"):
            轉接器 = 建立(家, 執行檔=Path("/不存在也沒關係"))
            assert isinstance(轉接器, 語言模型), f"{家} 的轉接器裝不進語言模型"

    def test_同一個角色換腦不換身分(self) -> None:
        """系統提示不變、腦換掉——這就是宿主反轉在這一層的樣子。"""
        甲, 乙 = 假腦(), 假腦()
        身分 = "你只寫會紅的測試"
        固定提示角色(名稱="測試員", 系統提示=身分, 腦=甲).做("任務")
        固定提示角色(名稱="測試員", 系統提示=身分, 腦=乙).做("任務")
        assert 甲.收到 == 乙.收到, "換腦之後角色收到的東西要一模一樣"

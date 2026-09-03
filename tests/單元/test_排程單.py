"""`nova 排程` 產生的 launchd 設定。

**nova 產生，人安裝。** 自動 `launchctl load` 下去的話，BTM（背景項目管理）
會留紀錄，unload 也清不乾淨——那是使用者系統上的狀態，不是 nova 的。
所以這一格只印出來。

命名照 `~/.claude/skills/bg-process-naming`：
- Label `com.nova.patrol`（專案就是 nova）／`com.nova.<專案>.patrol`（別的專案），
  全小寫 ASCII kebab
- **那條規則自己也住在 nova 裡**（`驗plist`）：合不合規這件事寫在宿主的 hook 腳本裡
  就是測不到，而且換掉宿主就一起消失
- `ProgramArguments[0]` **不准是直譯器或代跑工具**（`bash`、`python3`、`uv`…）
  ——「登入項目與延伸功能」只會顯示那個名字，完全看不出是誰的 job
- 帶 `APP_ROLE`，因為名字由 kernel 決定而環境變數不會

純字串，不碰硬碟，所以住單元層。
"""

import plistlib
from pathlib import Path

import pytest

from nova.載體.排程 import (
    不能當執行檔,
    啟動器名,
    怎麼跑,
    排程設定,
    排程預算,
    驗plist,
)
from nova.載體.預算 import 上限 as 預算上限


def _設定(
    *,
    預算token: int | None = None,
    預算美金: float | None = None,
    預算幾小時: float | None = None,
    **改: object,
) -> str:
    """預算那三個攤平著給。

    測試裡讀起來才是「使用者會打的那三個旗標」。
    """
    參 = {
        # **執行檔與工作目錄都在 daemon 那份 checkout 裡**，不在 `專案` 底下。
        "跑法": 怎麼跑(
            執行檔=Path("/Users/someone/nova-daemon/.venv/bin/nova-patrol"),
            路徑環境="/usr/bin:/bin",
            工作目錄=Path("/Users/someone/nova-daemon"),
        ),
        "專案": Path("/Users/someone/nova"),
        "狀態根": Path("/Users/someone/.local/state/nova"),
        "每幾分": 15,
        "預算": 排程預算(上限=預算上限(token=預算token, 美金=預算美金), 幾小時=預算幾小時),
    }
    參.update(改)
    return 排程設定(**參)  # type: ignore[arg-type]


def test_是合法的plist() -> None:
    讀回來 = plistlib.loads(_設定().encode("utf-8"))

    assert 讀回來["Label"].startswith("com.nova.")


def test_多久跑一次照給的分鐘數() -> None:
    讀回來 = plistlib.loads(_設定(每幾分=30).encode("utf-8"))

    assert 讀回來["StartInterval"] == 30 * 60


def test_跑的是nova不是直譯器() -> None:
    """**這一條是命名規範的核心。**

    寫成 `["/bin/bash", "跑.sh"]` 的話，「登入項目與延伸功能」與 macOS 的
    背景項目通知都只顯示 `bash`，完全看不出是誰的 job。
    """
    參數 = plistlib.loads(_設定().encode("utf-8"))["ProgramArguments"]

    # 名字是 `nova-patrol`（硬連結出來的專用直譯器）不是 `nova`——
    # console script 是 shebang 文字檔，kernel 執行的還是直譯器，
    # 活動監視器就會顯示 `python3`。見 `確保啟動器在`。
    assert Path(參數[0]).name.startswith("nova")
    assert not 不能當執行檔(Path(參數[0]))
    assert Path(參數[0]).is_absolute()


def test_跑的是巡那條路() -> None:
    """排程不生工作，它只是去巡一趟——**時鐘＝事件，收斂到同一個入口**。

    工作目錄在 daemon checkout，所以**要巡哪棵樹一定要明講**（`--專案`）：
    靠 cwd 猜的話，巡的就會是 daemon 自己那份。
    """
    參數 = plistlib.loads(_設定().encode("utf-8"))["ProgramArguments"]

    assert "巡" in 參數
    assert 參數[參數.index("--專案") + 1] == "/Users/someone/nova"
    assert 參數[參數.index("--喚醒來源") + 1] == "schedule"
    assert "--用" not in 參數, "排程不准用 --用 蓋掉依階段查派工表的路徑"


def test_帶著APP_ROLE() -> None:
    """名字由 kernel 在 exec 當下決定，環境變數不會——識別要靠它。"""
    環境 = plistlib.loads(_設定().encode("utf-8"))["EnvironmentVariables"]

    assert 環境["APP_ROLE"] == "nova.patrol"


def test_log落在狀態目錄不落在專案裡() -> None:
    """**log 也是會被餵回模型的東西**——落在工作目錄裡執行者就摸得到。"""
    讀回來 = plistlib.loads(_設定().encode("utf-8"))

    for 鍵 in ("StandardOutPath", "StandardErrorPath"):
        assert str(Path(讀回來[鍵]).parent) != "/Users/someone/nova"
        assert 讀回來[鍵].startswith("/Users/someone/.local/state/nova")
        # **檔名跟 Label 一致**：不一致的話，翻 log 的人手上只有 launchctl
        # 印出來的那個 Label，對不回是哪一個檔案。
        assert Path(讀回來[鍵]).name.startswith(f"{讀回來['Label']}.")


def test_Label是ASCII() -> None:
    """CJK 會讓 `launchctl`、`pkill`、log 過濾的字串比對出問題。

    **要對到整個字串**：只驗「是 ASCII、開頭是 com.nova.」的話，把每個專案
    都算成 `com.nova.patrol` 也照樣過關——而那樣兩個專案的 job 會共用一個
    Label，裝第二個就把第一個蓋掉。
    """
    標籤 = plistlib.loads(_設定(專案=Path("/Users/someone/Nova Repo 專案")).encode("utf-8"))[
        "Label"
    ]

    assert 標籤 == "com.nova.nova-repo.patrol"


@pytest.mark.parametrize(
    "名",
    ["bash", "sh", "zsh", "python3", "node", "uv", "uvx", "npx", "env", "nohup", "run"],
)
def test_擋得住拿直譯器或代跑工具當執行檔(名: str) -> None:
    """**這支是把關器不是說明。**

    `uv run nova` 很順手，但 plist 裡寫 `uv` 的話背景項目只會顯示 uv。
    通用廢名（`run`、`start`、`main`）同理——顯示出來都不是你的名字。
    """
    assert 不能當執行檔(Path(f"/somewhere/{名}"))


def test_nova自己可以當執行檔() -> None:
    """**這支防的是擋過頭。** 擋掉全部就沒有東西可以排程了。"""
    assert not 不能當執行檔(Path("/Users/someone/nova/.venv/bin/nova"))


def test_執行檔名字不對就當場炸() -> None:
    """印出一份裝下去會看不出是誰的 plist，比不印更糟。"""
    with pytest.raises(ValueError, match="uv"):
        _設定(
            跑法=怎麼跑(
                執行檔=Path("/opt/homebrew/bin/uv"),
                工作目錄=Path("/Users/someone/nova-daemon"),
            )
        )


class Test預算旗標要進得了排程:
    """**預算鎖存在的理由就是排程。**

    `nova 問` 一次只發一個請求，單看那次永遠沒超支——一天兩百次是另一回事，
    而那正是時鐘自己跑之後會發生的事。

    `ProgramArguments` 寫死的話，鎖剛好在它存在的理由上不存在：
    人在終端機打的每一次都擋得住，時鐘自己跑的那幾百次一次都擋不住。
    """

    def test_不給預算時不長出旗標(self) -> None:
        """**預設關閉**：「我主要是要看帳，但不要讓帳去把流程關閉。」"""
        參數 = plistlib.loads(_設定().encode("utf-8"))["ProgramArguments"]

        assert not [旗 for 旗 in 參數 if 旗.startswith("--預算")]

    def test_token上限會進到指令裡(self) -> None:
        參數 = plistlib.loads(_設定(預算token=500_000).encode("utf-8"))["ProgramArguments"]

        assert "--預算token" in 參數
        assert 參數[參數.index("--預算token") + 1] == "500000"

    def test_成本上限會進到指令裡(self) -> None:
        參數 = plistlib.loads(_設定(預算美金=5.0).encode("utf-8"))["ProgramArguments"]

        assert "--預算美金" in 參數
        assert float(參數[參數.index("--預算美金") + 1]) == 5.0

    def test_有給上限才帶窗口(self) -> None:
        """光給窗口不給上限的話，那個旗標一點作用都沒有。

        **帶著它會讓人以為有鎖。**
        """
        沒鎖 = plistlib.loads(_設定(預算幾小時=6.0).encode("utf-8"))["ProgramArguments"]
        有鎖 = plistlib.loads(_設定(預算token=100, 預算幾小時=6.0).encode("utf-8"))[
            "ProgramArguments"
        ]

        assert "--預算幾小時" not in 沒鎖
        assert 有鎖[有鎖.index("--預算幾小時") + 1] == "6.0"

    def test_每一格都是獨立的字串(self) -> None:
        """**`ProgramArguments` 不經過 shell。**

        `"--預算token 500000"` 塞成一格的話，argparse 會拿到一個叫
        「--預算token 500000」的旗標然後當場報用法錯誤——而那是在 launchd 的
        log 裡，沒有人會看到。
        """
        參數 = plistlib.loads(_設定(預算token=500_000).encode("utf-8"))["ProgramArguments"]

        assert all(" " not in 格 for 格 in 參數), 參數


def test_Label與啟動器名都是patrol那組() -> None:
    """排程這條線的身分是一組：Label、執行檔名、argv 三個要指同一件事。

    對得起來的時候，`launchctl list | grep patrol`、活動監視器裡的
    `nova-patrol`、log 檔名說的是同一個東西；對不起來就只能瞎猜。
    """
    讀回來 = plistlib.loads(_設定().encode("utf-8"))
    參數 = 讀回來["ProgramArguments"]

    assert 讀回來["Label"] == "com.nova.patrol"
    assert 啟動器名 == "nova-patrol"
    assert Path(參數[0]).name == 啟動器名
    assert "巡" in 參數
    assert 參數[參數.index("--專案") + 1] == "/Users/someone/nova"

    # 專案不是 nova 的時候要**多帶自己那段**：`com.nova.patrol` 是 nova 自己
    # 這條線的名字，別的專案沿用同一個的話，兩份 job 共用一個 Label，
    # 裝第二個就把第一個蓋掉，而 `launchctl list` 上只看得到一條。
    別的專案 = plistlib.loads(_設定(專案=Path("/Users/someone/otter")).encode("utf-8"))

    assert 別的專案["Label"] == "com.nova.otter.patrol"
    assert Path(別的專案["StandardOutPath"]).name.startswith("com.nova.otter.patrol.")


def _一份plist(*, 執行檔: str, 標籤: str) -> str:
    """最小的一份 plist——**違規要造得出來**，所以不走 `排程設定`。"""
    return plistlib.dumps(
        {
            "Label": 標籤,
            "ProgramArguments": [執行檔, "-m", "nova", "巡"],
            "RunAtLoad": False,
        },
        sort_keys=True,
    ).decode("utf-8")


def _可執行的(路徑: Path) -> Path:
    路徑.parent.mkdir(parents=True, exist_ok=True)
    路徑.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    路徑.chmod(0o755)
    return 路徑


def test_驗plist對五種違規各回一條而且家目錄是參數(tmp_path: Path) -> None:
    """五段檢查各自守一種「裝下去才會發現」的壞法，回一條照著做得完的訊息。

    **`家目錄` 與 `會消失的前綴` 是參數不是常數**：寫死的話這條規則只能在
    真的家目錄底下驗，於是永遠沒有測試看得到它——而它本來就是為了
    「從宿主的 hook 搬進 nova」才存在的。
    """
    家 = tmp_path / "家"
    好執行檔 = _可執行的(家 / "nova-daemon/.venv/bin/nova-patrol")
    這裡沒有會消失的地方 = ("/沒有這種前綴/",)

    def 驗(文字: str, 檔名: str = "com.nova.patrol.plist", **改: object) -> tuple[str, ...]:
        參: dict[str, object] = {"家目錄": 家, "會消失的前綴": 這裡沒有會消失的地方}
        參.update(改)
        return 驗plist(文字, 檔名, **參)  # type: ignore[arg-type]

    # 合規的一份要回空——**這一格就是參數化的理由**：`tmp_path` 住在
    # `/var/folders` 底下，而宿主那支把 `/var/folders` 判成「開機後會消失」。
    assert 驗(_一份plist(執行檔=str(好執行檔), 標籤="com.nova.patrol")) == ()

    # 一：執行檔名看不出是誰（代跑工具）。
    (訊息,) = 驗(_一份plist(執行檔=str(_可執行的(家 / "bin/uv")), 標籤="com.nova.patrol"))
    assert "uv" in 訊息

    # 二：不是絕對路徑——launchd 沒有你的 PATH。
    (訊息,) = 驗(_一份plist(執行檔="nova-patrol", 標籤="com.nova.patrol"))
    assert "絕對路徑" in 訊息

    # 三之一：路徑寫得漂亮但那支**根本不在**——`uv sync` 把 venv 重建掉就是這樣。
    # 「存在」跟「+x」是兩個壞法，只驗其中一個的話另一個沒有人守。
    不在的 = 家 / "nova-daemon/.venv/bin/nova-patrol-被清掉了"
    (訊息,) = 驗(_一份plist(執行檔=str(不在的), 標籤="com.nova.patrol"))
    assert "不存在" in 訊息
    assert str(不在的) in 訊息

    沒權限 = 家 / "nova-daemon/.venv/bin/nova-patrol-2"
    沒權限.write_text("#!/bin/sh\n", encoding="utf-8")
    沒權限.chmod(0o644)

    # 三之二：在，但沒有 +x——job 靜默失敗，而 BTM 已經留下項目了。
    (訊息,) = 驗(_一份plist(執行檔=str(沒權限), 標籤="com.nova.patrol"))
    assert "chmod" in 訊息
    assert str(沒權限) in 訊息

    # 四：放在開機後會消失的位置——重開機之後 job 永久壞掉。
    會消失 = _可執行的(tmp_path / "暫存/nova-patrol")
    (訊息,) = 驗(
        _一份plist(執行檔=str(會消失), 標籤="com.nova.patrol"),
        會消失的前綴=(f"{tmp_path / '暫存'}/",),
    )
    assert str(tmp_path / "暫存") in 訊息

    # 五之一：Label 不合正規式（大寫、非 kebab）。
    (訊息,) = 驗(
        _一份plist(執行檔=str(好執行檔), 標籤="com.Nova.Patrol"),
        檔名="com.Nova.Patrol.plist",
    )
    assert "com.nova." in 訊息

    # 五之二：Label 合規但跟檔名對不上——事後找不到是哪一支。
    (訊息,) = 驗(
        _一份plist(執行檔=str(好執行檔), 標籤="com.nova.patrol"),
        檔名="com.nova.別的.plist",
    )
    assert "com.nova.patrol.plist" in 訊息


def test_會消失的位置比對切在路徑分段上(tmp_path: Path) -> None:
    """「會不會消失」看的是路徑分段，不是字串開頭。

    前綴給的是一個目錄（`/tmp`、`/var/folders`），所以只有「就是它、或在它
    底下」才算會消失；名字剛好同開頭的鄰居（`/tmpfs-checkout`）是另一個地方，
    誤判會叫人把一支好好的執行檔搬走，而搬完那份 plist 還是裝不上去。

    **補不補斜線不准外包給呼叫端**：規則搬進 nova 就是為了讓呼叫端只給
    「哪些目錄會消失」——`("/tmp",)` 跟 `("/tmp/",)` 要判得一樣。
    """
    家 = tmp_path / "家"
    會消失的目錄 = tmp_path / "暫存"
    前綴 = (str(會消失的目錄),)  # 沒有結尾斜線：呼叫端會這樣給

    # 就在那個目錄底下——要抓。
    在裡面 = _可執行的(會消失的目錄 / "nova-patrol")
    (訊息,) = 驗plist(
        _一份plist(執行檔=str(在裡面), 標籤="com.nova.patrol"),
        "com.nova.patrol.plist",
        家目錄=家,
        會消失的前綴=前綴,
    )
    assert str(會消失的目錄) in 訊息

    # 只是名字開頭一樣的鄰居——不准抓。
    鄰居 = _可執行的(tmp_path / "暫存區還在/nova-daemon/.venv/bin/nova-patrol")
    assert (
        驗plist(
            _一份plist(執行檔=str(鄰居), 標籤="com.nova.patrol"),
            "com.nova.patrol.plist",
            家目錄=家,
            會消失的前綴=前綴,
        )
        == ()
    )

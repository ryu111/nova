"""驗收指令怎麼跑。**回 0 才算做完，不是模型說做完了。**

硬規則第 2 條不准以「模型說完成了」當停止條件。現在的收件匣迴圈
剛好就是那樣：工作流回 0 就進 `已處理/`，而那個 0 的意思是
「模型沒有摔」，不是「事情做對了」。這個模組是把判準換掉的那一步。

住整合層是因為它真的 fork 子程序（提交閘的時間預算規則）。
"""

import sys
from pathlib import Path

from nova.載體.跑驗收 import 跑驗收


def test_指令回0就是綠(tmp_path: Path) -> None:
    果 = 跑驗收(("/bin/echo 好了",), 工作目錄=tmp_path)
    assert 果.綠 is True
    assert len(果.每一條) == 1
    assert 果.每一條[0].退出碼 == 0


def test_指令回非0就是紅而且證據帶得出來(tmp_path: Path) -> None:
    果 = 跑驗收(
        (f"{sys.executable} -c \"import sys;print('壞了');sys.exit(3)\"",), 工作目錄=tmp_path
    )
    assert 果.綠 is False
    assert 果.每一條[0].退出碼 == 3
    assert "壞了" in 果.每一條[0].證據


def test_第一條紅就停(tmp_path: Path) -> None:
    """後面那些不跑。**跟閘同一條**：紅了就沒必要繼續燒時間。"""
    果 = 跑驗收(
        (f"{sys.executable} -c 'raise SystemExit(1)'", "/bin/echo 不該跑到"),
        工作目錄=tmp_path,
    )
    assert 果.綠 is False
    assert len(果.每一條) == 1


def test_全部都要綠才算綠(tmp_path: Path) -> None:
    果 = 跑驗收(("/bin/echo 甲", "/bin/echo 乙"), 工作目錄=tmp_path)
    assert 果.綠 is True
    assert len(果.每一條) == 2


def test_不走shell(tmp_path: Path) -> None:
    """**指令是 argv 不是 shell 字串。**

    走 shell 的話 `;`、`&&`、反引號都會被展開——而驗收指令是從票裡讀的，
    票可能是排程自己生的。一條驗收就能變成任意命令執行。
    """
    果 = 跑驗收(("/bin/echo 甲 && touch 壞檔",), 工作目錄=tmp_path)
    assert 果.綠 is True
    assert not (tmp_path / "壞檔").exists()


def test_逾時算紅而且說得出是逾時(tmp_path: Path) -> None:
    """**不知道就是沒過**（fail-closed）。

    驗收逾時跟工作流逾時不一樣：工作流逾時回 3（結果未知，不准重跑），
    驗收逾時是「這條驗收沒給出綠」——而沒給出綠就是紅。
    """
    果 = 跑驗收(
        (f"{sys.executable} -c 'import time;time.sleep(30)'",), 工作目錄=tmp_path, 每條上限秒=0.5
    )
    assert 果.綠 is False
    assert "逾時" in 果.每一條[0].證據


def test_執行檔不存在算紅不是炸掉(tmp_path: Path) -> None:
    """**打錯字的驗收指令不准把整個迴圈弄倒。**

    炸掉的話那一輪連成果帳都寫不出來，而「驗收指令打錯」跟
    「工作真的沒做完」在外面看起來會一模一樣。
    """
    果 = 跑驗收(("/不存在的執行檔 甲",), 工作目錄=tmp_path)
    assert 果.綠 is False
    assert 果.每一條[0].退出碼 != 0


def test_沒有驗收指令時綠但每一條是空的(tmp_path: Path) -> None:
    """**這個綠不代表驗收過，代表沒有驗收。**

    兩者分得開靠 `每一條` 是不是空的——呼叫端要看那一格，
    不是只看 `綠`。只看 `綠` 的話，一張沒宣告驗收的票會長得像驗收通過。
    """
    果 = 跑驗收((), 工作目錄=tmp_path)
    assert 果.綠 is True
    assert 果.每一條 == ()

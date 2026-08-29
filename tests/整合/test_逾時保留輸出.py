"""真的 fork 一個會逾時的子程序，確認它吐出來的東西撿得回來。

單元層那支（`tests/單元/test_逾時撿回.py`）驗的是「拿到部分輸出之後怎麼處理」，
用的是字串。**這一支驗的是「拿不拿得到」**——那是程序邊界的事，
`subprocess.TimeoutExpired` 到底帶不帶著 stdout，只有真的 fork 才知道。

這正是 05 說的「墊片證明的是轉遞形狀，不是可達性」。
"""

import stat
import sys
from pathlib import Path

import pytest

from nova.契約.角色 import 呼叫選項
from nova.載體.模型.執行 import 執行逾時, 跑cli
from nova.載體.模型.轉接 import 建立

#: 印一行帶 sid 的事件、沖出去、然後睡到被殺。
#: **一定要 flush**——不 flush 的話它會留在緩衝區裡跟著程序一起死，
#: 那就變成在測 Python 的緩衝行為而不是測 nova。
會拖的CLI = f"""#!{sys.executable}
import sys, time
sys.stdout.write('{{"type":"thread.started","thread_id":"睡著了的那段"}}\\n')
sys.stdout.write('{{"type":"item.completed","item":{{"id":"i1","type":"agent_message","text":"我開始查第一件事"}}}}\\n')
sys.stdout.flush()
time.sleep(30)
"""


@pytest.fixture
def 拖時間的(tmp_path: Path) -> Path:
    路徑 = tmp_path / "codex"
    路徑.write_text(會拖的CLI, encoding="utf-8")
    路徑.chmod(路徑.stat().st_mode | stat.S_IEXEC)
    return 路徑


@pytest.mark.serial
def test_逾時的例外帶著部分輸出(拖時間的: Path) -> None:
    """`subprocess.TimeoutExpired` 真的帶得回 stdout——這條不真跑就不知道。"""
    with pytest.raises(執行逾時) as 爆:
        跑cli(拖時間的, [], 逾時秒=1.0)
    assert "thread.started" in 爆.value.部分標準輸出


@pytest.mark.serial
def test_逾時之後撿得回sid(拖時間的: Path) -> None:
    """有 sid 才續接得了。這是「接續思考」整條路的關鍵一格。"""
    答 = 建立("codex", 執行檔=拖時間的).詢問("查三件事", 選項=呼叫選項(逾時秒=1.0))
    assert 答.對話識別碼 == "睡著了的那段"


@pytest.mark.serial
def test_逾時之後終局還是結果未知(拖時間的: Path) -> None:
    """**撿回東西不等於做完了。** 這條一鬆，可編輯模式下就會開始重跑副作用。"""
    答 = 建立("codex", 執行檔=拖時間的).詢問("查三件事", 選項=呼叫選項(逾時秒=1.0))
    assert 答.終局.value == "unknown"
    assert 答.失敗代碼.value == "timeout"


@pytest.mark.serial
def test_逾時之後看得到它做到哪(拖時間的: Path) -> None:
    答 = 建立("codex", 執行檔=拖時間的).詢問("查三件事", 選項=呼叫選項(逾時秒=1.0))
    assert "我開始查第一件事" in 答.文字

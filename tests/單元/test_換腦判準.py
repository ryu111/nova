"""「換一顆腦」的判準是**對話**，不是家族名。

三家不給續接時本來就都是新對話（codex `--ephemeral`、claude 不給 `--resume`、
agy 不給 `--conversation`），所以「同一家」擋掉的是一個已經隔離的組合。

真正要擋的是**做事與審查跑在同一個對話裡**——那才是自寫自評。
"""

import pytest

import nova
from nova.契約.模型回應 import 回應
from nova.契約.角色 import 呼叫選項, 預設選項
from nova.載體.角色 import 固定提示角色


def test_本地腦仍然不准當審查員() -> None:
    """放寬的是家族名那一條，**不是所有的審查資格檢查**。

    9B 的實測邊界（長提示 2/3、誠實拒答 1/3）沒有因為這條裁定而改變。
    """
    with pytest.raises(ValueError, match="審查資格|local"):
        nova.派工("任務", 用="claude", 審查用="local", 最多步數=0)


def test_角色結構上不可能續接到同一個對話() -> None:
    """**這才是真正的保證**：`固定提示角色` 組呼叫選項時沒有續接這個欄位。

    事前檢查看不到對話識別碼（那是呼叫之後才有的），
    所以保證只能落在結構上——角色拿不到續接，就永遠開新對話。
    加一個續接進去，這支就要紅。
    """
    收到的: list[呼叫選項] = []

    class 記錄腦:
        名稱 = "假腦"

        def 詢問(self, 提示: str, *, 選項: 呼叫選項 = 預設選項) -> 回應:
            del 提示
            收到的.append(選項)
            訊息 = "只看選項，不必真的回話"
            raise RuntimeError(訊息)

    角色 = 固定提示角色(名稱="測試員", 系統提示="你是測試員", 腦=記錄腦())
    with pytest.raises(RuntimeError):
        角色.做("做點事")

    assert 收到的, "角色沒有真的叫到腦"
    assert 收到的[0].續接 is None, f"角色不該傳續接：{收到的[0].續接}"

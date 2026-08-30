"""同一家不同對話可以互審——這支會真的啟動子程序，所以住整合層。"""

from pathlib import Path

import nova


def test_同一家不同對話可以互審(tmp_path: Path) -> None:
    """使用者裁定（2026-08-31）：new session 就不是同一個人。

    這條放寬的實際意義：某一家的某個額度池用完時，
    不必因為「找不到第二家」就整個停工。

    用 `最多步數=0` 讓它撞護欄立刻收場——這支只問「有沒有被家族名擋在門口」。
    """
    假cli = tmp_path / "agy"
    假cli.write_text("#!/bin/sh\necho '{}'\n", encoding="utf-8")
    假cli.chmod(0o755)

    結果 = nova.派工(
        "任務",
        用="agy",
        審查用="agy",
        最多步數=0,
        工作目錄=tmp_path,
        執行檔=假cli,
        審查執行檔=假cli,
        帳本目錄=tmp_path / "帳",
    )

    assert 結果 is not None, "同一家不該再被家族名擋在門口"

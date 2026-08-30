"""啟動器：把直譯器硬連結成一個活動監視器看得出是誰的名字。

**硬連結不是複製**，同一份 inode。但 inode 相同這件事會過期：
直譯器升級之後 `.venv/bin/python` 指到新的那份，而舊的硬連結還在
——於是排程跑的是舊直譯器、venv 的套件是給新的裝的，**炸在 launchd 的 log 裡**。

所以每次重印排程都要對一次 inode，不一樣就換掉。
"""

import os
from pathlib import Path

from nova.載體.排程 import 啟動器名, 確保啟動器在


def _inode(路徑: Path) -> int:
    return 路徑.stat().st_ino


def _假直譯器(在: Path, 名: str) -> Path:
    路 = 在 / 名
    路.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    路.chmod(路.stat().st_mode | 0o111)
    return 路


class Test啟動器:
    def test_沒有就建一個硬連結(self, tmp_path: Path) -> None:
        直譯器 = _假直譯器(tmp_path, "python3")

        落點 = 確保啟動器在(直譯器)

        assert 落點.name == 啟動器名
        assert 落點.parent == tmp_path, "**必須留在 venv 的 bin 裡**，搬出去就找不到 pyvenv.cfg"
        assert _inode(落點) == _inode(直譯器), "要硬連結，不是複製"

    def test_已經在就不重建(self, tmp_path: Path) -> None:
        """重複呼叫要安全——`nova 排程` 每次都會叫它一次。"""
        直譯器 = _假直譯器(tmp_path, "python3")
        第一次 = _inode(確保啟動器在(直譯器))

        assert _inode(確保啟動器在(直譯器)) == 第一次

    def test_直譯器換掉之後啟動器要跟著換(self, tmp_path: Path) -> None:
        """**inode 相同會過期。**

        直譯器升級後舊的硬連結還在，排程就會拿舊直譯器配新套件跑，
        而錯誤只出現在 launchd 的 log 裡。
        """
        舊的 = _假直譯器(tmp_path, "python3")
        確保啟動器在(舊的)
        舊的.unlink()
        新的 = _假直譯器(tmp_path, "python3")
        assert _inode(新的) != _inode(tmp_path / 啟動器名), "前提沒成立：兩份應該不同 inode"

        落點 = 確保啟動器在(新的)

        assert _inode(落點) == _inode(新的)

    def test_跟著符號連結走到真的那份(self, tmp_path: Path) -> None:
        """`.venv/bin/python` 是符號連結。

        **硬連結不能連到符號連結**，要連到它指的那份真的二進位。
        """
        真的 = _假直譯器(tmp_path, "python3.13")
        連結 = tmp_path / "python"
        連結.symlink_to(真的)

        落點 = 確保啟動器在(連結)

        assert not 落點.is_symlink()
        assert _inode(落點) == _inode(真的)

    def test_建出來的是可執行的(self, tmp_path: Path) -> None:
        直譯器 = _假直譯器(tmp_path, "python3")

        assert os.access(確保啟動器在(直譯器), os.X_OK)

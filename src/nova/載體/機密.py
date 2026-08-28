"""機密不進版控。

`.gitignore` 寫了什麼不等於 git 真的會忽略（順序、否定規則、已被追蹤的檔案都會翻盤），
所以直接問 git 本人，並且另外掃一遍「已經被追蹤的檔案」。
"""

from pathlib import Path

from nova.載體.git查詢 import 會被忽略, 追蹤中的檔案

必須被忽略 = (".env", ".env.local", ".env.production", "api.key", "server.pem")
機密特徵 = (".env", ".key", ".pem", ".p12", "credentials.json")
機密例外 = (".env.example",)


def 檢查機密(根目錄: Path) -> tuple[bool, str]:
    """回傳 (放行, 證據)。"""
    沒擋住 = [路徑 for 路徑 in 必須被忽略 if not 會被忽略(根目錄, 路徑)]
    已追蹤 = [
        路徑
        for 路徑 in 追蹤中的檔案(根目錄)
        if any(特徵 in Path(路徑).name for 特徵 in 機密特徵) and not 路徑.endswith(機密例外)
    ]

    問題 = []
    if 沒擋住:
        問題.append(f"git 不會忽略這些路徑：{'、'.join(沒擋住)}")
    if 已追蹤:
        問題.append(f"這些機密檔案已經被 git 追蹤（寫進 .gitignore 也擋不住）：{'、'.join(已追蹤)}")
    return (not 問題), "；".join(問題)

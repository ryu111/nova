"""工作流的喚醒來源契約。"""

from enum import StrEnum


class 喚醒來源(StrEnum):
    """誰讓這一輪工作流醒來；它不描述題目原本從哪裡來。"""

    人手動敲 = "manual"
    排程到期 = "schedule"
    收件檔出現 = "file"

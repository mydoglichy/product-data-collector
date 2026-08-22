from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def now_iso(timezone_name: str = "Asia/Seoul") -> str:
    return datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")


def today_string(timezone_name: str = "Asia/Seoul") -> str:
    return datetime.now(ZoneInfo(timezone_name)).date().isoformat()


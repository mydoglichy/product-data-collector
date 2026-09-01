from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def now_iso(timezone_name: str = "Asia/Seoul") -> str:
    return datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")


def today_string(timezone_name: str = "Asia/Seoul") -> str:
    return datetime.now(ZoneInfo(timezone_name)).date().isoformat()


def output_file_stamp(api_name: str, timezone_name: str = "Asia/Seoul", dt: datetime | None = None) -> str:
    value = dt or datetime.now(ZoneInfo(timezone_name))
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(timezone_name))
    value = value.astimezone(ZoneInfo(timezone_name))
    return f"{api_name}_{value:%Y}_{value:%m%d}_{value:%H%M}"


from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def now_iso(timezone: str) -> str:
    return datetime.now(ZoneInfo(timezone)).replace(microsecond=0).isoformat()


def today_string(timezone: str) -> str:
    return datetime.now(ZoneInfo(timezone)).strftime("%Y-%m-%d")


def output_file_stamp(api_name: str, timezone: str, dt: datetime | None = None) -> str:
    value = dt or datetime.now(ZoneInfo(timezone))
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(timezone))
    value = value.astimezone(ZoneInfo(timezone))
    return f"{api_name}_{value:%Y}_{value:%m%d}_{value:%H%M}"


def to_unix_millis(iso_value: str) -> int:
    return int(datetime.fromisoformat(iso_value).timestamp() * 1000)


def from_unix_millis(value: int, timezone: str) -> str:
    return datetime.fromtimestamp(value / 1000, ZoneInfo(timezone)).replace(microsecond=0).isoformat()

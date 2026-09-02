from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


NUMERIC_TEXT_RE = re.compile(r"^[\s$원]*[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?[\s원]*$")


def parse_number(value: Any) -> int | float | Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    normalized = normalize_numeric_text(value)
    if normalized is None:
        return value
    return float(normalized) if "." in normalized else int(normalized)


def parse_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    normalized = normalize_numeric_text(value)
    if normalized is None:
        return None
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def normalize_numeric_text(value: Any) -> str | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    text = str(value).strip()
    if not NUMERIC_TEXT_RE.fullmatch(text):
        return None
    return re.sub(r"[\s$원,]", "", text)

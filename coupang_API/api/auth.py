from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone


def coupang_signed_datetime(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%y%m%dT%H%M%SZ")


def generate_authorization(
    method: str,
    uri: str,
    access_key: str,
    secret_key: str,
    now: datetime | None = None,
) -> str:
    parts = uri.split("?")
    if len(parts) > 2:
        raise ValueError("incorrect uri format")

    path = parts[0]
    query = parts[1] if len(parts) == 2 else ""
    signed_date = coupang_signed_datetime(now)
    message = f"{signed_date}{method.upper()}{path}{query}"
    signature = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return (
        "CEA algorithm=HmacSHA256,"
        f"access-key={access_key},"
        f"signed-date={signed_date},"
        f"signature={signature}"
    )


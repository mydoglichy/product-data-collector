from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


MISSING = {"__value__": "__MISSING__"}
VOLATILE_KEYS = {
    "collectedAt",
    "raw",
    "rank",
    "keyword",
    "keywords",
    "productName",
    "productUrl",
    "affiliateUrl",
    "productImage",
    "imageUrl",
    "images",
    "registeredAt",
    "updatedAt",
    "saleStartedAt",
    "saleEndedAt",
    "firstSeenAt",
    "lastSeenAt",
    "lastCheckedAt",
    "fingerprint",
}
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "adid",
    "campaign",
    "clickid",
    "coupangclickid",
    "fbclid",
    "gclid",
    "lptag",
    "mc_cid",
    "mc_eid",
    "subid",
    "traceid",
}
COMPARABLE_KEYS = ("prices", "inventory", "shipping", "options", "status", "sourceStatus", "markets")
EXPECTED_SECTION_FIELDS = {
    "inventory": (
        "stockQuantity",
        "apiStockQuantity",
        "domeMoq",
        "domeMaxOrderQuantity",
        "domeOrderUnit",
        "supplyOrderUnit",
    ),
    "shipping": (
        "fee",
        "type",
        "feeType",
        "feePayer",
        "isFreeShipping",
        "domeFee",
        "domeFeeRaw",
        "domeFeeType",
        "supplyFee",
        "supplyFeeRaw",
        "supplyFeeType",
    ),
}
NUMERIC_TEXT_RE = re.compile(r"^[\s$￦₩€£¥]*[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?[\s원]*$")


def upsert_product_changes(
    *,
    platform: str,
    current_path: Path,
    history_path: Path,
    collected_at: str,
    products: Iterable[dict[str, Any]],
) -> dict[str, int]:
    current_db = _load_json(current_path, {"products": {}})
    history_db = _load_json(history_path, {"records": []})
    current_products = current_db.get("products") if isinstance(current_db.get("products"), dict) else {}
    history_records = history_db.get("records") if isinstance(history_db.get("records"), list) else []

    stats = {"checkedCount": 0, "newProductCount": 0, "changedProductCount": 0, "unchangedProductCount": 0}
    seen_in_call: set[str] = set()
    for product in products:
        external_id = external_product_id(product)
        if not external_id:
            continue
        db_key = product_key(platform, external_id)
        if db_key in seen_in_call:
            continue
        seen_in_call.add(db_key)
        stats["checkedCount"] += 1

        sanitized = normalize_current_product(product)
        comparable = comparable_state(product)
        fingerprint = fingerprint_state(comparable)
        existing = current_products.get(db_key) if isinstance(current_products.get(db_key), dict) else None
        before_comparable = existing.get("comparable") if existing else None
        before_fingerprint = existing.get("comparableFingerprint") if existing else None

        if existing is None:
            stats["newProductCount"] += 1
            history_records.append(
                _history_record(
                    platform=platform,
                    external_id=external_id,
                    changed_at=collected_at,
                    change_type="initial",
                    changed_fields=sorted(flatten_paths(comparable)),
                    before=None,
                    after=comparable,
                    before_fingerprint=None,
                    after_fingerprint=fingerprint,
                )
            )
            first_seen_at = collected_at
        elif before_fingerprint != fingerprint:
            stats["changedProductCount"] += 1
            changed_fields = changed_leaf_paths(before_comparable, comparable)
            history_records.append(
                _history_record(
                    platform=platform,
                    external_id=external_id,
                    changed_at=collected_at,
                    change_type="update",
                    changed_fields=changed_fields,
                    before=before_comparable,
                    after=comparable,
                    before_fingerprint=before_fingerprint,
                    after_fingerprint=fingerprint,
                )
            )
            first_seen_at = existing.get("firstSeenAt") or collected_at
        else:
            stats["unchangedProductCount"] += 1
            first_seen_at = existing.get("firstSeenAt") if existing else collected_at

        current_products[db_key] = {
            "platform": platform,
            "externalProductId": external_id,
            "firstSeenAt": first_seen_at,
            "lastCheckedAt": collected_at,
            "current": sanitized,
            "comparable": comparable,
            "comparableFingerprint": fingerprint,
        }

    current_db["products"] = current_products
    history_db["records"] = history_records
    _atomic_write_many(((current_path, current_db), (history_path, history_db)))
    return stats


def append_collection_run(
    path: Path,
    *,
    platform: str,
    started_at: str,
    ended_at: str,
    success: bool,
    queried_product_count: int,
    new_product_count: int,
    changed_product_count: int,
    unchanged_product_count: int,
    failed_product_count: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = _load_json(path, {"runs": []})
    runs = db.get("runs") if isinstance(db.get("runs"), list) else []
    record = {
        "platform": platform,
        "startedAt": started_at,
        "endedAt": ended_at,
        "success": success,
        "queriedProductCount": queried_product_count,
        "newProductCount": new_product_count,
        "changedProductCount": changed_product_count,
        "unchangedProductCount": unchanged_product_count,
        "failedProductCount": failed_product_count,
    }
    if extra:
        record["extra"] = extra
    runs.append(record)
    _atomic_write(path, {"runs": runs})
    return record


def get_recent_price_quantity_history(
    *,
    history_path: Path,
    platform: str,
    external_product_id: str,
    days: int = 30,
    end_at: str | None = None,
) -> dict[str, Any]:
    end_dt = _parse_datetime(end_at) if end_at else datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days - 1)
    records = [
        record
        for record in _load_json(history_path, {"records": []}).get("records", [])
        if isinstance(record, dict)
        and record.get("platform") == platform
        and str(record.get("externalProductId")) == str(external_product_id)
        and _parse_datetime(record.get("changedAt")) <= end_dt
    ]
    records.sort(key=lambda record: _parse_datetime(record.get("changedAt")))

    previous_state = None
    period_records = []
    price_change_count = 0
    quantity_change_count = 0
    for record in records:
        changed_at = _parse_datetime(record.get("changedAt"))
        state = record.get("after")
        if changed_at < start_dt:
            previous_state = state
            continue
        if previous_state is not None:
            changed = set(changed_leaf_paths(previous_state, state))
            if any(path.startswith("prices.") for path in changed):
                price_change_count += 1
            if any(path.startswith("inventory.") or path.startswith("options.") for path in changed):
                quantity_change_count += 1
        elif record.get("changeType") == "update":
            changed = set(record.get("changedFields") if isinstance(record.get("changedFields"), list) else [])
            if any(path.startswith("prices.") for path in changed):
                price_change_count += 1
            if any(path.startswith("inventory.") or path.startswith("options.") for path in changed):
                quantity_change_count += 1
        previous_state = state
        period_records.append(record)

    daily = []
    cursor = start_dt.date()
    end_date = end_dt.date()
    latest = _state_before(records, start_dt) or (period_records[0].get("after") if period_records else None)
    while cursor <= end_date:
        day_end = datetime.combine(cursor, datetime.max.time(), tzinfo=end_dt.tzinfo)
        for record in period_records:
            if _parse_datetime(record.get("changedAt")).date() == cursor:
                latest = record.get("after")
        daily.append({"date": cursor.isoformat(), "state": copy.deepcopy(latest)})
        cursor += timedelta(days=1)

    prices = [_extract_primary_price(item.get("state")) for item in daily]
    prices = [price for price in prices if isinstance(price, (int, float))]
    quantities = [_extract_quantity(item.get("state")) for item in daily]
    return {
        "platform": platform,
        "externalProductId": str(external_product_id),
        "days": days,
        "daily": daily,
        "firstValue": daily[0]["state"] if daily else None,
        "latestValue": daily[-1]["state"] if daily else None,
        "lowestPrice": min(prices) if prices else None,
        "highestPrice": max(prices) if prices else None,
        "priceChangeCount": price_change_count,
        "quantityChangeCount": quantity_change_count,
        "quantities": quantities,
    }


def external_product_id(product: dict[str, Any]) -> str | None:
    for key in ("externalProductId", "productId", "productKey"):
        value = product.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


def product_key(platform: str, external_id: str) -> str:
    return f"{platform}:{external_id}"


def normalize_current_product(product: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(product)
    result.pop("raw", None)
    for key in ("productUrl", "affiliateUrl", "imageUrl", "productImage"):
        if key in result:
            result[key] = normalize_url(result.get(key), strip_all_query=key.lower().find("image") >= 0)
    if "images" in result and isinstance(result["images"], list):
        result["images"] = [normalize_url(value, strip_all_query=True) for value in result["images"]]
    return result


def comparable_state(product: dict[str, Any]) -> dict[str, Any]:
    if product.get("prices") is None and "productPrice" in product:
        state = {
            "prices": {"productPrice": product.get("productPrice")},
            "shipping": {"isFreeShipping": product.get("isFreeShipping", MISSING)},
        }
    else:
        state = {key: _section_state(key, product) for key in COMPARABLE_KEYS}
    return canonicalize(state)


def _section_state(key: str, product: dict[str, Any]) -> Any:
    if key not in product:
        if key in EXPECTED_SECTION_FIELDS:
            return {field: MISSING for field in EXPECTED_SECTION_FIELDS[key]}
        return MISSING
    value = product[key]
    if isinstance(value, dict) and key in EXPECTED_SECTION_FIELDS:
        return {field: value[field] if field in value else MISSING for field in EXPECTED_SECTION_FIELDS[key]}
    return value


def canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key).strip(): canonicalize(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]).strip())
            if str(key) not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        items = [canonicalize(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if isinstance(value, str):
        text = value.strip()
        if NUMERIC_TEXT_RE.fullmatch(text):
            normalized = re.sub(r"[\s$￦₩€£¥원,]", "", text)
            return float(normalized) if "." in normalized else int(normalized)
        return text
    return value


def normalize_url(value: Any, *, strip_all_query: bool = False) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    parts = urlsplit(value.strip())
    if strip_all_query:
        query = ""
    else:
        params = [
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in TRACKING_QUERY_KEYS and not key.lower().startswith(TRACKING_QUERY_PREFIXES)
        ]
        query = urlencode(params, doseq=True)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


def fingerprint_state(state: Any) -> str:
    payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def changed_leaf_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        paths: list[str] = []
        for key in sorted(set(before) | set(after)):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(changed_leaf_paths(before.get(key, MISSING), after.get(key, MISSING), child_prefix))
        return paths
    if isinstance(before, list) and isinstance(after, list):
        return [prefix or "value"]
    return [prefix or "value"]


def flatten_paths(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        paths: set[str] = set()
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            paths.update(flatten_paths(child, child_prefix))
        return paths
    return {prefix or "value"}


def _history_record(
    *,
    platform: str,
    external_id: str,
    changed_at: str,
    change_type: str,
    changed_fields: list[str],
    before: Any,
    after: Any,
    before_fingerprint: str | None,
    after_fingerprint: str,
) -> dict[str, Any]:
    return {
        "platform": platform,
        "externalProductId": external_id,
        "changedAt": changed_at,
        "changeType": change_type,
        "changedFields": changed_fields,
        "before": before,
        "after": after,
        "beforeFingerprint": before_fingerprint,
        "afterFingerprint": after_fingerprint,
    }


def _state_before(records: list[dict[str, Any]], dt: datetime) -> Any:
    latest = None
    for record in records:
        if _parse_datetime(record.get("changedAt")) < dt:
            latest = record.get("after")
    return latest


def _extract_primary_price(state: Any) -> int | float | None:
    prices = state.get("prices") if isinstance(state, dict) and isinstance(state.get("prices"), dict) else {}
    for key in sorted(prices):
        value = prices[key]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def _extract_quantity(state: Any) -> int | float | None:
    inventory = state.get("inventory") if isinstance(state, dict) and isinstance(state.get("inventory"), dict) else {}
    value = inventory.get("stockQuantity")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value or "").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        dt = datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(default)
    with path.open("r", encoding="utf-8-sig") as fp:
        payload = json.load(fp)
    return payload if isinstance(payload, dict) else copy.deepcopy(default)


def _atomic_write_many(items: Iterable[tuple[Path, dict[str, Any]]]) -> None:
    written: list[tuple[Path, Path]] = []
    try:
        for path, payload in items:
            tmp_path = _write_tmp(path, payload)
            written.append((path, tmp_path))
        for path, tmp_path in written:
            os.replace(tmp_path, path)
    finally:
        for _, tmp_path in written:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = _write_tmp(path, payload)
    os.replace(tmp_path, path)


def _write_tmp(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2, sort_keys=True)
        fp.write("\n")
        fp.flush()
        os.fsync(fp.fileno())
    return tmp_path

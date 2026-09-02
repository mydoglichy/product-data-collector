from __future__ import annotations

import copy
import hashlib
import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from numeric_utils import NUMERIC_TEXT_RE, parse_number


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
    "backupImageUrl",
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
        "feeRaw",
        "typeRaw",
        "sourceFields",
        "domeFee",
        "domeFeeRaw",
        "domeFeeType",
        "domeFeePayer",
        "domeFeeTable",
        "supplyFee",
        "supplyFeeRaw",
        "supplyFeeType",
        "supplyFeePayer",
        "supplyFeeTable",
        "feeExtraJeju",
        "feeExtraIslands",
        "remoteAreaFee",
    ),
}

def external_product_id(product: dict[str, Any]) -> str | None:
    for key in ("externalProductId", "productId", "productKey"):
        value = product.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


def normalize_current_product(product: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(product)
    result.pop("raw", None)
    for key in ("productUrl", "affiliateUrl", "imageUrl", "backupImageUrl", "productImage"):
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
            return parse_number(text)
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


def _section_state(key: str, product: dict[str, Any]) -> Any:
    if key not in product:
        if key in EXPECTED_SECTION_FIELDS:
            return {field: MISSING for field in EXPECTED_SECTION_FIELDS[key]}
        return MISSING
    value = product[key]
    if isinstance(value, dict) and key in EXPECTED_SECTION_FIELDS:
        return {field: value[field] if field in value else MISSING for field in EXPECTED_SECTION_FIELDS[key]}
    return value

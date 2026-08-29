from __future__ import annotations

import copy
import re
from typing import Any


_NUMERIC_TEXT_RE = re.compile(r"^[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$")

STATUS_MAP = {
    "available": "available",
    "soldout": "soldout",
    "discontinued": "discontinued",
    "unavailable": "unavailable",
}


def extract_connection_items(connection: dict[str, Any], root_key: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = connection.get(root_key)
    if not isinstance(root, dict):
        return [], {}
    page_info = root.get("pageInfo") if isinstance(root.get("pageInfo"), dict) else {}
    items: list[dict[str, Any]] = []
    for edge in root.get("edges") or []:
        if isinstance(edge, dict) and isinstance(edge.get("node"), dict):
            node = dict(edge["node"])
            if edge.get("cursor") is not None:
                node["_cursor"] = edge.get("cursor")
            items.append(node)
    return items, page_info


def normalize_item(item: dict[str, Any], collected_at: str) -> dict[str, Any]:
    product_key = _string(item.get("key"))
    options = normalize_options(item.get("options"))
    source_status = _string(item.get("status"))
    category = item.get("category") if isinstance(item.get("category"), dict) else {}
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else item.get("metadata")
    raw = compact_raw_item_for_snapshot(item)
    product = {
        "source": "ownerclan",
        "productId": product_key,
        "productKey": product_key,
        "collectedAt": collected_at,
        "status": normalize_status(source_status),
        "sourceStatus": source_status,
        "productName": item.get("name"),
        "registeredAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
        "prices": {
            "currentSupplyPrice": number_or_original(item.get("price")),
            "fixedPrice": number_or_original(item.get("fixedPrice")),
        },
        "inventory": {
            "stockQuantity": calculate_total_stock(options),
            "stockQuantitySource": "sum(options[].quantity)",
            "apiStockQuantity": number_or_original(item.get("quantity")),
        },
        "options": options,
        "shipping": {
            "fee": number_or_original(item.get("shippingFee")),
            "type": item.get("shippingType"),
        },
        "category": {
            "code": category.get("key"),
            "name": category.get("name"),
            "fullName": category.get("fullName"),
        },
        "manufacturer": item.get("production"),
        "origin": item.get("origin"),
        "model": item.get("model"),
        "sourceSpecific": {
            "id": item.get("id"),
            "pricePolicy": item.get("pricePolicy"),
            "taxFree": item.get("taxFree"),
            "adultOnly": item.get("adultOnly"),
            "returnable": item.get("returnable"),
            "guaranteedShippingPeriod": number_or_original(item.get("guaranteedShippingPeriod")),
            "openmarketSellable": item.get("openmarketSellable"),
            "boxQuantity": number_or_original(item.get("boxQuantity")),
            "attributes": item.get("attributes"),
            "closingTime": item.get("closingTime"),
            "vendorKey": metadata.get("vendorKey") if isinstance(metadata, dict) else None,
            "certificateInformation": metadata.get("certificateInformation") if isinstance(metadata, dict) else None,
            "grade": metadata.get("grade") if isinstance(metadata, dict) else None,
            "gradeDetail": metadata.get("gradeDetail") if isinstance(metadata, dict) else None,
        },
        "raw": raw,
    }
    return product


def compact_raw_item_for_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(item)
    for key in ("content", "images", "searchKeywords", "metadata", "noReturnReason", "returnCriteria"):
        result.pop(key, None)
    return result


def normalize_options(value: Any) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for index, option in enumerate(value if isinstance(value, list) else []):
        if not isinstance(option, dict):
            continue
        attrs = option.get("optionAttributes")
        normalized_attrs = [
            {"name": attr.get("name"), "value": attr.get("value")}
            for attr in attrs
            if isinstance(attr, dict)
        ] if isinstance(attrs, list) else []
        options.append(
            {
                "skuKey": option.get("key"),
                "skuType": "default" if not normalized_attrs else "option",
                "optionAttributes": normalized_attrs,
                "price": number_or_original(option.get("price")),
                "quantity": number_or_original(option.get("quantity")),
            }
        )
    return options


def calculate_total_stock(options: list[dict[str, Any]]) -> int | None:
    quantities: list[int] = []
    for option in options:
        quantity = option.get("quantity")
        if isinstance(quantity, bool):
            continue
        if isinstance(quantity, (int, float)):
            quantities.append(int(quantity))
        elif isinstance(quantity, str) and quantity.strip().isdigit():
            quantities.append(int(quantity.strip()))
    return sum(quantities) if quantities else None


def number_or_original(value: Any) -> int | float | Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not _NUMERIC_TEXT_RE.fullmatch(text):
        return value
    normalized = text.replace(",", "")
    return float(normalized) if "." in normalized else int(normalized)


def normalize_status(value: str | None) -> str | None:
    if value is None:
        return None
    return STATUS_MAP.get(value, value)


def _string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)

from __future__ import annotations

import copy
from typing import Any


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
    compact_metadata = compact_metadata_for_snapshot(metadata)
    product = {
        "source": "ownerclan",
        "productId": product_key,
        "productKey": product_key,
        "collectedAt": collected_at,
        "status": normalize_status(source_status),
        "sourceStatus": source_status,
        "productName": item.get("name"),
        "keywords": item.get("searchKeywords"),
        "registeredAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
        "prices": {
            "currentSupplyPrice": item.get("price"),
            "fixedPrice": item.get("fixedPrice"),
        },
        "inventory": {
            "stockQuantity": calculate_total_stock(options),
            "stockQuantitySource": "sum(options[].quantity)",
            "apiStockQuantity": item.get("quantity"),
        },
        "options": options,
        "shipping": {
            "fee": item.get("shippingFee"),
            "type": item.get("shippingType"),
        },
        "category": {
            "code": category.get("key"),
            "name": category.get("name"),
            "fullName": category.get("fullName"),
        },
        "image": {
            "representativeUrl": _first(item.get("images")),
            "urls": item.get("images") if isinstance(item.get("images"), list) else [],
        },
        "manufacturer": item.get("production"),
        "origin": item.get("origin"),
        "model": item.get("model"),
        "sourceSpecific": {
            "id": item.get("id"),
            "content": item.get("content"),
            "pricePolicy": item.get("pricePolicy"),
            "taxFree": item.get("taxFree"),
            "adultOnly": item.get("adultOnly"),
            "returnable": item.get("returnable"),
            "noReturnReason": item.get("noReturnReason"),
            "guaranteedShippingPeriod": item.get("guaranteedShippingPeriod"),
            "openmarketSellable": item.get("openmarketSellable"),
            "boxQuantity": item.get("boxQuantity"),
            "attributes": item.get("attributes"),
            "closingTime": item.get("closingTime"),
            "returnCriteria": item.get("returnCriteria"),
            "metadata": compact_metadata,
            "vendorKey": metadata.get("vendorKey") if isinstance(metadata, dict) else None,
        },
        "raw": item,
    }
    return product


def compact_metadata_for_snapshot(metadata: Any) -> Any:
    if not isinstance(metadata, dict):
        return metadata
    result = copy.deepcopy(metadata)
    notification = result.get("productNotificationInformation")
    if isinstance(notification, dict):
        category_specific = notification.get("categorySpecific")
        if _is_repeated_placeholder_list(category_specific):
            notification["categorySpecificSummary"] = {
                "omitted": True,
                "reason": "repeated placeholder values",
                "count": len(category_specific),
                "uniqueValues": sorted({str(value) for value in category_specific}),
            }
            notification.pop("categorySpecific", None)
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
                "price": option.get("price"),
                "quantity": option.get("quantity"),
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


def normalize_status(value: str | None) -> str | None:
    if value is None:
        return None
    return STATUS_MAP.get(value, value)


def _string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _first(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return None


def _is_repeated_placeholder_list(value: Any) -> bool:
    if not isinstance(value, list) or len(value) < 2:
        return False
    normalized = [str(item).strip() for item in value if item not in (None, "")]
    if len(normalized) != len(value):
        return False
    unique = set(normalized)
    placeholder_values = {"상품 상세정보에 별도 표기", "판매자 연락처 참고"}
    return len(unique) <= 2 and unique.issubset(placeholder_values)

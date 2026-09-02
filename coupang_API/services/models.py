from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from numeric_utils import parse_number


@dataclass(frozen=True)
class ProductSearchRecord:
    productId: int | str | None
    itemId: str | None
    vendorItemId: str | None
    productName: str | None
    productPrice: int | float | str | None
    productUrl: str | None
    keyword: str | None
    rank: int | None
    isRocket: bool | None
    isFreeShipping: bool | None
    collectedAt: str

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_product_records(
    payload: dict[str, Any],
    requested_keyword: str,
    collected_at: str,
) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    product_data = data.get("productData") or []
    if not isinstance(product_data, list):
        product_data = []

    records: list[dict[str, Any]] = []
    for index, product in enumerate(product_data, start=1):
        if not isinstance(product, dict):
            product = {}
        product_url = product.get("productUrl")
        item_id = _query_value(product_url, "itemId")
        vendor_item_id = _query_value(product_url, "vendorItemId")
        record = ProductSearchRecord(
            productId=product.get("productId"),
            itemId=item_id,
            vendorItemId=vendor_item_id,
            productName=product.get("productName"),
            productPrice=_number(product.get("productPrice")),
            productUrl=product_url,
            keyword=product.get("keyword") or requested_keyword,
            rank=_rank(product.get("rank"), fallback=index),
            isRocket=product.get("isRocket"),
            isFreeShipping=product.get("isFreeShipping"),
            collectedAt=collected_at,
        )
        records.append(record.to_json_dict())
    return records


def _rank(value: Any, fallback: int) -> int | None:
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> int | float | Any:
    return parse_number(value)


def _query_value(url: Any, key: str) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    values = parse_qs(urlparse(url).query).get(key)
    return values[0] if values else None

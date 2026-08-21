from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SOURCE = "coupang_partners_product_search"


@dataclass(frozen=True)
class ProductSearchApiFields:
    keyword: str | None
    rank: int | None
    isRocket: bool | None
    isFreeShipping: bool | None
    productId: int | str | None
    productImage: str | None
    productName: str | None
    productPrice: int | float | str | None
    productUrl: str | None
    landingUrl: str | None


@dataclass(frozen=True)
class CollectorMetadata:
    requestedKeyword: str
    collectedAt: str
    source: str = SOURCE


@dataclass(frozen=True)
class ProductSearchRecord:
    api: ProductSearchApiFields
    collector: CollectorMetadata

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "api": asdict(self.api),
            "collector": asdict(self.collector),
        }


def parse_product_records(
    payload: dict[str, Any],
    requested_keyword: str,
    collected_at: str,
) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    landing_url = data.get("landingUrl")
    product_data = data.get("productData") or []
    if not isinstance(product_data, list):
        product_data = []

    records: list[dict[str, Any]] = []
    for index, product in enumerate(product_data, start=1):
        if not isinstance(product, dict):
            product = {}
        api_fields = ProductSearchApiFields(
            keyword=product.get("keyword"),
            rank=_rank(product.get("rank"), fallback=index),
            isRocket=product.get("isRocket"),
            isFreeShipping=product.get("isFreeShipping"),
            productId=product.get("productId"),
            productImage=product.get("productImage"),
            productName=product.get("productName"),
            productPrice=product.get("productPrice"),
            productUrl=product.get("productUrl"),
            landingUrl=landing_url,
        )
        record = ProductSearchRecord(
            api=api_fields,
            collector=CollectorMetadata(
                requestedKeyword=requested_keyword,
                collectedAt=collected_at,
            ),
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


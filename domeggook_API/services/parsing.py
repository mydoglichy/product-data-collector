from __future__ import annotations

import copy
import re
from typing import Any


_NUMERIC_TEXT_RE = re.compile(r"^[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$")


def parse_list_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = _root(payload)
    item_container = _first_present(root, ("list", "items", "itemList", "data"))
    items = _first_present(item_container, ("item", "items")) if isinstance(item_container, dict) else item_container
    return [item for item in _as_list(items) if isinstance(item, dict)]


def parse_list_header(payload: dict[str, Any]) -> dict[str, Any]:
    root = _root(payload)
    header = root.get("header") if isinstance(root, dict) else None
    return header if isinstance(header, dict) else {}


def parse_product_id(item: dict[str, Any]) -> str | None:
    for key in ("no", "itemNo", "itemNoOrigin", "productId", "productNo"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    basis = item.get("basis")
    if isinstance(basis, dict):
        value = basis.get("no")
        if value not in (None, ""):
            return str(value)
    return None


def parse_detail_products(
    payload: dict[str, Any],
    collected_at: str,
    *,
    raw_limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    products: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    root = _root(payload)
    candidates = _detail_candidates(root)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        product_id = parse_product_id(candidate)
        error = candidate.get("error") if isinstance(candidate.get("error"), dict) else None
        if error:
            failures.append(
                {
                    "productId": product_id,
                    "error": _get(error, "message", "msg"),
                    "code": _get(error, "code"),
                }
            )
            continue
        include_raw = raw_limit is None or len(products) < raw_limit
        products.append(parse_detail_product(candidate, collected_at, include_raw=include_raw))
    return products, failures


def parse_detail_product(item: dict[str, Any], collected_at: str, *, include_raw: bool = True) -> dict[str, Any]:
    basis = _first_dict(item, ("basis",))
    price = _first_dict(item, ("price",))
    qty = _first_dict(item, ("qty",))
    dome = _first_dict(item, ("dome", "domeggook", "domestic", "marketDome"))
    supply = _first_dict(item, ("supply", "domeme", "marketSupply"))
    price_labeled = _first_dict(price, ("labeledPrice",))
    deli_dome = _first_dict(_first_dict(item, ("deli",)), ("dome",))
    deli_supply = _first_dict(_first_dict(item, ("deli",)), ("supply",))
    seller = _first_dict(item, ("seller", "sellerInfo", "mem", "member"))
    category = _first_dict(item, ("category", "cate", "cat"))
    category_current = _first_dict(category, ("current",))
    delivery = _first_dict(item, ("deli", "delivery", "deliveryInfo", "ship", "shipping"))
    fee_extra = _first_dict(delivery, ("feeExtra",))
    channel = _first_dict(item, ("channel",))
    dome_fee_raw = _coalesce(_get(deli_dome, "fee", "tbl"), _get(dome, "deliveryFee", "shipFee"))
    supply_fee_raw = _coalesce(_get(deli_supply, "fee", "tbl"), _get(supply, "deliveryFee", "shipFee"))
    image_urls = _image_urls(
        item.get("thumb"),
        item.get("image"),
        item.get("imageInfo"),
        item.get("img"),
        item.get("imageUrl"),
        item.get("productImage"),
    )

    product_id = parse_product_id(item)
    product = {
        "productId": product_id,
        "collectedAt": collected_at,
        "status": _coalesce(_get(basis, "status"), _get(item, "status", "itemStatus", "saleStatus")),
        "productName": _coalesce(_get(basis, "title"), _get(item, "title", "itemName", "name")),
        "registeredAt": _coalesce(_get(basis, "dateReg"), _get(item, "regDate", "regDt", "createdAt")),
        "saleStartedAt": _coalesce(_get(basis, "dateStart"), _get(item, "startDate", "saleStartDate", "saleStartedAt")),
        "saleEndedAt": _coalesce(_get(basis, "dateEnd"), _get(item, "endDate", "saleEndDate", "saleEndedAt")),
        "prices": {
            "domeCurrentSupplyPrice": _number(_coalesce(_get(price, "dome"), _get(dome, "price", "salePrice", "supplyPrice"))),
            "domeOriginalSupplyPrice": _number(_get(dome, "orgPrice", "originalPrice", "beforeDiscountPrice")),
            "supplyCurrentSupplyPrice": _number(_coalesce(_get(price, "supply"), _get(supply, "price", "salePrice", "supplyPrice"))),
            "supplyOriginalSupplyPrice": _number(_get(supply, "orgPrice", "originalPrice", "beforeDiscountPrice")),
            "minimumRetailPrice": _number(_coalesce(_get(price_labeled, "low", "minimum"), _get(item, "minPrice", "minimumRetailPrice", "lowPrice"))),
            "recommendedRetailPrice": _number(_coalesce(_get(price_labeled, "recommend", "recommended"), _get(item, "recommendPrice", "recommendedRetailPrice", "recPrice"))),
        },
        "inventory": {
            "stockQuantity": _number(_coalesce(_get(qty, "inventory"), _get(item, "stock", "stockQty", "quantity"))),
            "domeMoq": _number(_coalesce(_get(qty, "domeMoq"), _get(dome, "minOrderQty", "moq", "minimumOrderQuantity"))),
            "domeMaxOrderQuantity": _number(_get(dome, "maxOrderQty", "maximumOrderQuantity")),
            "domeOrderUnit": _number(_coalesce(_get(qty, "domeUnit"), _get(dome, "orderUnit", "unitQty", "unit"))),
            "supplyOrderUnit": _number(_coalesce(_get(qty, "supplyUnit"), _get(supply, "orderUnit", "unitQty", "unit"))),
        },
        "shipping": {
            "method": _get(delivery, "method", "deliveryMethod", "shipMethod"),
            "feePayer": _get(delivery, "who", "pay", "feePayer", "deliveryChargeType", "shipFeeType"),
            "domeFeePayer": _get(delivery, "pay", "who", "feePayer", "deliveryChargeType", "shipFeeType"),
            "domeFee": _number(dome_fee_raw),
            "domeFeeRaw": dome_fee_raw,
            "domeFeeType": _coalesce(_get(deli_dome, "type"), _get(dome, "deliveryFeeType", "shipFeeType")),
            "domeFeeTable": _get(deli_dome, "tbl"),
            "supplyFeePayer": _coalesce(
                _get(deli_supply, "pay", "who", "feePayer", "deliveryChargeType", "shipFeeType"),
                _get(delivery, "pay", "who", "feePayer", "deliveryChargeType", "shipFeeType"),
            ),
            "supplyFee": _number(supply_fee_raw),
            "supplyFeeRaw": supply_fee_raw,
            "supplyFeeType": _coalesce(_get(deli_supply, "type"), _get(supply, "deliveryFeeType", "shipFeeType")),
            "supplyFeeTable": _get(deli_supply, "tbl"),
            "feeExtraJeju": _number(_get(fee_extra, "jeju")),
            "feeExtraIslands": _number(_get(fee_extra, "islands")),
            "remoteAreaFee": {
                "jeju": _number(_get(fee_extra, "jeju")),
                "islands": _number(_get(fee_extra, "islands")),
            },
            "preparationPeriod": _number(_get(delivery, "wating", "preparationPeriod", "preparationDays", "readyDays")),
            "averageShippingDays": _number(_get(delivery, "sendAvg", "averageShippingDays", "avgDeliveryDays", "avgShipDays")),
            "fastShipping": _get(delivery, "fastDeli", "fastShipping", "quickDelivery", "isFastShipping"),
            "overseasDirectShipping": _get(delivery, "fromOversea", "overseasDirectShipping", "overseaDelivery", "isOverseasDirect"),
        },
        "markets": {
            "domeOnSale": _coalesce(_get(channel, "dome"), _get(dome, "onSale", "isSale", "enabled")),
            "supplyOnSale": _coalesce(_get(channel, "supply"), _get(supply, "onSale", "isSale", "enabled")),
        },
        "seller": {
            "id": _get(seller, "id", "sellerId", "userId"),
            "nickname": _get(seller, "nick", "nickname", "sellerNick"),
            "type": _get(seller, "type", "sellerType"),
            "grade": _get(seller, "rank", "grade", "sellerGrade"),
            "excellentSeller": _get(seller, "good", "excellentSeller", "isExcellentSeller", "goodSeller"),
            "averageSatisfaction": _coalesce(
                _get(_first_dict(seller, ("score",)), "average", "avg"),
                _get(seller, "averageSatisfaction", "avgSatisfaction", "satisfaction"),
            ),
            "reviewCount": _number(_coalesce(
                _get(_first_dict(seller, ("score",)), "count", "cnt"),
                _get(seller, "reviewCount", "feedbackCount", "opinionCount"),
            )),
        },
        "category": {
            "code": _get(category_current, "code") or _get(category, "code", "categoryCode", "cateCode"),
            "name": _get(category_current, "name") or _get(category, "name", "categoryName", "cateName"),
        },
    }
    if image_urls:
        product["imageUrl"] = image_urls[0]
    if len(image_urls) > 1:
        product["backupImageUrl"] = image_urls[1]
    if include_raw:
        product["raw"] = compact_raw_item_for_snapshot(item)
    return product


def compact_raw_item_for_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(item)
    for key in ("detail", "desc", "description", "content", "contents", "thumb", "image", "imageInfo", "img", "imageUrl"):
        result.pop(key, None)
    basis = result.get("basis")
    if isinstance(basis, dict):
        basis.pop("keywords", None)
    for key in ("keyword", "keywords"):
        result.pop(key, None)
    return result


def _detail_candidates(root: Any) -> list[Any]:
    if not isinstance(root, dict):
        return []
    for key in ("item", "items", "itemView", "data"):
        value = root.get(key)
        if value is None:
            continue
        if isinstance(value, dict) and any(child in value for child in ("item", "items")):
            nested = value.get("item", value.get("items"))
            return _as_list(nested)
        return _as_list(value)
    return [root]


def _root(payload: dict[str, Any]) -> dict[str, Any]:
    domeggook = payload.get("domeggook")
    return domeggook if isinstance(domeggook, dict) else payload


def _first_present(source: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(source, dict):
        return source
    for key in keys:
        if key in source:
            return source[key]
    return None


def _first_dict(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        value = source.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _get(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value is not None:
            return value
    return None


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _image_urls(*values: Any) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        for url in _iter_image_urls(value):
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def _iter_image_urls(value: Any):
    if isinstance(value, str):
        text = value.strip()
        if text:
            yield text
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_image_urls(item)
        return
    if isinstance(value, dict):
        for key in ("original", "url", "src", "imageUrl", "productImage", "large", "medium", "small"):
            if key in value:
                yield from _iter_image_urls(value.get(key))


def _number(value: Any) -> int | float | Any:
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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]

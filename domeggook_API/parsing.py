from __future__ import annotations

from typing import Any


def parse_list_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = _root(payload)
    item_container = _first_present(root, ("list", "items", "itemList", "data"))
    items = _first_present(item_container, ("item", "items")) if isinstance(item_container, dict) else item_container
    return [item for item in _as_list(items) if isinstance(item, dict)]


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


def parse_detail_products(payload: dict[str, Any], collected_at: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
        products.append(parse_detail_product(candidate, collected_at))
    return products, failures


def parse_detail_product(item: dict[str, Any], collected_at: str) -> dict[str, Any]:
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
    image = _first_dict(item, ("thumb", "image", "imageInfo", "img"))
    channel = _first_dict(item, ("channel",))
    keywords = _get(basis, "keywords") or _get(item, "keyword", "keywords")

    product_id = parse_product_id(item)
    return {
        "productId": product_id,
        "collectedAt": collected_at,
        "status": _get(basis, "status") or _get(item, "status", "itemStatus", "saleStatus"),
        "productName": _get(basis, "title") or _get(item, "title", "itemName", "name"),
        "keywords": keywords,
        "registeredAt": _get(basis, "dateReg") or _get(item, "regDate", "regDt", "createdAt"),
        "saleStartedAt": _get(basis, "dateStart") or _get(item, "startDate", "saleStartDate", "saleStartedAt"),
        "saleEndedAt": _get(basis, "dateEnd") or _get(item, "endDate", "saleEndDate", "saleEndedAt"),
        "prices": {
            "domeCurrentSupplyPrice": _get(price, "dome") or _get(dome, "price", "salePrice", "supplyPrice"),
            "domeOriginalSupplyPrice": _get(dome, "orgPrice", "originalPrice", "beforeDiscountPrice"),
            "supplyCurrentSupplyPrice": _get(price, "supply") or _get(supply, "price", "salePrice", "supplyPrice"),
            "supplyOriginalSupplyPrice": _get(supply, "orgPrice", "originalPrice", "beforeDiscountPrice"),
            "minimumRetailPrice": _get(price_labeled, "low", "minimum") or _get(item, "minPrice", "minimumRetailPrice", "lowPrice"),
            "recommendedRetailPrice": _get(price_labeled, "recommend", "recommended") or _get(item, "recommendPrice", "recommendedRetailPrice", "recPrice"),
        },
        "inventory": {
            "stockQuantity": _get(qty, "inventory") or _get(item, "stock", "stockQty", "quantity"),
            "domeMoq": _get(qty, "domeMoq") or _get(dome, "minOrderQty", "moq", "minimumOrderQuantity"),
            "domeMaxOrderQuantity": _get(dome, "maxOrderQty", "maximumOrderQuantity"),
            "domeOrderUnit": _get(qty, "domeUnit") or _get(dome, "orderUnit", "unitQty", "unit"),
            "supplyOrderUnit": _get(qty, "supplyUnit") or _get(supply, "orderUnit", "unitQty", "unit"),
        },
        "shipping": {
            "method": _get(delivery, "method", "deliveryMethod", "shipMethod"),
            "feePayer": _get(delivery, "pay", "feePayer", "deliveryChargeType", "shipFeeType"),
            "domeFee": _get(deli_dome, "fee") or _get(dome, "deliveryFee", "shipFee"),
            "domeFeeType": _get(deli_dome, "type") or _get(dome, "deliveryFeeType", "shipFeeType"),
            "supplyFee": _get(deli_supply, "fee") or _get(supply, "deliveryFee", "shipFee"),
            "supplyFeeType": _get(deli_supply, "type") or _get(supply, "deliveryFeeType", "shipFeeType"),
            "preparationPeriod": _get(delivery, "wating", "preparationPeriod", "preparationDays", "readyDays"),
            "averageShippingDays": _get(delivery, "sendAvg", "averageShippingDays", "avgDeliveryDays", "avgShipDays"),
            "fastShipping": _get(delivery, "fastDeli", "fastShipping", "quickDelivery", "isFastShipping"),
            "overseasDirectShipping": _get(delivery, "fromOversea", "overseasDirectShipping", "overseaDelivery", "isOverseasDirect"),
        },
        "markets": {
            "domeOnSale": _get(channel, "dome") or _get(dome, "onSale", "isSale", "enabled"),
            "supplyOnSale": _get(channel, "supply") or _get(supply, "onSale", "isSale", "enabled"),
        },
        "seller": {
            "id": _get(seller, "id", "sellerId", "userId"),
            "nickname": _get(seller, "nick", "nickname", "sellerNick"),
            "type": _get(seller, "type", "sellerType"),
            "grade": _get(seller, "rank", "grade", "sellerGrade"),
            "excellentSeller": _get(seller, "good", "excellentSeller", "isExcellentSeller", "goodSeller"),
            "averageSatisfaction": _get(_first_dict(seller, ("score",)), "average") or _get(seller, "averageSatisfaction", "avgSatisfaction", "satisfaction"),
            "reviewCount": _get(_first_dict(seller, ("score",)), "count") or _get(seller, "reviewCount", "feedbackCount", "opinionCount"),
        },
        "category": {
            "code": _get(category_current, "code") or _get(category, "code", "categoryCode", "cateCode"),
            "name": _get(category_current, "name") or _get(category, "name", "categoryName", "cateName"),
        },
        "image": {
            "representativeUrl": _get(image, "original", "large", "url", "representativeUrl", "mainImageUrl") or _get(item, "imageUrl", "thumb", "img"),
            "lastChangedAt": _get(image, "lastUpdate", "lastChangedAt", "imageChangedAt", "imgLastDate"),
        },
        "raw": item,
    }


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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]

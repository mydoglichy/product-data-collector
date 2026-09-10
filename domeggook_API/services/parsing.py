from __future__ import annotations

import copy
from typing import Any
from urllib.parse import quote

from numeric_utils import parse_number


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
    price_labeled = _first_dict(item, ("labeledPrice",)) or _first_dict(price, ("labeledPrice",))
    price_resale = _first_dict(price, ("resale",))
    deli_dome = _first_dict(_first_dict(item, ("deli",)), ("dome",))
    deli_supply = _first_dict(_first_dict(item, ("deli",)), ("supply",))
    seller = _first_dict(item, ("seller", "sellerInfo", "mem", "member"))
    category = _first_dict(item, ("category", "cate", "cat"))
    category_current = _first_dict(category, ("current",))
    category_parents = _first_dict(category, ("parents",))
    delivery = _first_dict(item, ("deli", "delivery", "deliveryInfo", "ship", "shipping"))
    fee_extra = _first_dict(delivery, ("feeExtra",))
    merge = _first_dict(delivery, ("merge",))
    detail = _first_dict(item, ("detail",))
    desc = _first_dict(item, ("desc",))
    desc_license = _first_dict(desc, ("license",))
    return_policy = _first_dict(item, ("return", "returnPolicy"))
    popular = _first_dict(item, ("popular",))
    price_compare = _first_dict(item, ("priceCompare",))
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
        "productUrl": product_url(product_id, item, basis),
        "registeredAt": _coalesce(_get(basis, "dateReg"), _get(item, "regDate", "regDt", "createdAt")),
        "saleStartedAt": _coalesce(_get(basis, "dateStart"), _get(item, "startDate", "saleStartDate", "saleStartedAt")),
        "saleEndedAt": _coalesce(_get(basis, "dateEnd"), _get(item, "endDate", "saleEndDate", "saleEndedAt")),
        "prices": {
            "domeCurrentSupplyPrice": _number(_coalesce(_get(price, "dome"), _get(dome, "price", "salePrice", "supplyPrice"))),
            "domeOriginalSupplyPrice": _number(_coalesce(_get(price, "domeOrg"), _get(dome, "orgPrice", "originalPrice", "beforeDiscountPrice"))),
            "samplePrice": _number(_get(price, "sample")),
            "sampleDiscountBasis": _number(_get(price, "sampleDiscountBasis")),
            "supplyCurrentSupplyPrice": _number(_coalesce(_get(price, "supply"), _get(supply, "price", "salePrice", "supplyPrice"))),
            "supplyOriginalSupplyPrice": _number(_coalesce(_get(price, "supplyOrg"), _get(supply, "orgPrice", "originalPrice", "beforeDiscountPrice"))),
            "useLabeledPrice": _get(price_labeled, "useLabeledPrice"),
            "labeledCapacity": _number(_get(price_labeled, "labeledCapacity")),
            "labeledUnit": _get(price_labeled, "labeledUnit"),
            "labeledUnitPrice": _first_dict(price_labeled, ("unitPrice",)),
            "minimumRetailPrice": _number(_coalesce(_get(price_labeled, "low", "minimum"), _get(item, "minPrice", "minimumRetailPrice", "lowPrice"))),
            "recommendedRetailPrice": _number(_coalesce(_get(price_labeled, "recommend", "recommended"), _get(item, "recommendPrice", "recommendedRetailPrice", "recPrice"))),
            "resaleMinimumPrice": _number(_get(price_resale, "minimum", "minumum")),
            "resaleRecommendedPrice": _number(_get(price_resale, "Recommand", "recommend", "recommended")),
        },
        "inventory": {
            "stockQuantity": _number(_coalesce(_get(qty, "inventory"), _get(item, "stock", "stockQty", "quantity"))),
            "domeMoq": _number(_coalesce(_get(qty, "domeMoq"), _get(dome, "minOrderQty", "moq", "minimumOrderQuantity"))),
            "domeMaxOrderQuantity": _number(_coalesce(_get(qty, "domeLoq"), _get(dome, "maxOrderQty", "maximumOrderQuantity"))),
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
            "remoteAreaFee": _remote_area_fee(fee_extra),
            "preparationPeriod": _number(_get(delivery, "wating", "preparationPeriod", "preparationDays", "readyDays")),
            "preparationPeriodDays": _number(_get(delivery, "periodDeli")),
            "averageShippingDays": _number(_get(delivery, "sendAvg", "averageShippingDays", "avgDeliveryDays", "avgShipDays")),
            "fastShipping": _get(delivery, "fastDeli", "fastShipping", "quickDelivery", "isFastShipping"),
            "overseasDirectShipping": _get(delivery, "fromOversea", "overseasDirectShipping", "overseaDelivery", "isOverseasDirect"),
            "customsClearanceNumberRequired": _get(delivery, "reqCcno"),
            "shippingArea": _get(delivery, "shippingArea"),
            "bundleShipping": {
                "enabled": _get(merge, "enable"),
                "basePrice": _number(_get(merge, "basePrice")),
            },
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
            "depth": _number(_get(category_current, "depth")),
            "parents": _category_parent_elements(category_parents),
        },
        "sourceSpecific": {
            "basis": {
                "section": _get(basis, "section"),
                "nego": _get(basis, "nego"),
                "adult": _get(basis, "adult"),
                "secretItem": _get(basis, "secretItem"),
                "tax": _get(basis, "tax"),
            },
            "directSale": _get(basis, "section") == "직접판매",
            "distributionRiskStatus": _distribution_risk_status(_coalesce(_get(basis, "status"), _get(item, "status", "itemStatus", "saleStatus"))),
            "taxInvoiceRisk": _tax_invoice_risk(_get(seller, "type", "sellerType")),
            "seller": {
                "global": _get(seller, "global"),
                "power": _get(seller, "power"),
                "company": _first_dict(seller, ("company",)),
                "vacation": _first_dict(seller, ("vacation",)),
            },
            "detail": {
                "size": _get(detail, "size"),
                "weight": _get(detail, "weight"),
                "country": _get(detail, "country"),
                "manufacturer": _get(detail, "manufacturer"),
                "model": _get(detail, "model"),
                "oversea": _get(detail, "oversea"),
                "itemCustomCode": _get(detail, "itemCustomCode"),
                "safetyCert": _first_dict(detail, ("safetyCert",)),
                "infoDuty": _first_dict(detail, ("infoDuty",)),
            },
            "category": {
                "current": category_current,
                "parents": _category_parent_elements(category_parents),
            },
            "popular": popular,
            "priceCompare": price_compare,
            "returnPolicy": {
                "deliAmt": _number(_get(return_policy, "deliAmt")),
                "deliAmtDouble": _get(return_policy, "deliAmtDouble"),
            },
            "descriptionLicense": desc_license,
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


def product_url(product_id: str | None, *sources: dict[str, Any]) -> str | None:
    for source in sources:
        for key in ("productUrl", "productURL", "url", "link", "itemUrl", "itemURL"):
            value = source.get(key)
            if value in (None, ""):
                continue
            explicit_url = str(value).strip()
            if explicit_url:
                return explicit_url
    if not product_id:
        return None
    return f"https://www.domeggook.com/{quote(product_id, safe='')}"


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


def _category_parent_elements(parents: dict[str, Any]) -> list[dict[str, Any]]:
    elems = parents.get("elem") if isinstance(parents, dict) else None
    result: list[dict[str, Any]] = []
    for elem in _as_list(elems):
        if not isinstance(elem, dict):
            continue
        result.append(
            {
                "code": _get(elem, "code"),
                "name": _get(elem, "name"),
                "depth": _number(_get(elem, "depth")),
            }
        )
    return result


def _remote_area_fee(fee_extra: dict[str, Any]) -> dict[str, Any]:
    candidates = {
        "jeju": _number(_get(fee_extra, "jeju")),
        "islands": _number(_get(fee_extra, "islands")),
        "useQuantityProportional": _get(fee_extra, "useDeliPro"),
    }
    return {key: value for key, value in candidates.items() if value is not None}


def _distribution_risk_status(status: Any) -> str | None:
    if not isinstance(status, str):
        return None
    text = status.strip()
    return text if text in {"승인거부", "아웃벌점 제재"} else None


def _tax_invoice_risk(seller_type: Any) -> bool | None:
    if not isinstance(seller_type, str) or not seller_type.strip():
        return None
    return seller_type.strip() in {"간이과세자", "개인판매자"}


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
    return parse_number(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]

from domeggook_API.parsing import parse_detail_products, parse_list_items, parse_product_id


def test_parse_list_items_and_product_id_from_document_style_payload():
    payload = {
        "domeggook": {
            "list": {
                "item": [
                    {"no": "12345678", "title": "상품 A"},
                    {"itemNo": 98765432, "title": "상품 B"},
                ]
            }
        }
    }

    items = parse_list_items(payload)

    assert [parse_product_id(item) for item in items] == ["12345678", "98765432"]


def test_optional_detail_fields_are_saved_as_none():
    payload = {"domeggook": {"item": [{"no": "12345678", "title": "상품 A"}]}}

    products, failures = parse_detail_products(payload, "2026-08-22T09:00:00+09:00")

    assert failures == []
    assert products[0]["productId"] == "12345678"
    assert products[0]["productName"] == "상품 A"
    assert products[0]["status"] is None
    assert products[0]["prices"]["domeCurrentSupplyPrice"] is None
    assert products[0]["seller"]["nickname"] is None
    assert products[0]["image"]["representativeUrl"] is None


def test_real_detail_nested_shape_is_parsed():
    payload = {
        "domeggook": {
            "item": [
                {
                    "basis": {
                        "no": "12345678",
                        "status": "판매중",
                        "title": "상품 A",
                        "keywords": {"item": ["안경", "케이스"]},
                        "dateReg": "2026-08-20",
                        "dateStart": "2026-08-21",
                        "dateEnd": "2026-12-31",
                    },
                    "price": {
                        "dome": "1~9개: 2,000원 / 10개 이상: 1,800원",
                        "supply": 1700,
                        "labeledPrice": {"low": 2500, "recommend": 3000},
                    },
                    "qty": {"inventory": "999", "domeMoq": "2", "domeUnit": 1, "supplyUnit": 1},
                    "deli": {
                        "method": "택배",
                        "pay": "선결제",
                        "dome": {"fee": 3000, "type": "fixed"},
                        "supply": {"fee": 2500, "type": "fixed"},
                        "wating": "2",
                        "sendAvg": "1.5",
                        "fastDeli": "Y",
                        "fromOversea": "N",
                    },
                    "channel": {"dome": "Y", "supply": "Y"},
                    "seller": {"id": "seller1", "nick": "판매자", "type": "사업자", "rank": "A", "good": "Y"},
                    "category": {"current": {"code": "1010", "name": "잡화"}},
                    "thumb": {"original": "https://image", "lastUpdate": "2026-08-22"},
                }
            ]
        }
    }

    products, failures = parse_detail_products(payload, "2026-08-22T09:00:00+09:00")

    assert failures == []
    product = products[0]
    assert product["productId"] == "12345678"
    assert product["status"] == "판매중"
    assert product["prices"]["domeCurrentSupplyPrice"] == "1~9개: 2,000원 / 10개 이상: 1,800원"
    assert product["prices"]["supplyCurrentSupplyPrice"] == 1700
    assert product["inventory"]["stockQuantity"] == "999"
    assert product["shipping"]["domeFee"] == 3000
    assert product["markets"]["supplyOnSale"] == "Y"
    assert product["seller"]["nickname"] == "판매자"
    assert product["category"]["code"] == "1010"
    assert product["image"]["representativeUrl"] == "https://image"


def test_tiered_price_string_is_preserved_without_int_casting():
    payload = {
        "domeggook": {
            "item": [
                {
                    "no": "12345678",
                    "dome": {"price": "1~9개: 2,000원 / 10개 이상: 1,800원"},
                    "supply": {"price": "1,700"},
                }
            ]
        }
    }

    products, _ = parse_detail_products(payload, "2026-08-22T09:00:00+09:00")

    assert products[0]["prices"]["domeCurrentSupplyPrice"] == "1~9개: 2,000원 / 10개 이상: 1,800원"
    assert products[0]["prices"]["supplyCurrentSupplyPrice"] == "1,700"


def test_detail_item_level_error_does_not_drop_batch():
    payload = {
        "domeggook": {
            "item": [
                {"no": "1", "title": "ok"},
                {"no": "2", "error": {"code": "404", "message": "not found"}},
            ]
        }
    }

    products, failures = parse_detail_products(payload, "2026-08-22T09:00:00+09:00")

    assert [product["productId"] for product in products] == ["1"]
    assert failures == [{"productId": "2", "error": "not found", "code": "404"}]

from __future__ import annotations

from product_history import (
    append_collection_run,
    get_recent_price_quantity_history,
    normalize_current_product,
    upsert_product_changes,
)


def test_new_product_writes_current_and_initial_history(tmp_path):
    stats = _upsert(tmp_path, [_product()])

    assert stats["newProductCount"] == 1
    history = _load(tmp_path / "history.json")
    assert len(history["records"]) == 1
    assert history["records"][0]["changeType"] == "initial"
    assert history["records"][0]["platform"] == "ownerclan"
    assert history["records"][0]["externalProductId"] == "P1"


def test_unchanged_product_only_updates_last_checked_at(tmp_path):
    _upsert(tmp_path, [_product()], at="2026-08-01T00:00:00+09:00")
    stats = _upsert(tmp_path, [_product()], at="2026-08-02T00:00:00+09:00")

    current = _load(tmp_path / "current.json")
    assert stats["unchangedProductCount"] == 1
    assert len(_load(tmp_path / "history.json")["records"]) == 1
    assert current["products"]["ownerclan:P1"]["lastCheckedAt"] == "2026-08-02T00:00:00+09:00"


def test_price_only_change_writes_one_update(tmp_path):
    _upsert(tmp_path, [_product(price="₩1,000")])
    stats = _upsert(tmp_path, [_product(price=1200)])

    assert stats["changedProductCount"] == 1
    record = _load(tmp_path / "history.json")["records"][-1]
    assert record["changedFields"] == ["prices.currentSupplyPrice"]


def test_stock_only_change_writes_one_update(tmp_path):
    _upsert(tmp_path, [_product(stock=7)])
    _upsert(tmp_path, [_product(stock=0)])

    record = _load(tmp_path / "history.json")["records"][-1]
    assert record["changedFields"] == ["inventory.stockQuantity"]


def test_multiple_analysis_fields_change_together(tmp_path):
    _upsert(tmp_path, [_product(price=1000, stock=7, shipping_fee=3000)])
    _upsert(tmp_path, [_product(price=1100, stock=3, shipping_fee=0)])

    fields = _load(tmp_path / "history.json")["records"][-1]["changedFields"]
    assert fields == ["inventory.stockQuantity", "prices.currentSupplyPrice", "shipping.fee"]


def test_url_image_and_name_changes_do_not_write_history(tmp_path):
    _upsert(tmp_path, [_product(name="old", url="https://example.com/p?utm_source=a", image="https://cdn/a.jpg?v=1")])
    stats = _upsert(tmp_path, [_product(name="new", url="https://example.com/p?utm_source=b", image="https://cdn2/a.jpg?v=2")])

    current = _load(tmp_path / "current.json")["products"]["ownerclan:P1"]["current"]
    assert stats["unchangedProductCount"] == 1
    assert len(_load(tmp_path / "history.json")["records"]) == 1
    assert current["productName"] == "new"
    assert current["productUrl"] == "https://example.com/p"
    assert current["imageUrl"] == "https://cdn2/a.jpg"


def test_tracking_query_only_change_is_normalized_in_current(tmp_path):
    current = normalize_current_product(_product(url="https://shop/p?item=1&utm_campaign=x&gclid=y"))

    assert current["productUrl"] == "https://shop/p?item=1"


def test_option_order_only_change_does_not_write_history(tmp_path):
    first = _product(options=[_option("B", 200, 2), _option("A", 100, 1)])
    second = _product(options=[_option("A", "100", "1"), _option("B", "200", "2")])
    _upsert(tmp_path, [first])
    stats = _upsert(tmp_path, [second])

    assert stats["unchangedProductCount"] == 1
    assert len(_load(tmp_path / "history.json")["records"]) == 1


def test_api_field_missing_null_zero_and_soldout_are_distinct(tmp_path):
    _upsert(tmp_path, [_product(stock=None, status="available")])
    _upsert(tmp_path, [_product_without_inventory(status="available")])
    _upsert(tmp_path, [_product(stock=0, status="available")])
    _upsert(tmp_path, [_product(stock=0, status="soldout")])

    records = _load(tmp_path / "history.json")["records"]
    assert len(records) == 4
    assert records[1]["changedFields"] == ["inventory.stockQuantity"]
    assert records[2]["changedFields"] == ["inventory.stockQuantity"]
    assert records[3]["changedFields"] == ["status"]


def test_same_run_duplicate_product_does_not_duplicate_history(tmp_path):
    stats = _upsert(tmp_path, [_product(), _product()])

    assert stats["newProductCount"] == 1
    assert stats["checkedCount"] == 1
    assert len(_load(tmp_path / "history.json")["records"]) == 1


def test_partial_api_failure_is_recorded_as_run_failure_not_no_change(tmp_path):
    _upsert(tmp_path, [_product()])
    run = append_collection_run(
        tmp_path / "runs.json",
        platform="ownerclan",
        started_at="2026-08-01T00:00:00+09:00",
        ended_at="2026-08-01T00:01:00+09:00",
        success=False,
        queried_product_count=2,
        new_product_count=1,
        changed_product_count=0,
        unchanged_product_count=0,
        failed_product_count=1,
    )

    assert run["success"] is False
    assert run["failedProductCount"] == 1


def test_recent_30_day_history_reconstructs_carried_values_and_stats(tmp_path):
    _upsert(tmp_path, [_product(price=1000, stock=10)], at="2026-08-01T00:00:00+09:00")
    _upsert(tmp_path, [_product(price=900, stock=10)], at="2026-08-10T00:00:00+09:00")
    _upsert(tmp_path, [_product(price=900, stock=3)], at="2026-08-20T00:00:00+09:00")

    result = get_recent_price_quantity_history(
        history_path=tmp_path / "history.json",
        platform="ownerclan",
        external_product_id="P1",
        days=30,
        end_at="2026-08-30T00:00:00+09:00",
    )

    assert result["lowestPrice"] == 900
    assert result["highestPrice"] == 1000
    assert result["priceChangeCount"] == 1
    assert result["quantityChangeCount"] == 1
    assert result["daily"][0]["state"]["prices"]["currentSupplyPrice"] == 1000
    assert result["daily"][-1]["state"]["inventory"]["stockQuantity"] == 3


def _upsert(tmp_path, products, at="2026-08-01T00:00:00+09:00"):
    return upsert_product_changes(
        platform="ownerclan",
        current_path=tmp_path / "current.json",
        history_path=tmp_path / "history.json",
        collected_at=at,
        products=products,
    )


def _product(
    *,
    product_id="P1",
    price=1000,
    stock=7,
    shipping_fee=3000,
    status="available",
    name="name",
    url="https://example.com/p",
    image="https://cdn/a.jpg",
    options=None,
):
    return {
        "productId": product_id,
        "productName": name,
        "productUrl": url,
        "imageUrl": image,
        "prices": {"currentSupplyPrice": price},
        "inventory": {"stockQuantity": stock},
        "shipping": {"fee": shipping_fee},
        "options": options if options is not None else [_option("A", 100, 1)],
        "status": status,
    }


def _product_without_inventory(**kwargs):
    product = _product(**kwargs)
    product.pop("inventory")
    return product


def _option(key, price, quantity):
    return {"skuKey": key, "price": price, "quantity": quantity}


def _load(path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))

from pathlib import Path

from ownerclan_API.client import OwnerclanGraphQLError
from ownerclan_API.collect_product_details import collect_details, fetch_items_batch
from ownerclan_API.config import (
    DetailsConfig,
    DiscoveryConfig,
    IncrementalConfig,
    OutputConfig,
    OwnerclanConfig,
    RequestConfig,
)
from ownerclan_API.discover_products import discover
from ownerclan_API.normalization import calculate_total_stock, normalize_item, normalize_options
from ownerclan_API.storage import (
    atomic_write_json,
    load_json_object,
    load_tracked_products,
)
from ownerclan_API.sync_incremental import sync_incremental


class FakeClient:
    def __init__(self):
        self.queries = []
        self.last_detail_strategy = None

    def graphql(self, query):
        self.queries.append(query)
        if "allItems" in query and "search:" in query:
            return {
                "allItems": {
                    "pageInfo": {"hasNextPage": False, "endCursor": "c1"},
                    "edges": [
                        {"cursor": "c1", "node": _item("W1")},
                        {"cursor": "c2", "node": _item("W2")},
                    ],
                }
            }
        if "items(" in query:
            return {"items": [_item("W1"), _item("W2")]}
        if "allItems" in query and "dateFrom" in query:
            return {
                "allItems": {
                    "pageInfo": {"hasNextPage": False, "endCursor": "end"},
                    "edges": [{"cursor": "a", "node": _item("W3", updated_at=123)}],
                }
            }
        return {}


def test_keyword_default_and_new_search_and_dedupes_product_keys(tmp_path):
    config = _config(tmp_path)
    config.discovery.keyword_file.write_text("case\ncase\n", encoding="utf-8")
    client = FakeClient()
    saved_ranks = []

    def save_ranks(**kwargs):
        saved_ranks.extend(kwargs["records"])
        return len(saved_ranks)

    import ownerclan_API.discover_products as discover_module
    original = discover_module.save_search_ranks_if_enabled
    discover_module.save_search_ranks_if_enabled = save_ranks

    try:
        result = discover(tmp_path, config, client=client)
    finally:
        discover_module.save_search_ranks_if_enabled = original

    assert result["discoveredCount"] == 4
    assert result["newProductCount"] == 2
    assert len(client.queries) == 2
    assert "sortBy:" not in client.queries[0]
    assert "sortBy: registerDateDesc" in client.queries[1]
    tracked = load_tracked_products(config.output.tracked_products_path)
    assert set(tracked) == {"W1", "W2"}
    assert "searchTypes" not in tracked["W1"]
    assert tracked["W1"]["reasons"] == ["default", "registerDateDesc"]
    assert not list(config.output.output_dir.glob("ownerclan_*_search-ranks.json"))
    ranks = saved_ranks
    assert {record["sortBy"] for record in ranks} == {"default", "registerDateDesc"}
    assert all("searchType" not in record for record in ranks)


def test_multiple_item_query_falls_back_to_items_by_keys_then_single_item():
    class FallbackClient:
        def __init__(self):
            self.calls = []

        def graphql(self, query):
            self.calls.append(query)
            if "items(" in query:
                raise OwnerclanGraphQLError([{"message": "Cannot query field items"}])
            if "itemsByKeys" in query:
                raise OwnerclanGraphQLError([{"message": "Cannot query field itemsByKeys"}])
            return {"item": _item("W1")}

    client = FallbackClient()
    items = fetch_items_batch(client, ["W1"])

    assert [item["key"] for item in items] == ["W1"]
    assert len(client.calls) == 3


def test_collect_details_saves_products_to_postgres_without_json_outputs(tmp_path):
    config = _config(tmp_path)
    atomic_write_json(config.output.tracked_products_path, {"W1": {"productId": "W1", "active": True}})
    client = FakeClient()
    saved = {"raw": [], "snapshots": []}

    import ownerclan_API.collect_product_details as collect_module
    original_raw = collect_module.save_product_raw_samples_if_enabled
    original_snapshots = collect_module.save_product_snapshots_if_enabled
    collect_module.save_product_raw_samples_if_enabled = lambda **kwargs: saved["raw"].append(kwargs) or 1
    collect_module.save_product_snapshots_if_enabled = lambda **kwargs: saved["snapshots"].append(kwargs) or 1

    try:
        result = collect_details(tmp_path, config, client=client)
    finally:
        collect_module.save_product_raw_samples_if_enabled = original_raw
        collect_module.save_product_snapshots_if_enabled = original_snapshots

    assert result["successCount"] == 2
    assert len(saved["raw"]) == 1
    assert len(saved["snapshots"]) == 1
    saved_products = list(saved["snapshots"][0]["products"])
    assert saved_products
    assert all("raw" not in product for product in saved_products)
    assert not (config.output.state_dir / "latest-products.json").exists()
    assert not list(config.output.output_dir.glob("ownerclan_*_product-snapshots.json"))
    assert not list((config.output.output_dir.parent / "raw").glob("ownerclan_*_raw.json"))
    assert not list((config.output.output_dir.parent / "history").glob("ownerclan_*_product-history.json"))


def test_cursor_pagination_and_repeated_cursor_stops(tmp_path):
    class PagingClient:
        def __init__(self):
            self.count = 0

        def graphql(self, query):
            self.count += 1
            return {
                "allItems": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "same"},
                    "edges": [{"cursor": "same", "node": _item(f"W{self.count}", updated_at=self.count)}],
                }
            }

    config = _config(tmp_path)
    result = sync_incremental(tmp_path, config, client=PagingClient())

    assert result["pageCount"] == 2
    assert result["successCount"] == 2
    state = load_json_object(config.output.state_dir / "incremental-state.json")
    assert state["lastSuccessfulItemSyncAt"]


def test_incremental_failure_does_not_update_state(tmp_path):
    class FailingClient:
        def graphql(self, query):
            raise RuntimeError("boom")

    config = _config(tmp_path)
    result = sync_incremental(tmp_path, config, client=FailingClient())

    assert result["failureCount"] == 1
    assert not (config.output.state_dir / "incremental-state.json").exists()


def test_incremental_item_limit_stops_after_requested_items(tmp_path):
    class ManyItemsClient:
        def graphql(self, query):
            return {
                "allItems": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "next"},
                    "edges": [
                        {"cursor": "a", "node": _item("W1", updated_at=1)},
                        {"cursor": "b", "node": _item("W2", updated_at=2)},
                    ],
                }
            }

    config = _config(tmp_path)
    result = sync_incremental(tmp_path, config, item_limit=1, client=ManyItemsClient())

    assert result["successCount"] == 1
    tracked = load_tracked_products(config.output.tracked_products_path)
    assert tracked["W1"]["keywords"] == []
    assert "searchTypes" not in tracked["W1"]
    assert tracked["W1"]["reasons"] == ["updated_date_range"]


def test_options_stock_status_normalization_and_source_specific_preserved():
    item = _item(
        "W9",
        options=[
            {"optionAttributes": [], "price": 1000, "quantity": 2},
            {"optionAttributes": [{"name": "color", "value": "black"}], "price": 1200, "quantity": "3"},
        ],
    )
    item["status"] = "unavailable"
    item["pricePolicy"] = "fixed"
    item["openmarketSellable"] = False
    item["metadata"] = {"vendorKey": "V1"}

    product = normalize_item(item, "2026-08-24T00:00:00+09:00")

    assert product["options"][0]["skuType"] == "default"
    assert product["options"][1]["optionAttributes"] == [{"name": "color", "value": "black"}]
    assert product["inventory"]["stockQuantity"] == 5
    assert product["inventory"]["stockQuantitySource"] == "sum(options[].quantity)"
    assert product["status"] == "unavailable"
    assert product["sourceSpecific"]["pricePolicy"] == "fixed"
    assert product["sourceSpecific"]["vendorKey"] == "V1"


def test_metadata_content_keywords_and_images_are_not_saved():
    item = _item("W10")
    item["images"] = ["https://example.com/a.jpg", "https://example.com/a.jpg"]
    item["metadata"] = {
        "vendorKey": "V1",
        "productNotificationInformation": {
            "categorySpecific": [
                "?곹뭹 ?곸꽭?뺣낫??蹂꾨룄 ?쒓린",
                "?곹뭹 ?곸꽭?뺣낫??蹂꾨룄 ?쒓린",
                "?먮ℓ???곕씫泥?李멸퀬",
            ],
            "common": [
                "?곹뭹 ?곸꽭?뺣낫??蹂꾨룄 ?쒓린",
                "?곹뭹 ?곸꽭?뺣낫??蹂꾨룄 ?쒓린",
                "?곹뭹 ?곸꽭?뺣낫??蹂꾨룄 ?쒓린",
                "?곹뭹 ?곸꽭?뺣낫??蹂꾨룄 ?쒓린",
            ],
        },
    }

    product = normalize_item(item, "2026-08-24T00:00:00+09:00")

    assert "metadata" not in product["sourceSpecific"]
    assert "content" not in product["sourceSpecific"]
    assert "keywords" not in product
    assert "image" not in product
    assert "metadata" not in product["raw"]
    assert "content" not in product["raw"]
    assert "searchKeywords" not in product["raw"]
    assert "images" not in product["raw"]


def test_load_json_object_accepts_utf8_bom(tmp_path):
    path = tmp_path / "bom.json"
    path.write_text("{}", encoding="utf-8-sig")

    assert load_json_object(path) == {}


def test_total_stock_ignores_missing_quantities():
    options = normalize_options([{"optionAttributes": [], "quantity": None}, {"optionAttributes": [], "quantity": 4}])

    assert calculate_total_stock(options) == 4


def test_numeric_ownerclan_strings_are_cast_for_db_ready_fields():
    item = _item(
        "W11",
        options=[
            {"optionAttributes": [], "price": "1,500", "quantity": "5"},
            {"optionAttributes": [{"name": "size", "value": "L"}], "price": "2,000", "quantity": "3"},
        ],
    )
    item["price"] = "8,250"
    item["fixedPrice"] = "9,900"
    item["quantity"] = "10"
    item["shippingFee"] = "3,000"
    item["boxQuantity"] = "12"
    item["guaranteedShippingPeriod"] = "2"
    item["metadata"]["certificateInformation"] = [{"type": "KC", "code": "ABC"}]
    item["metadata"]["grade"] = "GOLD1"
    item["metadata"]["gradeDetail"] = {"averageShip": "GOOD"}

    product = normalize_item(item, "2026-08-24T00:00:00+09:00")

    assert product["prices"]["currentSupplyPrice"] == 8250
    assert product["prices"]["fixedPrice"] == 9900
    assert product["inventory"]["apiStockQuantity"] == 10
    assert product["inventory"]["stockQuantity"] == 8
    assert product["options"][0]["price"] == 1500
    assert product["options"][0]["quantity"] == 5
    assert product["shipping"]["fee"] == 3000
    assert product["sourceSpecific"]["boxQuantity"] == 12
    assert product["sourceSpecific"]["guaranteedShippingPeriod"] == 2
    assert product["sourceSpecific"]["certificateInformation"] == [{"type": "KC", "code": "ABC"}]
    assert product["sourceSpecific"]["grade"] == "GOLD1"
    assert product["sourceSpecific"]["gradeDetail"] == {"averageShip": "GOOD"}


def _config(tmp_path: Path):
    api_dir = tmp_path / "ownerclan_API"
    data_dir = api_dir / "data"
    output_dir = data_dir / "processed"
    state_dir = data_dir / "state"
    log_dir = data_dir / "logs"
    api_dir.mkdir(exist_ok=True)
    keyword_file = api_dir / "keywords.txt"
    keyword_file.write_text("case\n", encoding="utf-8")
    return OwnerclanConfig(
        environment="production",
        discovery=DiscoveryConfig(keyword_file, 2, 2),
        details=DetailsConfig(batch_size=2),
        incremental=IncrementalConfig(page_size=2, overlap_minutes=120, include_item_histories=False),
        request=RequestConfig(interval_seconds=0, timeout_seconds=10, max_retries=0, retry_after_max_seconds=1),
        output=OutputConfig(state_dir / "tracked_products.json", output_dir, state_dir, log_dir, 3),
        timezone="Asia/Seoul",
    )


def _item(key, *, name=None, updated_at="2026-08-24T00:00:00+09:00", options=None):
    return {
        "createdAt": "2026-08-23T00:00:00+09:00",
        "updatedAt": updated_at,
        "key": key,
        "id": f"id-{key}",
        "name": name or f"?곹뭹 {key}",
        "model": "M",
        "production": "Maker",
        "origin": "KR",
        "price": 1000,
        "pricePolicy": "free",
        "fixedPrice": 1500,
        "searchKeywords": ["case"],
        "category": {"key": "C1", "name": "cat", "fullName": "root > cat"},
        "content": "<p>detail</p>",
        "shippingFee": 3000,
        "shippingType": "inAdvance",
        "images": ["https://example.com/a.jpg"],
        "status": "available",
        "options": options if options is not None else [{"optionAttributes": [], "price": 1000, "quantity": 7}],
        "taxFree": False,
        "adultOnly": False,
        "returnable": True,
        "noReturnReason": None,
        "guaranteedShippingPeriod": 3,
        "openmarketSellable": True,
        "boxQuantity": 5,
        "attributes": [],
        "closingTime": None,
        "returnCriteria": None,
        "metadata": {"vendorKey": "V"},
    }

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
    append_search_ranks,
    atomic_write_json,
    load_json_object,
    load_tracked_products,
    migrate_sortby_schema,
    save_raw_samples,
    update_latest_and_history,
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

    result = discover(tmp_path, config, client=client)

    assert result["discoveredCount"] == 4
    assert result["newProductCount"] == 2
    assert len(client.queries) == 2
    assert "sortBy:" not in client.queries[0]
    assert "sortBy: registerDateDesc" in client.queries[1]
    tracked = load_tracked_products(config.output.tracked_products_path)
    assert set(tracked) == {"W1", "W2"}
    assert "searchTypes" not in tracked["W1"]
    assert tracked["W1"]["reasons"] == ["default", "registerDateDesc"]
    rank_files = list(config.output.output_dir.glob("ownerclan_*_search-ranks.json"))
    ranks = load_json_object(rank_files[0])["ranks"]
    assert {record["sortBy"] for record in ranks} == {"default", "registerDateDesc"}
    assert all("searchType" not in record for record in ranks)


def test_search_rank_history_keeps_same_product_at_different_ranks(tmp_path):
    path = tmp_path / "ownerclan_2026_0822_0900_search-ranks.json"
    records = [
        {
            "collectedAt": "2026-08-22T09:00:00+09:00",
            "keyword": "case",
            "sortBy": "default",
            "productId": "W1",
            "rank": 1,
        },
        {
            "collectedAt": "2026-08-22T09:00:00+09:00",
            "keyword": "case",
            "sortBy": "default",
            "productId": "W1",
            "rank": 2,
        },
    ]

    payload = append_search_ranks(path, records + [records[0]])

    assert len(payload["ranks"]) == 2
    assert [record["rank"] for record in payload["ranks"]] == [1, 2]


def test_search_rank_history_migrates_legacy_records_to_sortby(tmp_path):
    path = tmp_path / "ownerclan_2026_0822_0900_search-ranks.json"
    atomic_write_json(
        path,
        {
            "collectedAt": "2026-08-22T09:00:00+09:00",
            "ranks": [
                {
                    "collectedAt": "2026-08-22T09:00:00+09:00",
                    "keyword": "case",
                    "searchType": "default_top",
                    "sortBy": None,
                    "productId": "W1",
                    "productKey": "W1",
                    "rank": 1,
                }
            ],
        },
    )

    payload = append_search_ranks(path, [])

    assert payload["ranks"][0]["sortBy"] == "default"
    assert "searchType" not in payload["ranks"][0]


def test_raw_samples_are_capped_at_three_products(tmp_path):
    path = tmp_path / "raw.json"
    products = [{"productId": f"W{index}", "productKey": f"W{index}", "raw": {"key": f"W{index}"}} for index in range(5)]

    payload = save_raw_samples(path, "2026-08-22T09:00:00+09:00", products, 20)

    assert [item["productId"] for item in payload["items"]] == ["W0", "W1", "W2"]


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


def test_collect_details_writes_latest_history_and_failures(tmp_path):
    config = _config(tmp_path)
    atomic_write_json(config.output.tracked_products_path, {"W1": {"productId": "W1", "active": True}})
    client = FakeClient()

    result = collect_details(tmp_path, config, client=client)

    assert result["successCount"] == 2
    latest = load_json_object(config.output.state_dir / "latest-products.json")
    assert "rawSnapshots" not in latest["products"]["ownerclan:W1"]["current"]
    snapshot_files = list(config.output.output_dir.glob("ownerclan_*_product-snapshots.json"))
    assert snapshot_files
    snapshot = load_json_object(snapshot_files[0])
    assert "raw" not in snapshot["products"][0]
    raw_files = list((config.output.output_dir.parent / "raw").glob("ownerclan_*_raw.json"))
    assert raw_files
    raw_payload = load_json_object(raw_files[0])
    assert raw_payload["items"]
    history_files = list((config.output.output_dir.parent / "history").glob("ownerclan_*_product-history.json"))
    assert history_files


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


def test_migrate_sortby_schema_updates_stored_ownerclan_data(tmp_path):
    data_dir = tmp_path / "data"
    tracked_path = data_dir / "state" / "tracked_products.json"
    rank_path = data_dir / "processed" / "ownerclan_2026_0822_0900_search-ranks.json"
    atomic_write_json(
        tracked_path,
        {"W1": {"productId": "W1", "productKey": "W1", "keywords": ["case"], "searchTypes": ["default_top"], "reasons": []}},
    )
    atomic_write_json(
        rank_path,
        {
            "collectedAt": "2026-08-22T09:00:00+09:00",
            "ranks": [
                {
                    "collectedAt": "2026-08-22T09:00:00+09:00",
                    "keyword": "case",
                    "searchType": "default_top",
                    "sortBy": None,
                    "productId": "W1",
                    "productKey": "W1",
                    "rank": 1,
                }
            ],
        },
    )

    stats = migrate_sortby_schema(data_dir)

    assert stats == {"trackedFiles": 1, "rankFiles": 1}
    tracked = load_json_object(tracked_path)
    ranks = load_json_object(rank_path)["ranks"]
    assert "searchTypes" not in tracked["W1"]
    assert ranks[0]["sortBy"] == "default"
    assert "searchType" not in ranks[0]


def test_options_stock_status_normalization_and_source_specific_preserved():
    item = _item(
        "W9",
        options=[
            {"optionAttributes": [], "price": 1000, "quantity": 2},
            {"optionAttributes": [{"name": "색상", "value": "검정"}], "price": 1200, "quantity": "3"},
        ],
    )
    item["status"] = "unavailable"
    item["pricePolicy"] = "fixed"
    item["openmarketSellable"] = False
    item["metadata"] = {"vendorKey": "V1"}

    product = normalize_item(item, "2026-08-24T00:00:00+09:00")

    assert product["options"][0]["skuType"] == "default"
    assert product["options"][1]["optionAttributes"] == [{"name": "색상", "value": "검정"}]
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
                "상품 상세정보에 별도 표기",
                "상품 상세정보에 별도 표기",
                "판매자 연락처 참고",
            ],
            "common": [
                "상품 상세정보에 별도 표기",
                "상품 상세정보에 별도 표기",
                "상품 상세정보에 별도 표기",
                "상품 상세정보에 별도 표기",
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


def test_latest_products_do_not_store_raw_snapshots(tmp_path):
    latest_path = tmp_path / "latest.json"
    history_path = tmp_path / "history.json"
    for index in range(5):
        product = normalize_item(_item("W1", name=f"상품{index}"), f"2026-08-24T00:00:0{index}+09:00")
        update_latest_and_history(
            latest_path=latest_path,
            history_path=history_path,
            collected_at=product["collectedAt"],
            products=[product],
        )

    latest = load_json_object(latest_path)
    record = latest["products"]["ownerclan:W1"]
    assert "rawSnapshots" not in record["current"]
    assert "raw" not in record["current"]
    assert len(record["comparableFingerprint"]) == 64
    assert "content" not in record["comparableFingerprint"]


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
        "name": name or f"상품 {key}",
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

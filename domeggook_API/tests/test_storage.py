import json
import os
import time

import pytest

from domeggook_API.storage import (
    FileLock,
    append_search_ranks,
    active_product_ids,
    atomic_write_json,
    chunked,
    load_tracked_products,
    merge_discovered_product,
    merge_product_snapshots,
    save_raw_samples,
)


def test_discovered_product_ids_are_deduplicated(tmp_path):
    tracked = {}

    assert merge_discovered_product(tracked, "12345678", "안경 케이스", "dome", "popular", "2026-08-22T09:00:00+09:00")
    assert not merge_discovered_product(tracked, "12345678", "안경 케이스", "dome", "popular", "2026-08-22T10:00:00+09:00")

    assert list(tracked) == ["12345678"]
    assert tracked["12345678"]["productId"] == "12345678"
    assert tracked["12345678"]["keywords"] == ["안경 케이스"]


def test_existing_product_metadata_is_merged_without_duplicates():
    tracked = {
        "12345678": {
            "productId": "12345678",
            "keywords": ["안경 케이스"],
            "markets": ["dome"],
            "reasons": ["popular"],
            "firstSeenAt": "2026-08-21T09:00:00+09:00",
            "lastSeenAt": "2026-08-21T09:00:00+09:00",
            "active": True,
        }
    }

    created = merge_discovered_product(
        tracked,
        "12345678",
        "선글라스 케이스",
        "supply",
        "recent",
        "2026-08-22T09:00:00+09:00",
    )

    assert not created
    assert tracked["12345678"]["keywords"] == ["안경 케이스", "선글라스 케이스"]
    assert tracked["12345678"]["markets"] == ["dome", "supply"]
    assert tracked["12345678"]["reasons"] == ["popular", "recent"]
    assert tracked["12345678"]["firstSeenAt"] == "2026-08-21T09:00:00+09:00"
    assert tracked["12345678"]["lastSeenAt"] == "2026-08-22T09:00:00+09:00"


def test_active_product_ids_skip_inactive_and_sort_as_strings():
    tracked = {
        "2": {"active": True},
        "10": {"active": True},
        "1": {"active": False},
    }

    assert active_product_ids(tracked) == ["10", "2"]


def test_chunked_splits_detail_batches_by_100():
    product_ids = [str(value) for value in range(205)]

    chunks = chunked(product_ids, 100)

    assert [len(chunk) for chunk in chunks] == [100, 100, 5]
    assert chunks[0][0] == "0"
    assert chunks[-1][-1] == "204"


def test_atomic_write_json_replaces_valid_file(tmp_path):
    path = tmp_path / "tracked_products.json"

    atomic_write_json(path, {"1": {"productId": "1"}})
    atomic_write_json(path, {"2": {"productId": "2"}})

    assert load_tracked_products(path) == {"2": {"productId": "2"}}
    assert not list(tmp_path.glob("*.tmp"))


def test_product_snapshots_merge_by_product_id(tmp_path):
    path = tmp_path / "domeggook_2026_0822_0900_product-snapshots.json"

    merge_product_snapshots(path, "2026-08-22T09:00:00+09:00", [{"productId": "1", "price": "1000"}], [])
    payload = merge_product_snapshots(
        path,
        "2026-08-22T10:00:00+09:00",
        [{"productId": "1", "price": "900"}, {"productId": "2", "price": "2000"}],
        [{"productId": "3", "error": "not found"}],
    )

    assert payload["successCount"] == 2
    assert payload["failureCount"] == 1
    assert [product["productId"] for product in payload["products"]] == ["1", "2"]
    assert payload["products"][0]["price"] == "900"
    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_search_rank_history_keeps_same_product_at_different_ranks(tmp_path):
    path = tmp_path / "domeggook_2026_0822_0900_search-ranks.json"
    records = [
        {
            "collectedAt": "2026-08-22T09:00:00+09:00",
            "keyword": "안경 케이스",
            "market": "dome",
            "sort": "ha",
            "productId": "1",
            "rank": 1,
        },
        {
            "collectedAt": "2026-08-22T09:00:00+09:00",
            "keyword": "안경 케이스",
            "market": "dome",
            "sort": "ha",
            "productId": "1",
            "rank": 2,
        },
    ]

    payload = append_search_ranks(path, records + [records[0]])

    assert len(payload["ranks"]) == 2
    assert [record["rank"] for record in payload["ranks"]] == [1, 2]


def test_raw_samples_are_capped_at_three_products(tmp_path):
    path = tmp_path / "raw.json"
    products = [{"productId": str(index), "raw": {"no": str(index)}} for index in range(5)]

    payload = save_raw_samples(path, "2026-08-22T09:00:00+09:00", products, 20)

    assert [item["productId"] for item in payload["items"]] == ["0", "1", "2"]


def test_file_lock_rejects_recent_existing_lock(tmp_path):
    path = tmp_path / "collector.lock"
    path.write_text("12345", encoding="ascii")

    with pytest.raises(RuntimeError, match="another domeggook_API collection"):
        with FileLock(path, stale_after_seconds=60):
            pass

    assert path.exists()


def test_file_lock_removes_stale_existing_lock(tmp_path):
    path = tmp_path / "collector.lock"
    path.write_text("12345", encoding="ascii")
    old_time = time.time() - 120
    os.utime(path, (old_time, old_time))

    with FileLock(path, stale_after_seconds=60):
        assert path.exists()

    assert not path.exists()

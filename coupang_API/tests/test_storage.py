import json

from coupang_API.storage import JsonlWriter


def test_same_product_id_history_is_preserved_across_collection_times(tmp_path):
    path = tmp_path / "history.jsonl"
    first = {
        "api": {"productId": 1, "rank": 1, "productPrice": 1000},
        "collector": {"requestedKeyword": "a", "collectedAt": "2026-08-21T00:00:00Z"},
    }
    second = {
        "api": {"productId": 1, "rank": 2, "productPrice": 900},
        "collector": {"requestedKeyword": "a", "collectedAt": "2026-08-21T01:00:00Z"},
    }

    with JsonlWriter(path) as writer:
        assert writer.write_many_dedup([first, second]) == 2

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["api"]["productPrice"] for line in lines] == [1000, 900]


def test_exact_duplicates_are_removed_within_same_run(tmp_path):
    path = tmp_path / "dedup.jsonl"
    record = {
        "api": {"productId": 1, "rank": 1, "productPrice": 1000},
        "collector": {"requestedKeyword": "a", "collectedAt": "2026-08-21T00:00:00Z"},
    }

    with JsonlWriter(path) as writer:
        assert writer.write_many_dedup([record, dict(record)]) == 1

    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

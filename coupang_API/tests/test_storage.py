import json

from coupang_API.storage import JsonlWriter, prune_raw_samples, save_raw_response


def test_same_product_id_history_is_preserved_across_collection_times(tmp_path):
    path = tmp_path / "history.jsonl"
    first = {
        "productId": 1,
        "rank": 1,
        "productPrice": 1000,
        "keyword": "a",
        "collectedAt": "2026-08-21T00:00:00Z",
    }
    second = {
        "productId": 1,
        "rank": 2,
        "productPrice": 900,
        "keyword": "a",
        "collectedAt": "2026-08-21T01:00:00Z",
    }

    with JsonlWriter(path) as writer:
        assert writer.write_many_dedup([first, second]) == 2

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["productPrice"] for line in lines] == [1000, 900]


def test_exact_duplicates_are_removed_within_same_run(tmp_path):
    path = tmp_path / "dedup.jsonl"
    record = {
        "productId": 1,
        "rank": 1,
        "productPrice": 1000,
        "keyword": "a",
        "collectedAt": "2026-08-21T00:00:00Z",
    }

    with JsonlWriter(path) as writer:
        assert writer.write_many_dedup([record, dict(record)]) == 1

    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_prune_raw_samples_keeps_limited_files_per_run(tmp_path):
    raw_dir = tmp_path / "raw"
    save_raw_response(raw_dir, "run1", "a", {"keyword": "a"})
    save_raw_response(raw_dir, "run1", "b", {"keyword": "b"})
    save_raw_response(raw_dir, "run1", "c", {"keyword": "c"})
    save_raw_response(raw_dir, "run2", "a", {"keyword": "a"})
    save_raw_response(raw_dir, "run2", "b", {"keyword": "b"})

    assert prune_raw_samples(raw_dir, 2) == 1

    names = sorted(path.name for path in raw_dir.glob("*_raw*.json"))
    assert len([name for name in names if name.startswith("run1_raw_")]) == 2
    assert len([name for name in names if name.startswith("run2_raw_")]) == 2

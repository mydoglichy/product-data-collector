from collection_state import item_list_hash, resume_index


def test_resume_index_uses_next_index_when_list_hash_matches() -> None:
    items = ["A", "B", "C"]
    state = {"trackedListHash": item_list_hash(items), "nextIndex": 2, "lastCompletedProductId": "A"}

    assert resume_index(items, state, item_list_hash(items)) == 2


def test_resume_index_falls_back_to_last_completed_when_list_changes() -> None:
    items = ["A", "B", "C"]
    old_hash = item_list_hash(["A", "C"])
    state = {"trackedListHash": old_hash, "nextIndex": 99, "lastCompletedProductId": "B"}

    assert resume_index(items, state, item_list_hash(items)) == 2


def test_resume_index_starts_at_zero_when_state_is_not_usable() -> None:
    items = ["A", "B", "C"]

    assert resume_index(items, {"nextIndex": "bad"}, item_list_hash(items)) == 0
    assert resume_index(items, {"lastCompletedProductId": "missing"}, item_list_hash(items)) == 0

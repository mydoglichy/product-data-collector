from coupang_API.persistence.storage import dedupe_records


def test_dedupe_records_keeps_first_occurrence() -> None:
    records = [
        {"productId": 1, "price": 1000},
        {"price": 1000, "productId": 1},
        {"productId": 2, "price": 900},
    ]

    assert dedupe_records(records) == [
        {"productId": 1, "price": 1000},
        {"productId": 2, "price": 900},
    ]

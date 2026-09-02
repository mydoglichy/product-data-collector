from __future__ import annotations

from pathlib import Path

import pytest

from postgres_storage import (
    _has_inventory_snapshot,
    _has_shipping_snapshot,
    _search_rank_rows,
    _snapshot_row,
    load_postgres_config,
    save_product_snapshots_if_enabled,
)


def test_load_postgres_config_reads_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            (
                "POSTGRES_HOST=localhost",
                "POSTGRES_PORT=5433",
                "POSTGRES_DB=collector_test",
                "POSTGRES_USER=collector",
                "POSTGRES_PASSWORD=secret",
            )
        ),
        encoding="utf-8",
    )
    for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        monkeypatch.delenv(key, raising=False)

    config = load_postgres_config(tmp_path)

    assert config.host == "localhost"
    assert config.port == 5433
    assert config.database == "collector_test"
    assert config.user == "collector"
    assert config.password == "secret"


def test_snapshot_row_normalizes_product_for_postgres() -> None:
    row = _snapshot_row(
        "coupang",
        "2026-08-30T10:00:00Z",
        {
            "productId": "123",
            "productName": "Sample",
            "imageUrl": "https://img.example/a.jpg?size=100",
            "backupImageUrl": "https://img.example/b.jpg?size=100",
            "productPrice": 12000,
            "raw": {"ignored": True},
        },
    )

    assert row is not None
    assert row["platform"] == "coupang"
    assert row["external_product_id"] == "123"
    assert row["image_url"] == "https://img.example/a.jpg"
    assert row["backup_image_url"] == "https://img.example/b.jpg"
    assert row["current_payload"]["imageUrl"] == "https://img.example/a.jpg"
    assert row["current_payload"]["backupImageUrl"] == "https://img.example/b.jpg"
    assert "images" not in row["current_payload"]
    assert "raw" not in row["current_payload"]
    assert row["primary_price"] == 12000


def test_snapshot_row_preserves_falsy_inventory_and_shipping_values() -> None:
    row = _snapshot_row(
        "ownerclan",
        "2026-08-30T10:00:00Z",
        {
            "productId": "zero-stock",
            "productPrice": "12345",
            "inventory": {"stockQuantity": 0},
            "shipping": {"isFreeShipping": False},
        },
    )

    assert row is not None
    assert row["stock_quantity"] == 0
    assert row["is_free_shipping"] is False


def test_empty_inventory_snapshot_is_skipped_for_coupang_search_records() -> None:
    row = _snapshot_row(
        "coupang",
        "2026-08-30T10:00:00Z",
        {
            "productId": "123",
            "productName": "Sample",
            "productPrice": 12000,
        },
    )

    assert row is not None
    assert row["stock_quantity"] is None
    assert not _has_inventory_snapshot(row)


def test_inventory_snapshot_keeps_zero_and_source_inventory_values() -> None:
    zero_row = _snapshot_row(
        "ownerclan",
        "2026-08-30T10:00:00Z",
        {
            "productId": "zero-stock",
            "inventory": {"stockQuantity": 0},
        },
    )
    api_quantity_row = _snapshot_row(
        "ownerclan",
        "2026-08-30T10:00:00Z",
        {
            "productId": "api-stock",
            "inventory": {
                "stockQuantity": None,
                "stockQuantitySource": "sum(options[].quantity)",
                "apiStockQuantity": 10,
            },
        },
    )

    assert zero_row is not None
    assert api_quantity_row is not None
    assert _has_inventory_snapshot(zero_row)
    assert _has_inventory_snapshot(api_quantity_row)


def test_empty_ownerclan_inventory_snapshot_is_skipped_when_only_source_label_exists() -> None:
    row = _snapshot_row(
        "ownerclan",
        "2026-08-30T10:00:00Z",
        {
            "productId": "missing-stock",
            "inventory": {
                "stockQuantity": None,
                "stockQuantitySource": "sum(options[].quantity)",
                "apiStockQuantity": None,
            },
        },
    )

    assert row is not None
    assert not _has_inventory_snapshot(row)


def test_empty_domeggook_inventory_snapshot_is_skipped() -> None:
    row = _snapshot_row(
        "domeggook",
        "2026-08-30T10:00:00Z",
        {
            "productId": "missing-stock",
            "inventory": {
                "stockQuantity": None,
                "domeMoq": None,
                "domeMaxOrderQuantity": None,
                "domeOrderUnit": None,
                "supplyOrderUnit": None,
            },
        },
    )

    assert row is not None
    assert not _has_inventory_snapshot(row)


def test_shipping_snapshot_keeps_coupang_free_shipping_flag() -> None:
    row = _snapshot_row(
        "coupang",
        "2026-08-30T10:00:00Z",
        {
            "productId": "123",
            "productPrice": 12000,
            "isFreeShipping": False,
        },
    )

    assert row is not None
    assert row["is_free_shipping"] is False
    assert _has_shipping_snapshot(row["shipping_rows"][0], row)


def test_empty_shipping_snapshot_is_skipped_when_source_has_no_values() -> None:
    row = _snapshot_row(
        "ownerclan",
        "2026-08-30T10:00:00Z",
        {
            "productId": "missing-shipping",
            "shipping": {
                "fee": None,
                "feeRaw": None,
                "type": None,
                "typeRaw": None,
                "isFreeShipping": None,
                "sourceFields": {"shippingFee": None, "shippingType": None},
            },
        },
    )

    assert row is not None
    assert not _has_shipping_snapshot(row["shipping_rows"][0], row)


def test_snapshot_row_splits_domeggook_market_prices_and_shipping() -> None:
    row = _snapshot_row(
        "domeggook",
        "2026-08-30T10:00:00Z",
        {
            "productId": "11291544",
            "prices": {
                "domeCurrentSupplyPrice": "10+650|100+620",
                "supplyCurrentSupplyPrice": 680,
                "minimumRetailPrice": 900,
                "recommendedRetailPrice": 1000,
            },
            "shipping": {
                "feePayer": "P",
                "domeFeePayer": "P",
                "domeFee": "100+3000|100+3000",
                "domeFeeType": "수량별비례",
                "domeFeeTable": "100+3000|100+3000",
                "supplyFeePayer": "B",
                "supplyFee": 3000,
                "supplyFeeType": "고정배송비",
                "feeExtraJeju": 3000,
                "feeExtraIslands": 5000,
            },
        },
    )

    assert row is not None
    assert row["primary_price"] is None
    assert row["prices_payload"]["domeCurrentSupplyPrice"] == "10+650|100+620"
    assert row["price_rows"] == [
        {"market": "dome", "price_type": "current_supply", "amount": None},
        {"market": "supply", "price_type": "current_supply", "amount": 680},
        {"market": "retail", "price_type": "minimum_retail", "amount": 900},
        {"market": "retail", "price_type": "recommended_retail", "amount": 1000},
    ]
    assert row["shipping_fee"] is None
    assert row["shipping_rows"][0]["market"] == "dome"
    assert row["shipping_rows"][0]["fee"] is None
    assert row["shipping_rows"][0]["shipping_type"] == "quantity_proportional"
    assert row["shipping_rows"][0]["shipping_fee_raw"] == "100+3000|100+3000"
    assert row["shipping_rows"][0]["shipping_fee_type_raw"] == "수량별비례"
    assert row["shipping_rows"][0]["additional_fee"] == 3000
    assert row["shipping_rows"][0]["requires_quantity_calculation"] is True
    assert row["shipping_rows"][0]["shipping_payment"] == "prepaid"
    assert row["shipping_rows"][0]["payload"]["domeFee"] == "100+3000|100+3000"
    assert row["shipping_rows"][0]["payload"]["shipping_fee"] is None
    assert row["shipping_rows"][0]["payload"]["remote_area_fee"] == {"jeju": 3000, "islands": 5000}
    assert row["shipping_rows"][0]["payload"]["source_fields"] == {
        "fee": "100+3000|100+3000",
        "type": "수량별비례",
        "tbl": "100+3000|100+3000",
        "pay": "P",
    }
    assert row["shipping_rows"][1]["market"] == "supply"
    assert row["shipping_rows"][1]["fee"] == 3000
    assert row["shipping_rows"][1]["shipping_type"] == "fixed"
    assert row["shipping_rows"][1]["shipping_payment"] == "collect"
    assert row["shipping_rows"][1]["shipping_fee_raw"] == 3000
    assert row["shipping_rows"][1]["shipping_fee_type_raw"] == "고정배송비"


def test_snapshot_row_keeps_zero_shipping_distinct_from_missing_fee() -> None:
    free_row = _snapshot_row(
        "ownerclan",
        "2026-08-30T10:00:00Z",
        {
            "productId": "free",
            "prices": {"currentSupplyPrice": 1000},
            "shipping": {"fee": 0, "type": "free"},
        },
    )
    missing_row = _snapshot_row(
        "ownerclan",
        "2026-08-30T10:00:00Z",
        {
            "productId": "missing",
            "prices": {"currentSupplyPrice": 1000},
            "shipping": {"fee": None, "type": "unknown"},
        },
    )

    assert free_row is not None
    assert missing_row is not None
    assert free_row["shipping_rows"][0]["fee"] == 0
    assert missing_row["shipping_rows"][0]["fee"] is None


def test_snapshot_row_casts_won_text_prices_for_storage() -> None:
    row = _snapshot_row(
        "ownerclan",
        "2026-08-30T10:00:00Z",
        {
            "productId": "won-price",
            "prices": {"currentSupplyPrice": " 12,300원 "},
            "inventory": {"stockQuantity": " 4 "},
            "shipping": {"fee": "3,000원", "type": "고정배송비"},
        },
    )

    assert row is not None
    assert row["primary_price"] == 12300
    assert row["price_rows"][0]["amount"] == 12300
    assert row["stock_quantity"] == 4
    assert row["shipping_rows"][0]["fee"] == 3000


def test_snapshot_row_parses_shipping_payment_separately_from_fee() -> None:
    row = _snapshot_row(
        "domeggook",
        "2026-08-30T10:00:00Z",
        {
            "productId": "collect",
            "shipping": {
                "feePayer": "B",
                "domeFee": "1+3500|20+5500",
                "domeFeeType": "수량별차등",
            },
        },
    )

    assert row is not None
    shipping = row["shipping_rows"][0]
    assert shipping["fee"] is None
    assert shipping["shipping_type"] == "quantity_tiered"
    assert shipping["shipping_payment"] == "collect"
    assert shipping["payload"]["shipping_payment"] == "collect"
    assert shipping["payload"]["shipping_fee_raw"] == "1+3500|20+5500"
    assert shipping["shipping_rules"] == [
        {"min_quantity": 1, "fee": 3500},
        {"min_quantity": 20, "fee": 5500},
    ]


def test_snapshot_row_preserves_ownerclan_shipping_without_domeggook_fallback() -> None:
    row = _snapshot_row(
        "ownerclan",
        "2026-08-30T10:00:00Z",
        {
            "productId": "owner-shipping",
            "prices": {"currentSupplyPrice": 1000},
            "shipping": {
                "fee": 3000,
                "feeRaw": "3,000",
                "type": "inAdvance",
                "typeRaw": "inAdvance",
                "isFreeShipping": False,
                "sourceFields": {"shippingFee": "3,000", "shippingType": "inAdvance"},
            },
        },
    )

    assert row is not None
    assert row["is_free_shipping"] is False
    assert row["shipping_rows"] == [
        {
            "market": "ownerclan",
            "fee": 3000,
            "shipping_type": "unknown",
            "shipping_payment": "prepaid",
            "shipping_fee": 3000,
            "shipping_fee_raw": "3,000",
            "shipping_fee_type_raw": "inAdvance",
            "requires_quantity_calculation": False,
            "payload": row["shipping_rows"][0]["payload"],
        }
    ]
    assert row["shipping_rows"][0]["payload"]["source_fields"] == {"shippingFee": "3,000", "shippingType": "inAdvance"}


def test_snapshot_row_does_not_create_supply_shipping_from_dome_fallback() -> None:
    row = _snapshot_row(
        "domeggook",
        "2026-08-30T10:00:00Z",
        {
            "productId": "dome-only",
            "shipping": {
                "feePayer": "P",
                "domeFee": 3000,
                "domeFeeType": "고정배송비",
            },
        },
    )

    assert row is not None
    assert [shipping["market"] for shipping in row["shipping_rows"]] == ["dome"]
    assert row["shipping_rows"][0]["payload"]["source_fields"]["pay"] == "P"


def test_save_product_snapshots_if_enabled_skips_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_ENABLED", "false")

    saved_count = save_product_snapshots_if_enabled(
        project_root=tmp_path,
        platform="ownerclan",
        collected_at="2026-08-30T10:00:00Z",
        products=[{"productId": "123"}],
    )

    assert saved_count == 0


def test_search_rank_rows_keep_only_domeggook_ranked_sorts_and_positive_ranks() -> None:
    rows = _search_rank_rows(
        "domeggook",
        [
            {"collectedAt": "2026-08-30T10:00:00Z", "productId": "ha-1", "sort": "ha", "rank": 1},
            {"collectedAt": "2026-08-30T10:00:00Z", "productId": "rd-1", "sort": "rd", "rank": 2},
            {"collectedAt": "2026-08-30T10:00:00Z", "productId": "da-1", "sort": "da", "rank": 3},
            {"collectedAt": "2026-08-30T10:00:00Z", "productId": "aa-1", "sort": "aa", "rank": 4},
            {"collectedAt": "2026-08-30T10:00:00Z", "productId": "missing-rank", "sort": "ha"},
            {"collectedAt": "2026-08-30T10:00:00Z", "productId": "zero-rank", "sort": "ha", "rank": 0},
        ],
    )

    assert [(row["external_product_id"], row["sort"], row["rank"]) for row in rows] == [
        ("ha-1", "ha", 1),
        ("rd-1", "rd", 2),
    ]


def test_search_rank_rows_preserve_same_product_for_different_keywords() -> None:
    rows = _search_rank_rows(
        "domeggook",
        [
            {
                "collectedAt": "2026-08-30T10:00:00Z",
                "productId": "100",
                "keyword": "bag",
                "categoryCode": "01_01_00_00_00",
                "market": "dome",
                "sort": "ha",
                "rank": 1,
            },
            {
                "collectedAt": "2026-08-30T10:00:00Z",
                "productId": "100",
                "keyword": "case",
                "categoryCode": "02_01_00_00_00",
                "market": "dome",
                "sort": "ha",
                "rank": 1,
            },
        ],
    )

    assert len(rows) == 2
    assert {row["keyword"] for row in rows} == {"bag", "case"}

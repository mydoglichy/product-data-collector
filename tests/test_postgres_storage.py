from __future__ import annotations

from pathlib import Path

import pytest

from postgres_storage import _snapshot_row, load_postgres_config, save_product_snapshots_if_enabled


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
            "productPrice": 12000,
            "raw": {"ignored": True},
        },
    )

    assert row is not None
    assert row["platform"] == "coupang"
    assert row["external_product_id"] == "123"
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
                "domeFee": "100+3000|100+3000",
                "domeFeeType": "수량별비례",
                "supplyFee": 3000,
                "supplyFeeType": "고정배송비",
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
    assert row["shipping_rows"] == [
        {"market": "dome", "fee": None, "shipping_type": "수량별비례"},
        {"market": "supply", "fee": 3000, "shipping_type": "고정배송비"},
    ]


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


def test_save_product_snapshots_if_enabled_skips_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_ENABLED", "false")

    saved_count = save_product_snapshots_if_enabled(
        project_root=tmp_path,
        platform="ownerclan",
        collected_at="2026-08-30T10:00:00Z",
        products=[{"productId": "123"}],
    )

    assert saved_count == 0

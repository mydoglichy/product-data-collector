from __future__ import annotations

import pytest

from shipping_fees import parse_shipping_fee, parse_shipping_payment


@pytest.mark.parametrize(
    ("quantity", "expected"),
    (
        (1, 3000),
        (100, 3000),
    ),
)
def test_fixed_shipping_fee(quantity: int, expected: int) -> None:
    parsed = parse_shipping_fee(3000, "고정배송비", quantity=quantity)

    assert parsed["shipping_type"] == "fixed"
    assert parsed["shipping_fee"] == expected
    assert parsed["shipping_fee_raw"] == 3000
    assert parsed["shipping_fee_type_raw"] == "고정배송비"


@pytest.mark.parametrize(
    ("fee", "quantity"),
    (
        ("100+3000|100+3000", 1),
        ("100+3000|100+3000", 100),
        ("100+3000|100+3000", 101),
        ("100+3000|100+3000", 250),
        ("30+2900|30+3000", 30),
        ("30+2900|30+3000", 31),
        ("30+2900|30+3000", 61),
    ),
)
def test_quantity_proportional_shipping_fee_is_not_calculated(fee: str, quantity: int) -> None:
    parsed = parse_shipping_fee(fee, "수량별비례", quantity=quantity)

    assert parsed["shipping_type"] == "quantity_proportional"
    assert parsed["shipping_fee"] is None
    assert parsed["requires_quantity_calculation"] is True


def test_quantity_proportional_keeps_duplicate_second_rule() -> None:
    parsed = parse_shipping_fee("100+3000|100+3000", "수량별비례", quantity=101)

    assert parsed["shipping_fee"] is None
    assert parsed["quantity_unit"] == 100
    assert parsed["first_fee"] == 3000
    assert parsed["additional_quantity_unit"] == 100
    assert parsed["additional_fee"] == 3000
    assert parsed["shipping_rules"] == [
        {"quantity": 100, "fee": 3000},
        {"quantity": 100, "fee": 3000},
    ]


@pytest.mark.parametrize(
    "quantity",
    (
        1,
        19,
        20,
        100,
    ),
)
def test_quantity_tiered_shipping_fee_is_not_calculated(quantity: int) -> None:
    parsed = parse_shipping_fee("1+3500|20+5500", "수량별차등", quantity=quantity)

    assert parsed["shipping_type"] == "quantity_tiered"
    assert parsed["shipping_fee"] is None
    assert parsed["requires_quantity_calculation"] is True
    assert parsed["shipping_rules"] == [
        {"min_quantity": 1, "fee": 3500},
        {"min_quantity": 20, "fee": 5500},
    ]


@pytest.mark.parametrize("fee_type", ("무료배송", "free"))
def test_free_shipping_is_always_zero(fee_type: str) -> None:
    for quantity in (1, 100):
        parsed = parse_shipping_fee(None, fee_type, quantity=quantity)
        assert parsed["shipping_type"] == "free"
        assert parsed["shipping_payment"] == "free"
        assert parsed["shipping_fee"] == 0


def test_free_shipping_payer_overrides_fee_amount() -> None:
    parsed = parse_shipping_fee(3000, "고정배송비", fee_payer="S", quantity=100)

    assert parsed["shipping_type"] == "free"
    assert parsed["shipping_payment"] == "free"
    assert parsed["shipping_fee"] == 0


@pytest.mark.parametrize("fee", (None, "", "not-a-rule"))
def test_unknown_shipping_fee(fee: object) -> None:
    parsed = parse_shipping_fee(fee, "수량별비례")

    assert parsed["shipping_type"] == "quantity_proportional"
    assert parsed["shipping_payment"] == "unknown"
    assert parsed["shipping_fee"] is None
    assert parsed["requires_quantity_calculation"] is True


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("S", "free"),
        ("무료배송", "free"),
        ("P", "prepaid"),
        ("선결제", "prepaid"),
        ("B", "collect"),
        ("착불", "collect"),
        ("C", "buyer_choice"),
        ("구매자 선택", "buyer_choice"),
    ),
)
def test_shipping_payment(value: str, expected: str) -> None:
    assert parse_shipping_payment(value) == expected


def test_ownerclan_in_advance_shipping_type_is_payment_metadata() -> None:
    parsed = parse_shipping_fee("3,000", "inAdvance", fee_payer="inAdvance")

    assert parsed["shipping_type"] == "unknown"
    assert parsed["shipping_payment"] == "prepaid"
    assert parsed["shipping_fee"] == 3000


def test_fixed_shipping_fee_accepts_won_text() -> None:
    parsed = parse_shipping_fee(" 3,000원 ", "고정배송비")

    assert parsed["shipping_type"] == "fixed"
    assert parsed["shipping_fee"] == 3000


def test_unknown_pair_fee_preserves_rules_without_calculation() -> None:
    parsed = parse_shipping_fee("1+3500|20+5500")

    assert parsed["shipping_type"] == "unknown"
    assert parsed["shipping_fee"] is None
    assert parsed["requires_quantity_calculation"] is True
    assert parsed["shipping_rules"] == [
        {"quantity": 1, "fee": 3500},
        {"quantity": 20, "fee": 5500},
    ]

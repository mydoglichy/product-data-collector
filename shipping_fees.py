from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from numeric_utils import parse_decimal


_PAIR_RE = re.compile(r"^\s*([0-9][0-9,]*)\s*\+\s*([0-9][0-9,]*)\s*$")


def parse_shipping_fee(
    fee: Any,
    fee_type: Any = None,
    *,
    fee_payer: Any = None,
    quantity: int = 1,
) -> dict[str, Any]:
    _ = quantity
    fee_raw = fee
    fee_type_raw = fee_type
    payment = parse_shipping_payment(fee_payer)
    result: dict[str, Any] = {
        "shipping_type": "unknown",
        "shipping_payment": payment,
        "shipping_fee": None,
        "shipping_fee_raw": fee_raw,
        "shipping_fee_type_raw": fee_type_raw,
        "requires_quantity_calculation": False,
    }

    if payment == "free" or _is_free_type(fee_type) or _is_free_fee(fee):
        result["shipping_type"] = "free"
        result["shipping_payment"] = "free"
        result["shipping_fee"] = Decimal("0")
        return result

    normalized_type = _normalize_shipping_type(fee_type)
    if normalized_type == "fixed":
        fixed_fee = _decimal_or_none(fee)
        if fixed_fee is None:
            return result
        result["shipping_type"] = "fixed"
        result["shipping_fee"] = fixed_fee
        return result

    pairs = _parse_pairs(fee)
    if normalized_type == "quantity_proportional":
        if len(pairs) < 2:
            result["shipping_type"] = "quantity_proportional"
            result["requires_quantity_calculation"] = True
            return result
        first_quantity, first_fee = pairs[0]
        additional_quantity, additional_fee = pairs[1]
        if first_quantity <= 0 or additional_quantity <= 0:
            result["shipping_type"] = "quantity_proportional"
            result["requires_quantity_calculation"] = True
            return result
        result.update(
            {
                "shipping_type": "quantity_proportional",
                "shipping_fee": None,
                "requires_quantity_calculation": True,
                "quantity_unit": first_quantity,
                "first_fee": first_fee,
                "additional_quantity_unit": additional_quantity,
                "additional_fee": additional_fee,
                "shipping_rules": [
                    {"quantity": first_quantity, "fee": first_fee},
                    {"quantity": additional_quantity, "fee": additional_fee},
                ],
            }
        )
        return result

    if normalized_type == "quantity_tiered":
        if not pairs:
            result["shipping_type"] = "quantity_tiered"
            result["requires_quantity_calculation"] = True
            return result
        rules = sorted(({"min_quantity": min_quantity, "fee": rule_fee} for min_quantity, rule_fee in pairs), key=lambda item: item["min_quantity"])
        result.update(
            {
                "shipping_type": "quantity_tiered",
                "shipping_fee": None,
                "requires_quantity_calculation": True,
                "shipping_rules": rules,
            }
        )
        return result

    if pairs:
        result.update(
            {
                "shipping_fee": None,
                "requires_quantity_calculation": True,
                "shipping_rules": [{"quantity": quantity, "fee": rule_fee} for quantity, rule_fee in pairs],
            }
        )
        return result

    numeric_fee = _decimal_or_none(fee)
    if numeric_fee is not None:
        result["shipping_type"] = "fixed" if fee_type in (None, "") else "unknown"
        result["shipping_fee"] = numeric_fee
    return result


def parse_shipping_payment(value: Any) -> str:
    if value in (None, ""):
        return "unknown"
    text = str(value).strip()
    lowered = text.lower()
    upper = text.upper()
    if upper == "S" or text == "무료배송":
        return "free"
    if lowered in {"free", "free_shipping", "freeshipping"}:
        return "free"
    if upper == "P" or text == "선결제":
        return "prepaid"
    if lowered in {"inadvance", "prepaid", "advance", "paid"}:
        return "prepaid"
    if upper == "B" or text == "착불":
        return "collect"
    if lowered in {"collect", "cash_on_delivery", "cod", "ondelivery"}:
        return "collect"
    if upper == "C" or text == "구매자 선택":
        return "buyer_choice"
    if lowered in {"buyer_choice", "buyerchoice"}:
        return "buyer_choice"
    return "unknown"


def _normalize_shipping_type(value: Any) -> str:
    if value in (None, ""):
        return "unknown"
    text = str(value).strip().lower()
    if text in {"고정배송비", "fixed", "fixed_shipping", "fixedshipping"}:
        return "fixed"
    if text in {"수량별비례", "quantity_proportional", "proportional", "quantity"}:
        return "quantity_proportional"
    if text in {"수량별차등", "quantity_tiered", "tiered", "quantity_tier"}:
        return "quantity_tiered"
    if text in {"무료배송", "free", "free_shipping", "freeshipping"}:
        return "free"
    return "unknown"


def _is_free_type(value: Any) -> bool:
    return _normalize_shipping_type(value) == "free"


def _is_free_fee(value: Any) -> bool:
    if isinstance(value, str) and value.strip() == "무료배송":
        return True
    numeric = _decimal_or_none(value)
    return numeric == Decimal("0")


def _parse_pairs(value: Any) -> list[tuple[int, Decimal]]:
    if not isinstance(value, str):
        return []
    pairs: list[tuple[int, Decimal]] = []
    for part in value.split("|"):
        match = _PAIR_RE.fullmatch(part)
        if not match:
            return []
        quantity = int(match.group(1).replace(",", ""))
        fee = Decimal(match.group(2).replace(",", ""))
        pairs.append((quantity, fee))
    return pairs


def _decimal_or_none(value: Any) -> Decimal | None:
    return parse_decimal(value)

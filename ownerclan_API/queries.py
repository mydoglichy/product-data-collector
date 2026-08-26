from __future__ import annotations

import json
from typing import Any


ITEM_FIELDS = """
createdAt
updatedAt
key
id
name
model
production
origin
price
pricePolicy
fixedPrice
category {
  key
  name
  fullName
}
shippingFee
shippingType
status
options {
  optionAttributes {
    name
    value
  }
  price
  quantity
  key
}
taxFree
adultOnly
returnable
guaranteedShippingPeriod
openmarketSellable
boxQuantity
attributes
closingTime
"""

MINIMAL_ITEM_FIELDS = """
createdAt
updatedAt
key
id
name
model
production
origin
price
category {
  key
  name
  fullName
}
shippingFee
shippingType
status
options {
  optionAttributes {
    name
    value
  }
  price
  quantity
  key
}
taxFree
adultOnly
openmarketSellable
"""


def item_query(key: str, *, minimal: bool = False) -> str:
    return f"query {{ item(key: {json.dumps(key, ensure_ascii=False)}) {{ {_fields(minimal)} }} }}"


def items_query(keys: list[str], field_name: str = "items", *, minimal: bool = False) -> str:
    keys_json = json.dumps(keys, ensure_ascii=False)
    return f"query {{ {field_name}(keys: {keys_json}) {{ {_fields(minimal)} }} }}"


def all_items_query(
    *,
    first: int,
    search: str | None = None,
    sort_by: str | None = None,
    after: str | None = None,
    date_from: int | None = None,
    date_to: int | None = None,
    minimal: bool = False,
) -> str:
    args: dict[str, Any] = {"first": first}
    if search:
        args["search"] = search
    if sort_by:
        args["sortBy"] = _enum(sort_by)
    if after:
        args["after"] = after
    if date_from is not None:
        args["dateFrom"] = date_from
    if date_to is not None:
        args["dateTo"] = date_to
    return f"query {{ allItems({_format_args(args)}) {{ pageInfo {{ hasNextPage startCursor endCursor }} edges {{ cursor node {{ {_fields(minimal)} }} }} }} }}"


def item_histories_query(*, first: int, after: str | None = None, date_from: int | None = None, date_to: int | None = None) -> str:
    args: dict[str, Any] = {"first": first}
    if after:
        args["after"] = after
    if date_from is not None:
        args["dateFrom"] = date_from
    if date_to is not None:
        args["dateTo"] = date_to
    return (
        "query { itemHistories("
        + _format_args(args)
        + ") { pageInfo { hasNextPage startCursor endCursor } edges { cursor node { itemKey kind title valueBefore valueAfter createdAt } } } }"
    )


def _enum(value: str) -> tuple[str, str]:
    return ("enum", value)


def _format_args(args: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in args.items():
        if isinstance(value, tuple) and value[0] == "enum":
            rendered = value[1]
        else:
            rendered = json.dumps(value, ensure_ascii=False)
        parts.append(f"{key}: {rendered}")
    return ", ".join(parts)


def _fields(minimal: bool) -> str:
    return MINIMAL_ITEM_FIELDS if minimal else ITEM_FIELDS

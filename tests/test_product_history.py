from __future__ import annotations

from product_history import (
    changed_leaf_paths,
    comparable_state,
    external_product_id,
    fingerprint_state,
    flatten_paths,
    normalize_current_product,
)


def test_external_product_id_uses_known_source_keys() -> None:
    assert external_product_id({"productId": "P1"}) == "P1"
    assert external_product_id({"productKey": "K1"}) == "K1"
    assert external_product_id({"externalProductId": "E1"}) == "E1"
    assert external_product_id({}) is None


def test_normalize_current_product_removes_raw_and_tracking_queries() -> None:
    current = normalize_current_product(
        {
            "productId": "P1",
            "raw": {"ignored": True},
            "productUrl": "https://SHOP.example/p?item=1&utm_campaign=x&gclid=y",
            "imageUrl": "https://CDN.example/a.jpg?v=1",
        }
    )

    assert "raw" not in current
    assert current["productUrl"] == "https://shop.example/p?item=1"
    assert current["imageUrl"] == "https://cdn.example/a.jpg"


def test_comparable_state_ignores_volatile_display_fields() -> None:
    first = comparable_state(_product(name="old", url="https://example.com/p?utm_source=a"))
    second = comparable_state(_product(name="new", url="https://example.com/p?utm_source=b"))

    assert first == second
    assert fingerprint_state(first) == fingerprint_state(second)


def test_option_order_and_numeric_strings_are_canonicalized() -> None:
    first = comparable_state(_product(options=[_option("B", 200, 2), _option("A", 100, 1)]))
    second = comparable_state(_product(options=[_option("A", "100", "1"), _option("B", "200", "2")]))

    assert first == second


def test_missing_null_zero_and_status_are_distinct() -> None:
    missing = comparable_state(_product_without_inventory(status="available"))
    null = comparable_state(_product(stock=None, status="available"))
    zero = comparable_state(_product(stock=0, status="available"))
    soldout = comparable_state(_product(stock=0, status="soldout"))

    assert changed_leaf_paths(missing, null) == ["inventory.stockQuantity"]
    assert changed_leaf_paths(null, zero) == ["inventory.stockQuantity"]
    assert changed_leaf_paths(zero, soldout) == ["status"]


def test_flatten_paths_lists_leaf_paths() -> None:
    state = comparable_state(_product(price=1000, stock=7, shipping_fee=3000))

    assert "prices.currentSupplyPrice" in flatten_paths(state)
    assert "inventory.stockQuantity" in flatten_paths(state)
    assert "shipping.fee" in flatten_paths(state)


def _product(
    *,
    product_id="P1",
    price=1000,
    stock=7,
    shipping_fee=3000,
    status="available",
    name="name",
    url="https://example.com/p",
    image="https://cdn/a.jpg",
    options=None,
):
    return {
        "productId": product_id,
        "productName": name,
        "productUrl": url,
        "imageUrl": image,
        "prices": {"currentSupplyPrice": price},
        "inventory": {"stockQuantity": stock},
        "shipping": {"fee": shipping_fee},
        "options": options if options is not None else [_option("A", 100, 1)],
        "status": status,
    }


def _product_without_inventory(**kwargs):
    product = _product(**kwargs)
    product.pop("inventory")
    return product


def _option(key, price, quantity):
    return {"skuKey": key, "price": price, "quantity": quantity}

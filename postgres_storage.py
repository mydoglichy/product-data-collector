from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

import psycopg
from dotenv import load_dotenv
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from product_history import comparable_state, external_product_id, fingerprint_state, normalize_current_product


TRUE_VALUES = {"1", "true", "yes", "y", "on"}
DEFAULT_EMBEDDING_DIMENSIONS = 1536


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password: str


def load_postgres_config(project_root: Path | None = None) -> PostgresConfig:
    if project_root is not None:
        load_dotenv(project_root / ".env", override=False)
    else:
        load_dotenv(override=False)

    values = {
        "POSTGRES_HOST": os.getenv("POSTGRES_HOST"),
        "POSTGRES_PORT": os.getenv("POSTGRES_PORT"),
        "POSTGRES_DB": os.getenv("POSTGRES_DB"),
        "POSTGRES_USER": os.getenv("POSTGRES_USER"),
        "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD"),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"missing required PostgreSQL environment variables: {', '.join(missing)}")

    return PostgresConfig(
        host=str(values["POSTGRES_HOST"]),
        port=int(str(values["POSTGRES_PORT"])),
        database=str(values["POSTGRES_DB"]),
        user=str(values["POSTGRES_USER"]),
        password=str(values["POSTGRES_PASSWORD"]),
    )


def postgres_enabled(project_root: Path | None = None) -> bool:
    if project_root is not None:
        load_dotenv(project_root / ".env", override=False)
    else:
        load_dotenv(override=False)
    return str(os.getenv("POSTGRES_ENABLED", "")).strip().lower() in TRUE_VALUES


@contextmanager
def connect(config: PostgresConfig) -> Iterator[Connection[Any]]:
    connection = psycopg.connect(
        host=config.host,
        port=config.port,
        dbname=config.database,
        user=config.user,
        password=config.password,
        connect_timeout=10,
        row_factory=dict_row,
    )
    try:
        yield connection
    finally:
        connection.close()


def test_connection(project_root: Path | None = None) -> dict[str, str]:
    config = load_postgres_config(project_root)
    with connect(config) as connection:
        row = connection.execute(
            "SELECT current_database() AS database, version() AS version"
        ).fetchone() or {}
    return {"database": str(row.get("database") or ""), "version": str(row.get("version") or "")}


def init_schema(connection: Connection[Any]) -> None:
    statements = (
        "CREATE EXTENSION IF NOT EXISTS vector",
        """
        CREATE TABLE IF NOT EXISTS products (
            id BIGSERIAL PRIMARY KEY,
            platform TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            product_name TEXT NULL,
            product_url TEXT NULL,
            image_url TEXT NULL,
            current_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            comparable_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            comparable_fingerprint CHAR(64) NOT NULL,
            first_seen_at TIMESTAMPTZ NOT NULL,
            last_collected_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (platform, external_product_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS product_prices (
            id BIGSERIAL PRIMARY KEY,
            product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            collected_at TIMESTAMPTZ NOT NULL,
            price_type TEXT NOT NULL DEFAULT 'primary',
            amount NUMERIC(18, 2) NULL,
            currency CHAR(3) NOT NULL DEFAULT 'KRW',
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (product_id, collected_at, price_type)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS product_inventory (
            id BIGSERIAL PRIMARY KEY,
            product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            collected_at TIMESTAMPTZ NOT NULL,
            stock_quantity NUMERIC(18, 2) NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (product_id, collected_at)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS product_shipping_fees (
            id BIGSERIAL PRIMARY KEY,
            product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            collected_at TIMESTAMPTZ NOT NULL,
            fee NUMERIC(18, 2) NULL,
            shipping_type TEXT NULL,
            is_free_shipping BOOLEAN NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (product_id, collected_at)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS product_change_history (
            id BIGSERIAL PRIMARY KEY,
            product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            changed_at TIMESTAMPTZ NOT NULL,
            change_type TEXT NOT NULL,
            before_fingerprint CHAR(64) NULL,
            after_fingerprint CHAR(64) NOT NULL,
            before_payload JSONB NULL,
            after_payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS product_embeddings (
            product_id BIGINT PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
            embedding_source TEXT NOT NULL DEFAULT 'product_name',
            model_name TEXT NULL,
            dimensions INTEGER NOT NULL DEFAULT {DEFAULT_EMBEDDING_DIMENSIONS},
            embedding vector({DEFAULT_EMBEDDING_DIMENSIONS}) NULL,
            embedded_text TEXT NULL,
            embedded_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_products_platform_external_id ON products(platform, external_product_id)",
        "CREATE INDEX IF NOT EXISTS idx_products_last_collected_at ON products(last_collected_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_change_history_product_changed_at ON product_change_history(product_id, changed_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_prices_product_collected_at ON product_prices(product_id, collected_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_inventory_product_collected_at ON product_inventory(product_id, collected_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_shipping_fees_product_collected_at ON product_shipping_fees(product_id, collected_at)",
    )
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
    connection.commit()


def save_product_snapshots(
    *,
    project_root: Path,
    platform: str,
    collected_at: str,
    products: Iterable[dict[str, Any]],
) -> int:
    rows = [_snapshot_row(platform, collected_at, product) for product in products]
    rows = [row for row in rows if row is not None]
    if not rows:
        return 0

    config = load_postgres_config(project_root)
    with connect(config) as connection:
        init_schema(connection)
        for row in rows:
            _save_snapshot(connection, row)
        connection.commit()
    return len(rows)


def save_product_snapshots_if_enabled(
    *,
    project_root: Path,
    platform: str,
    collected_at: str,
    products: Iterable[dict[str, Any]],
    logger: logging.Logger | None = None,
) -> int:
    if not postgres_enabled(project_root):
        return 0

    saved_count = save_product_snapshots(
        project_root=project_root,
        platform=platform,
        collected_at=collected_at,
        products=products,
    )
    if logger is not None:
        logger.info("saved PostgreSQL product snapshots count=%d", saved_count)
    return saved_count


def _save_snapshot(connection: Connection[Any], row: dict[str, Any]) -> None:
    existing = connection.execute(
        """
        SELECT id, comparable_fingerprint, comparable_payload, first_seen_at
        FROM products
        WHERE platform = %s AND external_product_id = %s
        """,
        (row["platform"], row["external_product_id"]),
    ).fetchone()
    before_fingerprint = existing.get("comparable_fingerprint") if existing else None
    before_payload = existing.get("comparable_payload") if existing else None
    first_seen_at = existing.get("first_seen_at") if existing else row["collected_at"]

    product = connection.execute(
        """
        INSERT INTO products (
            platform,
            external_product_id,
            product_name,
            product_url,
            image_url,
            current_payload,
            comparable_payload,
            comparable_fingerprint,
            first_seen_at,
            last_collected_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (platform, external_product_id) DO UPDATE SET
            product_name = EXCLUDED.product_name,
            product_url = EXCLUDED.product_url,
            image_url = EXCLUDED.image_url,
            current_payload = EXCLUDED.current_payload,
            comparable_payload = EXCLUDED.comparable_payload,
            comparable_fingerprint = EXCLUDED.comparable_fingerprint,
            last_collected_at = EXCLUDED.last_collected_at,
            updated_at = now()
        RETURNING id
        """,
        (
            row["platform"],
            row["external_product_id"],
            row["product_name"],
            row["product_url"],
            row["image_url"],
            Jsonb(row["current_payload"]),
            Jsonb(row["comparable_payload"]),
            row["comparable_fingerprint"],
            first_seen_at,
            row["collected_at"],
        ),
    ).fetchone()
    product_id = product["id"]

    _insert_price(connection, product_id, row)
    _insert_inventory(connection, product_id, row)
    _insert_shipping(connection, product_id, row)
    _ensure_embedding_placeholder(connection, product_id)

    if before_fingerprint != row["comparable_fingerprint"]:
        connection.execute(
            """
            INSERT INTO product_change_history (
                product_id,
                changed_at,
                change_type,
                before_fingerprint,
                after_fingerprint,
                before_payload,
                after_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                product_id,
                row["collected_at"],
                "initial" if before_fingerprint is None else "update",
                before_fingerprint,
                row["comparable_fingerprint"],
                Jsonb(before_payload) if before_payload is not None else None,
                Jsonb(row["comparable_payload"]),
            ),
        )


def _insert_price(connection: Connection[Any], product_id: int, row: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO product_prices (product_id, collected_at, amount, payload)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (product_id, collected_at, price_type) DO UPDATE SET
            amount = EXCLUDED.amount,
            payload = EXCLUDED.payload
        """,
        (product_id, row["collected_at"], row["primary_price"], Jsonb(row["prices_payload"])),
    )


def _insert_inventory(connection: Connection[Any], product_id: int, row: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO product_inventory (product_id, collected_at, stock_quantity, payload)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (product_id, collected_at) DO UPDATE SET
            stock_quantity = EXCLUDED.stock_quantity,
            payload = EXCLUDED.payload
        """,
        (product_id, row["collected_at"], row["stock_quantity"], Jsonb(row["inventory_payload"])),
    )


def _insert_shipping(connection: Connection[Any], product_id: int, row: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO product_shipping_fees (product_id, collected_at, fee, shipping_type, is_free_shipping, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (product_id, collected_at) DO UPDATE SET
            fee = EXCLUDED.fee,
            shipping_type = EXCLUDED.shipping_type,
            is_free_shipping = EXCLUDED.is_free_shipping,
            payload = EXCLUDED.payload
        """,
        (
            product_id,
            row["collected_at"],
            row["shipping_fee"],
            row["shipping_type"],
            row["is_free_shipping"],
            Jsonb(row["shipping_payload"]),
        ),
    )


def _ensure_embedding_placeholder(connection: Connection[Any], product_id: int) -> None:
    connection.execute(
        """
        INSERT INTO product_embeddings (product_id)
        VALUES (%s)
        ON CONFLICT (product_id) DO NOTHING
        """,
        (product_id,),
    )


def _snapshot_row(platform: str, collected_at: str, product: dict[str, Any]) -> dict[str, Any] | None:
    external_id = external_product_id(product)
    if not external_id:
        return None
    current = normalize_current_product(product)
    comparable = comparable_state(product)
    prices = _section_or_empty(comparable, current, "prices")
    inventory = _section_or_empty(comparable, current, "inventory")
    shipping = _section_or_empty(comparable, current, "shipping")
    return {
        "platform": platform,
        "external_product_id": external_id,
        "collected_at": _parse_datetime(collected_at),
        "product_name": _first_text(current, "productName", "name", "title"),
        "product_url": _first_text(current, "productUrl", "affiliateUrl", "url"),
        "image_url": _first_text(current, "imageUrl", "productImage"),
        "current_payload": current,
        "comparable_payload": comparable,
        "comparable_fingerprint": fingerprint_state(comparable),
        "prices_payload": prices,
        "inventory_payload": inventory,
        "shipping_payload": shipping,
        "primary_price": _decimal_or_none(_extract_primary_price(prices, current)),
        "stock_quantity": _decimal_or_none(_first_available_value(inventory, current, "stockQuantity")),
        "shipping_fee": _decimal_or_none(_first_value(shipping, "fee", "domeFee", "supplyFee")),
        "shipping_type": _text_or_none(_first_value(shipping, "type", "feeType", "domeFeeType", "supplyFeeType")),
        "is_free_shipping": _bool_or_none(_first_available_value(shipping, current, "isFreeShipping")),
    }


def _parse_datetime(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _object_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _section_or_empty(comparable: dict[str, Any], current: dict[str, Any], key: str) -> dict[str, Any]:
    comparable_section = _object_or_empty(comparable.get(key))
    if any(_has_value(value) for value in comparable_section.values()):
        return comparable_section
    return _object_or_empty(current.get(key)) or comparable_section


def _first_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if _has_value(value):
            return value
    return None


def _first_available_value(primary: dict[str, Any], fallback: dict[str, Any], key: str) -> Any:
    value = primary.get(key)
    if _has_value(value):
        return value
    value = fallback.get(key)
    return value if _has_value(value) else None


def _has_value(value: Any) -> bool:
    return value not in (None, "") and value != {"__value__": "__MISSING__"}


def _text_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in TRUE_VALUES:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return None


def _extract_primary_price(prices: dict[str, Any], current: dict[str, Any]) -> Any:
    for key in ("productPrice", "salePrice", "price", "supplyPrice"):
        value = prices.get(key) if key in prices else current.get(key)
        if value not in (None, ""):
            return value
    for value in prices.values():
        if isinstance(value, (int, float, str)) and not isinstance(value, bool):
            return value
    return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None

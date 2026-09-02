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
from shipping_fees import parse_shipping_fee


TRUE_VALUES = {"1", "true", "yes", "y", "on"}
DOMEGGOOK_RANKED_SORTS = {"ha", "rd"}

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
        """
        CREATE TABLE IF NOT EXISTS products (
            id BIGSERIAL PRIMARY KEY,
            platform TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            product_name TEXT NULL,
            product_url TEXT NULL,
            image_url TEXT NULL,
            backup_image_url TEXT NULL,
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
            market TEXT NOT NULL DEFAULT 'default',
            price_type TEXT NOT NULL DEFAULT 'primary',
            amount NUMERIC(18, 2) NULL,
            currency CHAR(3) NOT NULL DEFAULT 'KRW',
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT product_prices_product_collected_market_type_key UNIQUE (product_id, collected_at, market, price_type)
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
            market TEXT NOT NULL DEFAULT 'default',
            fee NUMERIC(18, 2) NULL,
            shipping_type TEXT NULL,
            is_free_shipping BOOLEAN NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT product_shipping_fees_product_collected_market_key UNIQUE (product_id, collected_at, market)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS product_raw_samples (
            id BIGSERIAL PRIMARY KEY,
            platform TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            collected_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT product_raw_samples_platform_collected_product_key UNIQUE (platform, collected_at, external_product_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS product_search_ranks (
            id BIGSERIAL PRIMARY KEY,
            platform TEXT NOT NULL,
            collected_at TIMESTAMPTZ NOT NULL,
            keyword TEXT NOT NULL DEFAULT '',
            category_code TEXT NOT NULL DEFAULT '',
            category_name TEXT NULL,
            category_path JSONB NOT NULL DEFAULT '[]'::jsonb,
            market TEXT NOT NULL DEFAULT 'default',
            sort TEXT NOT NULL DEFAULT '',
            reason TEXT NULL,
            external_product_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT product_search_ranks_history_key
                UNIQUE (platform, collected_at, keyword, category_code, market, sort, external_product_id, rank)
        )
        """,
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS backup_image_url TEXT NULL",
        "ALTER TABLE product_search_ranks ADD COLUMN IF NOT EXISTS keyword TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE product_search_ranks ADD COLUMN IF NOT EXISTS category_code TEXT NOT NULL DEFAULT ''",
        "UPDATE product_search_ranks SET keyword = '' WHERE keyword IS NULL",
        "UPDATE product_search_ranks SET category_code = '' WHERE category_code IS NULL",
        "ALTER TABLE product_search_ranks ALTER COLUMN keyword SET DEFAULT ''",
        "ALTER TABLE product_search_ranks ALTER COLUMN category_code SET DEFAULT ''",
        "ALTER TABLE product_search_ranks ALTER COLUMN keyword SET NOT NULL",
        "ALTER TABLE product_search_ranks ALTER COLUMN category_code SET NOT NULL",
        "DELETE FROM product_search_ranks WHERE rank <= 0",
        "DELETE FROM product_search_ranks WHERE platform = 'domeggook' AND sort NOT IN ('ha', 'rd')",
        "ALTER TABLE product_search_ranks DROP CONSTRAINT IF EXISTS product_search_ranks_platform_collected_market_sort_product_rank_key",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'product_search_ranks_history_key'
            ) THEN
                ALTER TABLE product_search_ranks
                ADD CONSTRAINT product_search_ranks_history_key
                UNIQUE (platform, collected_at, keyword, category_code, market, sort, external_product_id, rank);
            END IF;
        END $$;
        """,
        "ALTER TABLE product_prices ADD COLUMN IF NOT EXISTS market TEXT NOT NULL DEFAULT 'default'",
        "ALTER TABLE product_shipping_fees ADD COLUMN IF NOT EXISTS market TEXT NOT NULL DEFAULT 'default'",
        "ALTER TABLE product_prices DROP CONSTRAINT IF EXISTS product_prices_product_id_collected_at_price_type_key",
        "ALTER TABLE product_shipping_fees DROP CONSTRAINT IF EXISTS product_shipping_fees_product_id_collected_at_key",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'product_prices_product_collected_market_type_key'
            ) THEN
                ALTER TABLE product_prices
                ADD CONSTRAINT product_prices_product_collected_market_type_key
                UNIQUE (product_id, collected_at, market, price_type);
            END IF;
        END $$;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'product_shipping_fees_product_collected_market_key'
            ) THEN
                ALTER TABLE product_shipping_fees
                ADD CONSTRAINT product_shipping_fees_product_collected_market_key
                UNIQUE (product_id, collected_at, market);
            END IF;
        END $$;
        """,
        """
        INSERT INTO product_prices (product_id, collected_at, market, price_type, amount, currency, payload, created_at)
        SELECT product_id, collected_at, market, price_type, amount, currency, payload, created_at
        FROM (
            SELECT
                product_id,
                collected_at,
                market,
                price_type,
                CASE
                    WHEN value_text ~ '^[+-]?(?:\\d+|\\d{1,3}(?:,\\d{3})+)(?:\\.\\d+)?$'
                    THEN replace(value_text, ',', '')::numeric
                    ELSE NULL
                END AS amount,
                currency,
                payload,
                created_at
            FROM (
                SELECT pp.product_id, pp.collected_at, pp.currency, pp.payload, pp.created_at, v.market, v.price_type, pp.payload #>> ARRAY[v.payload_key] AS value_text
                FROM product_prices pp
                CROSS JOIN (
                    VALUES
                        ('dome', 'current_supply', 'domeCurrentSupplyPrice'),
                        ('supply', 'current_supply', 'supplyCurrentSupplyPrice'),
                        ('retail', 'minimum_retail', 'minimumRetailPrice'),
                        ('retail', 'recommended_retail', 'recommendedRetailPrice')
                ) AS v(market, price_type, payload_key)
                WHERE pp.market = 'default'
                  AND pp.payload ? v.payload_key
                  AND pp.payload -> v.payload_key <> 'null'::jsonb
                  AND pp.payload #>> ARRAY[v.payload_key] <> ''
            ) source_values
        ) backfill_rows
        ON CONFLICT (product_id, collected_at, market, price_type) DO UPDATE SET
            amount = EXCLUDED.amount,
            payload = EXCLUDED.payload
        """,
        """
        INSERT INTO product_prices (product_id, collected_at, market, price_type, amount, currency, payload, created_at)
        SELECT product_id, collected_at, market, price_type, amount, currency, payload, created_at
        FROM (
            SELECT
                pp.product_id,
                pp.collected_at,
                p.platform AS market,
                v.price_type,
                CASE
                    WHEN pp.payload #>> ARRAY[v.payload_key] ~ '^[+-]?(?:\\d+|\\d{1,3}(?:,\\d{3})+)(?:\\.\\d+)?$'
                    THEN replace(pp.payload #>> ARRAY[v.payload_key], ',', '')::numeric
                    ELSE NULL
                END AS amount,
                pp.currency,
                pp.payload,
                pp.created_at
            FROM product_prices pp
            JOIN products p ON p.id = pp.product_id
            CROSS JOIN (
                VALUES
                    ('current_supply', 'currentSupplyPrice'),
                    ('fixed', 'fixedPrice')
            ) AS v(price_type, payload_key)
            WHERE pp.market = 'default'
              AND pp.payload ? v.payload_key
              AND pp.payload -> v.payload_key <> 'null'::jsonb
              AND pp.payload #>> ARRAY[v.payload_key] <> ''
        ) backfill_rows
        ON CONFLICT (product_id, collected_at, market, price_type) DO UPDATE SET
            amount = EXCLUDED.amount,
            payload = EXCLUDED.payload
        """,
        """
        INSERT INTO product_shipping_fees (product_id, collected_at, market, fee, shipping_type, is_free_shipping, payload, created_at)
        SELECT product_id, collected_at, market, fee, shipping_type, is_free_shipping, payload, created_at
        FROM (
            SELECT
                ps.product_id,
                ps.collected_at,
                v.market,
                CASE
                    WHEN ps.payload #>> ARRAY[v.fee_key] ~ '^[+-]?(?:\\d+|\\d{1,3}(?:,\\d{3})+)(?:\\.\\d+)?$'
                    THEN replace(ps.payload #>> ARRAY[v.fee_key], ',', '')::numeric
                    ELSE NULL
                END AS fee,
                NULLIF(ps.payload #>> ARRAY[v.type_key], '') AS shipping_type,
                ps.is_free_shipping,
                ps.payload,
                ps.created_at
            FROM product_shipping_fees ps
            CROSS JOIN (
                VALUES
                    ('dome', 'domeFee', 'domeFeeType'),
                    ('supply', 'supplyFee', 'supplyFeeType')
            ) AS v(market, fee_key, type_key)
            WHERE ps.market = 'default'
              AND (
                  (
                      ps.payload ? v.fee_key
                      AND ps.payload -> v.fee_key <> 'null'::jsonb
                      AND ps.payload -> v.fee_key <> '{"__value__": "__MISSING__"}'::jsonb
                      AND ps.payload #>> ARRAY[v.fee_key] <> ''
                  )
                  OR (
                      ps.payload ? v.type_key
                      AND ps.payload -> v.type_key <> 'null'::jsonb
                      AND ps.payload -> v.type_key <> '{"__value__": "__MISSING__"}'::jsonb
                      AND ps.payload #>> ARRAY[v.type_key] <> ''
                  )
              )
        ) backfill_rows
        ON CONFLICT (product_id, collected_at, market) DO UPDATE SET
            fee = EXCLUDED.fee,
            shipping_type = EXCLUDED.shipping_type,
            is_free_shipping = EXCLUDED.is_free_shipping,
            payload = EXCLUDED.payload
        """,
        """
        INSERT INTO product_shipping_fees (product_id, collected_at, market, fee, shipping_type, is_free_shipping, payload, created_at)
        SELECT product_id, collected_at, market, fee, shipping_type, is_free_shipping, payload, created_at
        FROM (
            SELECT
                ps.product_id,
                ps.collected_at,
                p.platform AS market,
                CASE
                    WHEN ps.payload #>> '{fee}' ~ '^[+-]?(?:\\d+|\\d{1,3}(?:,\\d{3})+)(?:\\.\\d+)?$'
                    THEN replace(ps.payload #>> '{fee}', ',', '')::numeric
                    ELSE NULL
                END AS fee,
                NULLIF(COALESCE(ps.payload #>> '{type}', ps.payload #>> '{feeType}'), '') AS shipping_type,
                ps.is_free_shipping,
                ps.payload,
                ps.created_at
            FROM product_shipping_fees ps
            JOIN products p ON p.id = ps.product_id
            WHERE ps.market = 'default'
              AND (
                  (
                      ps.payload ? 'fee'
                      AND ps.payload -> 'fee' <> 'null'::jsonb
                      AND ps.payload -> 'fee' <> '{"__value__": "__MISSING__"}'::jsonb
                      AND ps.payload #>> '{fee}' <> ''
                  )
                  OR (
                      ps.payload ? 'type'
                      AND ps.payload -> 'type' <> 'null'::jsonb
                      AND ps.payload -> 'type' <> '{"__value__": "__MISSING__"}'::jsonb
                      AND ps.payload #>> '{type}' <> ''
                  )
                  OR (
                      ps.payload ? 'feeType'
                      AND ps.payload -> 'feeType' <> 'null'::jsonb
                      AND ps.payload -> 'feeType' <> '{"__value__": "__MISSING__"}'::jsonb
                      AND ps.payload #>> '{feeType}' <> ''
                  )
              )
        ) backfill_rows
        ON CONFLICT (product_id, collected_at, market) DO UPDATE SET
            fee = EXCLUDED.fee,
            shipping_type = EXCLUDED.shipping_type,
            is_free_shipping = EXCLUDED.is_free_shipping,
            payload = EXCLUDED.payload
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
        "CREATE INDEX IF NOT EXISTS idx_products_platform_external_id ON products(platform, external_product_id)",
        "CREATE INDEX IF NOT EXISTS idx_products_last_collected_at ON products(last_collected_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_change_history_product_changed_at ON product_change_history(product_id, changed_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_prices_product_collected_at ON product_prices(product_id, collected_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_inventory_product_collected_at ON product_inventory(product_id, collected_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_shipping_fees_product_collected_at ON product_shipping_fees(product_id, collected_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_raw_samples_platform_collected_at ON product_raw_samples(platform, collected_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_search_ranks_platform_collected_at ON product_search_ranks(platform, collected_at)",
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


def save_product_raw_samples_if_enabled(
    *,
    project_root: Path,
    platform: str,
    collected_at: str,
    products: Iterable[dict[str, Any]],
    limit: int,
    logger: logging.Logger | None = None,
) -> int:
    if not postgres_enabled(project_root):
        return 0
    if limit < 0:
        raise ValueError("limit must be zero or greater")

    rows: list[dict[str, Any]] = []
    for product in products:
        if len(rows) >= min(limit, 3):
            break
        raw = product.get("raw")
        external_id = external_product_id(product)
        if raw is None or not external_id:
            continue
        rows.append(
            {
                "platform": platform,
                "external_product_id": external_id,
                "collected_at": _parse_datetime(collected_at),
                "payload": raw,
            }
        )
    if not rows:
        return 0

    config = load_postgres_config(project_root)
    with connect(config) as connection:
        init_schema(connection)
        for row in rows:
            connection.execute(
                """
                INSERT INTO product_raw_samples (platform, external_product_id, collected_at, payload)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (platform, collected_at, external_product_id) DO UPDATE SET
                    payload = EXCLUDED.payload
                """,
                (
                    row["platform"],
                    row["external_product_id"],
                    row["collected_at"],
                    Jsonb(_json_safe(row["payload"])),
                ),
            )
        connection.commit()
    if logger is not None:
        logger.info("saved PostgreSQL raw samples count=%d", len(rows))
    return len(rows)


def save_search_ranks_if_enabled(
    *,
    project_root: Path,
    platform: str,
    records: Iterable[dict[str, Any]],
    logger: logging.Logger | None = None,
) -> int:
    if not postgres_enabled(project_root):
        return 0

    rows = _search_rank_rows(platform, records)
    if not rows:
        return 0

    config = load_postgres_config(project_root)
    with connect(config) as connection:
        init_schema(connection)
        for row in rows:
            connection.execute(
                """
                INSERT INTO product_search_ranks (
                    platform,
                    collected_at,
                    keyword,
                    category_code,
                    category_name,
                    category_path,
                    market,
                    sort,
                    reason,
                    external_product_id,
                    rank,
                    payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (platform, collected_at, keyword, category_code, market, sort, external_product_id, rank) DO UPDATE SET
                    category_name = EXCLUDED.category_name,
                    category_path = EXCLUDED.category_path,
                    reason = EXCLUDED.reason,
                    payload = EXCLUDED.payload
                """,
                (
                    row["platform"],
                    row["collected_at"],
                    row["keyword"],
                    row["category_code"],
                    row["category_name"],
                    Jsonb(_json_safe(row["category_path"])),
                    row["market"],
                    row["sort"],
                    row["reason"],
                    row["external_product_id"],
                    row["rank"],
                    Jsonb(_json_safe(row["payload"])),
                ),
            )
        connection.commit()
    if logger is not None:
        logger.info("saved PostgreSQL search ranks count=%d", len(rows))
    return len(rows)


def _search_rank_rows(platform: str, records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        product_id = record.get("productId")
        collected_at = record.get("collectedAt")
        sort = _text_or_none(record.get("sort") or record.get("sortBy")) or ""
        rank = _positive_int(record.get("rank"))
        if product_id in (None, "") or collected_at in (None, "") or rank is None:
            continue
        if platform == "domeggook" and sort not in DOMEGGOOK_RANKED_SORTS:
            continue
        rows.append(
            {
                "platform": platform,
                "collected_at": _parse_datetime(str(collected_at)),
                "keyword": _text_or_none(record.get("keyword")) or "",
                "category_code": _text_or_none(record.get("categoryCode")) or "",
                "category_name": _text_or_none(record.get("categoryName")),
                "category_path": record.get("categoryPath") if isinstance(record.get("categoryPath"), list) else [],
                "market": _text_or_none(record.get("market")) or "default",
                "sort": sort,
                "reason": _text_or_none(record.get("reason")),
                "external_product_id": str(product_id),
                "rank": rank,
                "payload": record,
            }
        )
    return rows


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


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
            backup_image_url,
            current_payload,
            comparable_payload,
            comparable_fingerprint,
            first_seen_at,
            last_collected_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (platform, external_product_id) DO UPDATE SET
            product_name = EXCLUDED.product_name,
            product_url = EXCLUDED.product_url,
            image_url = EXCLUDED.image_url,
            backup_image_url = EXCLUDED.backup_image_url,
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
            row["backup_image_url"],
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
    for price in row["price_rows"]:
        connection.execute(
            """
            INSERT INTO product_prices (product_id, collected_at, market, price_type, amount, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (product_id, collected_at, market, price_type) DO UPDATE SET
                amount = EXCLUDED.amount,
                payload = EXCLUDED.payload
            """,
            (
                product_id,
                row["collected_at"],
                price["market"],
                price["price_type"],
                price["amount"],
                Jsonb(row["prices_payload"]),
            ),
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
    for shipping in row["shipping_rows"]:
        connection.execute(
            """
            INSERT INTO product_shipping_fees (product_id, collected_at, market, fee, shipping_type, is_free_shipping, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (product_id, collected_at, market) DO UPDATE SET
                fee = EXCLUDED.fee,
                shipping_type = EXCLUDED.shipping_type,
                is_free_shipping = EXCLUDED.is_free_shipping,
                payload = EXCLUDED.payload
            """,
            (
                product_id,
                row["collected_at"],
                shipping["market"],
                shipping["fee"],
                shipping["shipping_type"],
                row["is_free_shipping"],
                Jsonb(_json_safe(shipping.get("payload", row["shipping_payload"]))),
            ),
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
    shipping_payload = _shipping_payload(comparable, current)
    shipping_rows = _shipping_rows(platform, shipping_payload)
    return {
        "platform": platform,
        "external_product_id": external_id,
        "collected_at": _parse_datetime(collected_at),
        "product_name": _first_text(current, "productName", "name", "title"),
        "product_url": _first_text(current, "productUrl", "affiliateUrl", "url"),
        "image_url": _first_text(current, "imageUrl", "productImage"),
        "backup_image_url": _first_text(current, "backupImageUrl"),
        "current_payload": current,
        "comparable_payload": comparable,
        "comparable_fingerprint": fingerprint_state(comparable),
        "prices_payload": prices,
        "inventory_payload": inventory,
        "shipping_payload": shipping_payload,
        "primary_price": _decimal_or_none(_extract_primary_price(prices, current)),
        "price_rows": _price_rows(platform, prices, current),
        "stock_quantity": _decimal_or_none(_first_available_value(inventory, current, "stockQuantity")),
        "shipping_fee": shipping_rows[0]["fee"],
        "shipping_type": _text_or_none(_first_value(shipping_payload, "type", "feeType", "domeFeeType", "supplyFeeType")),
        "shipping_rows": shipping_rows,
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


def _shipping_payload(comparable: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    current_shipping = _object_or_empty(current.get("shipping"))
    comparable_shipping = _object_or_empty(comparable.get("shipping"))
    payload = {
        key: value
        for key, value in comparable_shipping.items()
        if _has_value(value)
    }
    payload.update(
        {
            key: value
            for key, value in current_shipping.items()
            if _has_value(value)
        }
    )
    return payload or comparable_shipping


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


def _price_rows(platform: str, prices: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if _has_value(prices.get("domeCurrentSupplyPrice")):
        rows.append(
            {
                "market": "dome",
                "price_type": "current_supply",
                "amount": _decimal_or_none(prices.get("domeCurrentSupplyPrice")),
            }
        )
    if _has_value(prices.get("supplyCurrentSupplyPrice")):
        rows.append(
            {
                "market": "supply",
                "price_type": "current_supply",
                "amount": _decimal_or_none(prices.get("supplyCurrentSupplyPrice")),
            }
        )
    if _has_value(prices.get("minimumRetailPrice")):
        rows.append(
            {
                "market": "retail",
                "price_type": "minimum_retail",
                "amount": _decimal_or_none(prices.get("minimumRetailPrice")),
            }
        )
    if _has_value(prices.get("recommendedRetailPrice")):
        rows.append(
            {
                "market": "retail",
                "price_type": "recommended_retail",
                "amount": _decimal_or_none(prices.get("recommendedRetailPrice")),
            }
        )
    if _has_value(prices.get("currentSupplyPrice")):
        rows.append(
            {
                "market": platform,
                "price_type": "current_supply",
                "amount": _decimal_or_none(prices.get("currentSupplyPrice")),
            }
        )
    if _has_value(prices.get("fixedPrice")):
        rows.append(
            {
                "market": platform,
                "price_type": "fixed",
                "amount": _decimal_or_none(prices.get("fixedPrice")),
            }
        )
    if rows:
        return rows
    return [
        {
            "market": platform,
            "price_type": "primary",
            "amount": _decimal_or_none(_extract_primary_price(prices, current)),
        }
    ]


def _shipping_rows(platform: str, shipping: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if _has_value(shipping.get("domeFee")) or _has_value(shipping.get("domeFeeType")):
        parsed = parse_shipping_fee(
            _first_value(shipping, "domeFeeRaw", "domeFee"),
            shipping.get("domeFeeType"),
            fee_payer=_first_value(shipping, "domeFeePayer", "feePayer", "deliWho", "who"),
        )
        rows.append(
            {
                "market": "dome",
                "fee": parsed["shipping_fee"],
                "shipping_type": _text_or_none(shipping.get("domeFeeType")),
                **parsed,
                "payload": _shipping_row_payload(shipping, "dome", parsed),
            }
        )
    if _has_value(shipping.get("supplyFee")) or _has_value(shipping.get("supplyFeeType")):
        parsed = parse_shipping_fee(
            _first_value(shipping, "supplyFeeRaw", "supplyFee"),
            shipping.get("supplyFeeType"),
            fee_payer=_first_value(shipping, "supplyFeePayer", "feePayer", "deliWho", "who"),
        )
        rows.append(
            {
                "market": "supply",
                "fee": parsed["shipping_fee"],
                "shipping_type": _text_or_none(shipping.get("supplyFeeType")),
                **parsed,
                "payload": _shipping_row_payload(shipping, "supply", parsed),
            }
        )
    if rows:
        return rows
    parsed = parse_shipping_fee(
        _first_value(shipping, "feeRaw", "fee"),
        _first_value(shipping, "type", "feeType"),
        fee_payer=_first_value(shipping, "shippingPayment", "feePayer", "deliWho", "who", "type", "feeType"),
    )
    return [
        {
            "market": platform,
            "fee": parsed["shipping_fee"],
            "shipping_type": _text_or_none(_first_value(shipping, "type", "feeType")),
            **parsed,
            "payload": _shipping_row_payload(shipping, platform, parsed),
        }
    ]


def _shipping_row_payload(shipping: dict[str, Any], market: str, parsed: dict[str, Any]) -> dict[str, Any]:
    payload = dict(shipping)
    payload["market"] = market
    payload.update(parsed)
    remote_area_fee = _remote_area_fee(shipping)
    if remote_area_fee:
        payload["remote_area_fee"] = remote_area_fee
    payload["source_fields"] = _shipping_source_fields(shipping, market)
    return payload


def _remote_area_fee(shipping: dict[str, Any]) -> dict[str, Any]:
    fees: dict[str, Any] = {}
    jeju = _first_value(shipping, "feeExtraJeju")
    islands = _first_value(shipping, "feeExtraIslands")
    nested = shipping.get("remoteAreaFee") if isinstance(shipping.get("remoteAreaFee"), dict) else {}
    jeju = jeju if _has_value(jeju) else _first_value(nested, "jeju")
    islands = islands if _has_value(islands) else _first_value(nested, "islands")
    if _has_value(jeju):
        fees["jeju"] = jeju
    if _has_value(islands):
        fees["islands"] = islands
    return fees


def _shipping_source_fields(shipping: dict[str, Any], market: str) -> dict[str, Any]:
    if market == "dome":
        return {
            "fee": _first_value(shipping, "domeFeeRaw", "domeFee"),
            "type": shipping.get("domeFeeType"),
            "tbl": shipping.get("domeFeeTable"),
            "pay": _first_value(shipping, "domeFeePayer", "feePayer", "deliWho", "who"),
        }
    if market == "supply":
        return {
            "fee": _first_value(shipping, "supplyFeeRaw", "supplyFee"),
            "type": shipping.get("supplyFeeType"),
            "tbl": shipping.get("supplyFeeTable"),
            "pay": _first_value(shipping, "supplyFeePayer", "feePayer", "deliWho", "who"),
        }
    source_fields = shipping.get("sourceFields")
    if isinstance(source_fields, dict):
        return dict(source_fields)
    return {
        "fee": _first_value(shipping, "feeRaw", "fee"),
        "type": _first_value(shipping, "typeRaw", "type", "feeType"),
        "pay": _first_value(shipping, "shippingPayment", "feePayer", "deliWho", "who"),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _json_safe(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_safe(child) for child in value]
    return value


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None

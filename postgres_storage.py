from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import psycopg
from dotenv import load_dotenv
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from numeric_utils import parse_decimal
from product_history import (
    canonicalize,
    changed_leaf_paths,
    comparable_state,
    external_product_id,
    flatten_paths,
    normalize_current_product,
)
from shipping_fees import parse_shipping_fee


TRUE_VALUES = {"1", "true", "yes", "y", "on"}
DOMEGGOOK_RANKED_SORTS = {"ha", "rd"}
DEFAULT_PRODUCT_BATCH_SIZE = 1000
PRODUCT_BATCH_SIZE_ENV = "POSTGRES_PRODUCT_BATCH_SIZE"
LOGGER = logging.getLogger(__name__)

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


def product_counts(project_root: Path | None = None) -> dict[str, int]:
    config = load_postgres_config(project_root)
    with connect(config) as connection:
        init_schema(connection)
        rows = connection.execute(
            """
            SELECT platform, count(*) AS count
            FROM products
            GROUP BY platform
            ORDER BY platform
            """
        ).fetchall()
    return {str(row["platform"]): int(row["count"]) for row in rows}


def discovered_product_ids(
    *,
    project_root: Path,
    platform: str,
    limit: int | None = None,
) -> list[str]:
    if not postgres_enabled(project_root):
        return []
    config = load_postgres_config(project_root)
    with connect(config) as connection:
        init_schema(connection)
        query = """
            SELECT external_product_id
            FROM product_discovery_targets
            WHERE platform = %s AND active
            ORDER BY first_discovered_at, external_product_id
        """
        params: tuple[Any, ...] = (platform,)
        if limit is not None:
            query += " LIMIT %s"
            params = (platform, limit)
        rows = connection.execute(query, params).fetchall()
    return [str(row["external_product_id"]) for row in rows]


def save_discovered_product_ids_if_enabled(
    *,
    project_root: Path,
    platform: str,
    records: Iterable[dict[str, Any]],
    logger: logging.Logger | None = None,
) -> int:
    if not postgres_enabled(project_root):
        return 0

    rows = _discovery_target_rows(platform, records)
    if not rows:
        return 0

    inserted_count = 0
    config = load_postgres_config(project_root)
    with connect(config) as connection:
        init_schema(connection)
        for row in rows:
            inserted = connection.execute(
                """
                INSERT INTO product_discovery_targets (
                    platform,
                    external_product_id,
                    first_discovered_at,
                    last_discovered_at,
                    keyword,
                    category_code,
                    category_name,
                    market,
                    reason,
                    payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (platform, external_product_id) DO NOTHING
                RETURNING id
                """,
                (
                    row["platform"],
                    row["external_product_id"],
                    row["discovered_at"],
                    row["discovered_at"],
                    row["keyword"],
                    row["category_code"],
                    row["category_name"],
                    row["market"],
                    row["reason"],
                    Jsonb(_json_safe(row["payload"])),
                ),
            ).fetchone()
            if inserted:
                inserted_count += 1
                continue
            connection.execute(
                """
                UPDATE product_discovery_targets
                SET last_discovered_at = %s,
                    keyword = COALESCE(%s, keyword),
                    category_code = COALESCE(%s, category_code),
                    category_name = COALESCE(%s, category_name),
                    market = COALESCE(%s, market),
                    reason = COALESCE(%s, reason),
                    payload = %s,
                    active = true,
                    updated_at = now()
                WHERE platform = %s AND external_product_id = %s
                """,
                (
                    row["discovered_at"],
                    row["keyword"],
                    row["category_code"],
                    row["category_name"],
                    row["market"],
                    row["reason"],
                    Jsonb(_json_safe(row["payload"])),
                    row["platform"],
                    row["external_product_id"],
                ),
            )
        connection.commit()
    if logger is not None:
        logger.info("saved PostgreSQL discovery targets count=%d newCount=%d", len(rows), inserted_count)
    return inserted_count


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
            status TEXT NULL,
            seller_external_id TEXT NULL,
            seller_nickname TEXT NULL,
            seller_type TEXT NULL,
            seller_grade TEXT NULL,
            seller_excellent_seller BOOLEAN NULL,
            seller_average_satisfaction TEXT NULL,
            seller_review_count NUMERIC(18, 2) NULL,
            first_seen_at TIMESTAMPTZ NOT NULL,
            last_collected_at TIMESTAMPTZ NOT NULL,
            UNIQUE (platform, external_product_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
        """
        CREATE TABLE IF NOT EXISTS product_discovery_targets (
            id BIGSERIAL PRIMARY KEY,
            platform TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            active BOOLEAN NOT NULL DEFAULT true,
            first_discovered_at TIMESTAMPTZ NOT NULL,
            last_discovered_at TIMESTAMPTZ NOT NULL,
            keyword TEXT NULL,
            category_code TEXT NULL,
            category_name TEXT NULL,
            market TEXT NULL,
            reason TEXT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (platform, external_product_id)
        )
        """,
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS backup_image_url TEXT NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS status TEXT NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS seller_external_id TEXT NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS seller_nickname TEXT NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS seller_type TEXT NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS seller_grade TEXT NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS seller_excellent_seller BOOLEAN NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS seller_average_satisfaction TEXT NULL",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS seller_review_count NUMERIC(18, 2) NULL",
        "ALTER TABLE products DROP COLUMN IF EXISTS current_payload",
        "ALTER TABLE products DROP COLUMN IF EXISTS comparable_payload",
        "ALTER TABLE products DROP COLUMN IF EXISTS comparable_fingerprint",
        "ALTER TABLE products DROP COLUMN IF EXISTS created_at",
        "ALTER TABLE products DROP COLUMN IF EXISTS updated_at",
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
        """
        CREATE TABLE IF NOT EXISTS product_history (
            id BIGSERIAL PRIMARY KEY,
            product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            observed_at TIMESTAMPTZ NOT NULL,
            change_type TEXT NOT NULL,
            changed_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            prices JSONB NOT NULL DEFAULT '{}'::jsonb,
            inventory JSONB NOT NULL DEFAULT '{}'::jsonb,
            shipping JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "ALTER TABLE product_history ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ",
        "ALTER TABLE product_history ADD COLUMN IF NOT EXISTS changed_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]",
        "ALTER TABLE product_history ADD COLUMN IF NOT EXISTS prices JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE product_history ADD COLUMN IF NOT EXISTS inventory JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE product_history ADD COLUMN IF NOT EXISTS shipping JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE product_history ADD COLUMN IF NOT EXISTS status TEXT NULL",
        "UPDATE product_history SET observed_at = created_at WHERE observed_at IS NULL",
        "ALTER TABLE product_history ALTER COLUMN observed_at SET NOT NULL",
        "DROP TABLE IF EXISTS product_change_history",
        "DROP TABLE IF EXISTS product_latest_fields",
        "DROP TABLE IF EXISTS product_prices",
        "DROP TABLE IF EXISTS product_inventory",
        "DROP TABLE IF EXISTS product_shipping_fees",
        "CREATE INDEX IF NOT EXISTS idx_products_platform_external_id ON products(platform, external_product_id)",
        "CREATE INDEX IF NOT EXISTS idx_products_last_collected_at ON products(last_collected_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_history_product_observed_at ON product_history(product_id, observed_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_history_changed_fields_gin ON product_history USING GIN(changed_fields)",
        "CREATE INDEX IF NOT EXISTS idx_product_raw_samples_platform_collected_at ON product_raw_samples(platform, collected_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_search_ranks_platform_collected_at ON product_search_ranks(platform, collected_at)",
        "CREATE INDEX IF NOT EXISTS idx_product_discovery_targets_platform_active ON product_discovery_targets(platform, active, first_discovered_at)",
    )
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
    _apply_one_time_migrations(connection)
    connection.commit()


def _apply_one_time_migrations(connection: Connection[Any]) -> None:
    migration_name = "drop_payload_based_change_history_20260904"
    applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE name = %s",
        (migration_name,),
    ).fetchone()
    if applied:
        return
    connection.execute("DROP TABLE IF EXISTS product_change_history")
    connection.execute(
        "INSERT INTO schema_migrations (name) VALUES (%s)",
        (migration_name,),
    )


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
    batch_size = _product_batch_size(project_root)
    saved_count = 0
    with connect(config) as connection:
        init_schema(connection)
        for batch in _chunks(rows, batch_size):
            try:
                saved_count += _save_product_batch_with_retry(connection, batch)
            except Exception:
                LOGGER.exception(
                    "failed PostgreSQL product batch platform=%s count=%d firstExternalProductId=%s",
                    platform,
                    len(batch),
                    batch[0]["external_product_id"] if batch else "",
                )
                connection.rollback()
    return saved_count


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


def _discovery_target_rows(platform: str, records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        product_id = record.get("productId") or record.get("productKey") or record.get("externalProductId")
        discovered_at = record.get("collectedAt") or record.get("discoveredAt")
        if product_id in (None, "") or discovered_at in (None, ""):
            continue
        external_id = str(product_id)
        if external_id in seen:
            continue
        seen.add(external_id)
        rows.append(
            {
                "platform": platform,
                "external_product_id": external_id,
                "discovered_at": _parse_datetime(str(discovered_at)),
                "keyword": _text_or_none(record.get("keyword")),
                "category_code": _text_or_none(record.get("categoryCode")),
                "category_name": _text_or_none(record.get("categoryName")),
                "market": _text_or_none(record.get("market")),
                "reason": _text_or_none(record.get("reason")),
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


def _product_batch_size(project_root: Path | None = None) -> int:
    if project_root is not None:
        load_dotenv(project_root / ".env", override=False)
    else:
        load_dotenv(override=False)
    raw = os.getenv(PRODUCT_BATCH_SIZE_ENV)
    if raw in (None, ""):
        return DEFAULT_PRODUCT_BATCH_SIZE
    try:
        parsed = int(str(raw))
    except ValueError:
        LOGGER.warning("invalid %s=%r; using default %d", PRODUCT_BATCH_SIZE_ENV, raw, DEFAULT_PRODUCT_BATCH_SIZE)
        return DEFAULT_PRODUCT_BATCH_SIZE
    if parsed <= 0:
        LOGGER.warning("invalid %s=%r; using default %d", PRODUCT_BATCH_SIZE_ENV, raw, DEFAULT_PRODUCT_BATCH_SIZE)
        return DEFAULT_PRODUCT_BATCH_SIZE
    return parsed


def _chunks(rows: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def _save_product_batch_with_retry(connection: Connection[Any], rows: list[dict[str, Any]]) -> int:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            saved_count = _save_product_batch(connection, rows)
            connection.commit()
            return saved_count
        except Exception as exc:
            last_error = exc
            connection.rollback()
            if attempt == 0:
                LOGGER.warning("retrying PostgreSQL product batch count=%d after failure: %s", len(rows), exc)
    assert last_error is not None
    raise last_error


def _save_product_batch(connection: Connection[Any], rows: list[dict[str, Any]]) -> int:
    unique_rows = _dedupe_product_rows(rows)
    if not unique_rows:
        return 0
    external_ids = [row["external_product_id"] for row in unique_rows]
    existing_states = _existing_product_states(connection, unique_rows[0]["platform"], external_ids)
    history_plans = _history_insert_plans(unique_rows, existing_states)
    _bulk_upsert_products(connection, unique_rows, existing_states)
    product_ids = _product_ids(connection, unique_rows[0]["platform"], external_ids)
    _bulk_insert_history(connection, history_plans, product_ids)
    return len(unique_rows)


def _dedupe_product_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        deduped[row["external_product_id"]] = row
    return list(deduped.values())


def _existing_product_states(
    connection: Connection[Any],
    platform: str,
    external_ids: list[str],
) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            p.id,
            p.external_product_id,
            p.first_seen_at,
            h.prices,
            h.inventory,
            h.shipping,
            h.status
        FROM products p
        LEFT JOIN LATERAL (
            SELECT prices, inventory, shipping, status
            FROM product_history
            WHERE product_id = p.id
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
        ) h ON true
        WHERE p.platform = %s
          AND p.external_product_id = ANY(%s)
        """,
        (platform, external_ids),
    ).fetchall()
    return {str(row["external_product_id"]): row for row in rows}


def _product_ids(connection: Connection[Any], platform: str, external_ids: list[str]) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT id, external_product_id
        FROM products
        WHERE platform = %s
          AND external_product_id = ANY(%s)
        """,
        (platform, external_ids),
    ).fetchall()
    return {str(row["external_product_id"]): int(row["id"]) for row in rows}


def _history_insert_plans(
    rows: list[dict[str, Any]],
    existing_states: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for row in rows:
        current_state = _history_state(row)
        existing = existing_states.get(row["external_product_id"])
        if existing is None or existing.get("prices") is None:
            changed_fields = sorted(flatten_paths(current_state))
            change_type = "initial"
        else:
            previous_state = {
                "prices": existing.get("prices") or {},
                "inventory": existing.get("inventory") or {},
                "shipping": existing.get("shipping") or {},
                "status": existing.get("status"),
            }
            changed_fields = changed_leaf_paths(canonicalize(previous_state), canonicalize(current_state))
            change_type = "update"
        if not changed_fields:
            continue
        plans.append(
            {
                "external_product_id": row["external_product_id"],
                "observed_at": row["collected_at"],
                "change_type": change_type,
                "changed_fields": changed_fields,
                **current_state,
            }
        )
    return plans


def _history_state(row: dict[str, Any]) -> dict[str, Any]:
    shipping_rows = [
        {
            "market": shipping["market"],
            "fee": shipping["fee"],
            "shippingType": shipping["shipping_type"],
            "isFreeShipping": row["is_free_shipping"],
            "payload": shipping.get("payload", row["shipping_payload"]),
        }
        for shipping in row["shipping_rows"]
        if _has_shipping_snapshot(shipping, row)
    ]
    return _json_safe(
        {
            "prices": {
                "rows": row["price_rows"],
                "payload": row["prices_payload"],
            },
            "inventory": {
                "stockQuantity": row["stock_quantity"],
                "payload": row["inventory_payload"] if _has_inventory_snapshot(row) else {},
                "options": row["options_payload"],
            },
            "shipping": {
                "rows": shipping_rows,
                "payload": row["shipping_payload"] if shipping_rows else {},
            },
            "status": row["status"],
        }
    )


def _bulk_upsert_products(
    connection: Connection[Any],
    rows: list[dict[str, Any]],
    existing_states: dict[str, dict[str, Any]],
) -> None:
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO products (
                platform,
                external_product_id,
                product_name,
                product_url,
                image_url,
                backup_image_url,
                status,
                seller_external_id,
                seller_nickname,
                seller_type,
                seller_grade,
                seller_excellent_seller,
                seller_average_satisfaction,
                seller_review_count,
                first_seen_at,
                last_collected_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (platform, external_product_id) DO UPDATE SET
                product_name = EXCLUDED.product_name,
                product_url = EXCLUDED.product_url,
                image_url = EXCLUDED.image_url,
                backup_image_url = EXCLUDED.backup_image_url,
                status = EXCLUDED.status,
                seller_external_id = EXCLUDED.seller_external_id,
                seller_nickname = EXCLUDED.seller_nickname,
                seller_type = EXCLUDED.seller_type,
                seller_grade = EXCLUDED.seller_grade,
                seller_excellent_seller = EXCLUDED.seller_excellent_seller,
                seller_average_satisfaction = EXCLUDED.seller_average_satisfaction,
                seller_review_count = EXCLUDED.seller_review_count,
                last_collected_at = EXCLUDED.last_collected_at
            """,
            [_product_upsert_params(row, existing_states.get(row["external_product_id"])) for row in rows],
        )


def _product_upsert_params(row: dict[str, Any], existing: dict[str, Any] | None) -> tuple[Any, ...]:
    seller = row["seller"]
    first_seen_at = existing.get("first_seen_at") if existing else row["collected_at"]
    return (
        row["platform"],
        row["external_product_id"],
        row["product_name"],
        row["product_url"],
        row["image_url"],
        row["backup_image_url"],
        row["status"],
        seller["id"],
        seller["nickname"],
        seller["type"],
        seller["grade"],
        seller["excellent_seller"],
        seller["average_satisfaction"],
        seller["review_count"],
        first_seen_at,
        row["collected_at"],
    )


def _bulk_insert_history(
    connection: Connection[Any],
    history_plans: list[dict[str, Any]],
    product_ids: dict[str, int],
) -> None:
    rows = [
        (
            product_ids[plan["external_product_id"]],
            plan["observed_at"],
            plan["change_type"],
            plan["changed_fields"],
            Jsonb(plan["prices"]),
            Jsonb(plan["inventory"]),
            Jsonb(plan["shipping"]),
            plan["status"],
        )
        for plan in history_plans
        if plan["external_product_id"] in product_ids
    ]
    if not rows:
        return
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO product_history (
                product_id,
                observed_at,
                change_type,
                changed_fields,
                prices,
                inventory,
                shipping,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )


def _has_inventory_snapshot(row: dict[str, Any]) -> bool:
    if row["stock_quantity"] is not None:
        return True
    return _has_meaningful_payload_value(row["inventory_payload"], ignored_keys={"stockQuantitySource"})


def _has_shipping_snapshot(shipping: dict[str, Any], row: dict[str, Any]) -> bool:
    if shipping["fee"] is not None or row["is_free_shipping"] is not None:
        return True
    if shipping["shipping_type"] not in (None, "", "unknown"):
        return True
    payload = shipping.get("payload", row["shipping_payload"])
    return _has_meaningful_payload_value(
        payload,
        ignored_keys={
            "market",
            "shipping_fee",
            "shipping_type",
            "shipping_payment",
            "shipping_fee_raw",
            "shipping_fee_type_raw",
            "requires_quantity_calculation",
            "sourceFields",
            "source_fields",
        },
    )


def _has_meaningful_payload_value(value: Any, *, ignored_keys: set[str] | None = None) -> bool:
    ignored = ignored_keys or set()
    if isinstance(value, dict):
        return any(
            _has_meaningful_payload_value(child, ignored_keys=ignored)
            for key, child in value.items()
            if str(key) not in ignored
        )
    if isinstance(value, list):
        return any(_has_meaningful_payload_value(child, ignored_keys=ignored) for child in value)
    return _has_value(value)


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
    seller = _seller_row(_object_or_empty(current.get("seller")))
    return {
        "platform": platform,
        "external_product_id": external_id,
        "collected_at": _parse_datetime(collected_at),
        "product_name": _first_text(current, "productName", "name", "title"),
        "product_url": _first_text(current, "productUrl", "affiliateUrl", "url"),
        "image_url": _first_text(current, "imageUrl", "productImage"),
        "backup_image_url": _first_text(current, "backupImageUrl"),
        "status": _text_or_none(current.get("status")),
        "seller": seller,
        "prices_payload": prices,
        "inventory_payload": inventory,
        "options_payload": comparable.get("options") if isinstance(comparable.get("options"), list) else current.get("options", []),
        "shipping_payload": shipping_payload,
        "primary_price": _decimal_or_none(_extract_primary_price(prices, current)),
        "price_rows": _price_rows(platform, prices, current),
        "stock_quantity": _decimal_or_none(_first_available_value(inventory, current, "stockQuantity")),
        "shipping_fee": shipping_rows[0]["fee"],
        "shipping_type": _text_or_none(_first_value(shipping_payload, "type", "feeType", "domeFeeType", "supplyFeeType")),
        "shipping_rows": shipping_rows,
        "is_free_shipping": _bool_or_none(_first_available_value(shipping, current, "isFreeShipping")),
    }


def _seller_row(seller: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _text_or_none(seller.get("id")),
        "nickname": _text_or_none(seller.get("nickname")),
        "type": _text_or_none(seller.get("type")),
        "grade": _text_or_none(seller.get("grade")),
        "excellent_seller": _bool_or_none(seller.get("excellentSeller")),
        "average_satisfaction": _text_or_none(seller.get("averageSatisfaction")),
        "review_count": _decimal_or_none(seller.get("reviewCount")),
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
    if _has_value(prices.get("resaleMinimumPrice")):
        rows.append(
            {
                "market": "resale",
                "price_type": "minimum",
                "amount": _decimal_or_none(prices.get("resaleMinimumPrice")),
            }
        )
    if _has_value(prices.get("resaleRecommendedPrice")):
        rows.append(
            {
                "market": "resale",
                "price_type": "recommended",
                "amount": _decimal_or_none(prices.get("resaleRecommendedPrice")),
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
    return parse_decimal(value)

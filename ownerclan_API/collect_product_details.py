from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Any

from .client import OwnerclanGraphQLError
from .config import OwnerclanConfig, find_project_root, load_config
from .discover_products import make_client
from .logging_config import configure_logging
from .normalization import normalize_item
from .queries import item_query, items_query
from .storage import (
    active_product_keys,
    chunked,
    load_tracked_products,
    merge_product_snapshots,
    save_raw_samples,
    save_failures,
    update_latest_and_history,
)
from .time_utils import now_iso, output_file_stamp


LOGGER = logging.getLogger("ownerclan_API.collect_product_details")


def collect_details(
    project_root: Path,
    config: OwnerclanConfig,
    *,
    product_limit: int | None = None,
    dry_run: bool = False,
    client: Any | None = None,
) -> dict[str, int]:
    tracked = load_tracked_products(config.output.tracked_products_path)
    product_keys = active_product_keys(tracked)
    if product_limit is not None:
        product_keys = product_keys[:product_limit]
    client = client or make_client(project_root, config)

    collected_at = now_iso(config.timezone)
    products: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    fallback_count = 0

    for batch in chunked(product_keys, config.details.batch_size):
        try:
            items = fetch_items_batch(client, batch)
        except Exception as exc:
            LOGGER.error("failed ownerclan detail batch size=%d error=%s", len(batch), exc)
            failures.extend({"productId": key, "error": str(exc)} for key in batch)
            continue
        found = {str(item.get("key")) for item in items if item.get("key") is not None}
        missing = [key for key in batch if key not in found]
        failures.extend({"productId": key, "error": "not returned by items query"} for key in missing)
        products.extend(normalize_item(item, collected_at) for item in items)
        if getattr(client, "last_detail_strategy", None) in {"itemsByKeys", "item"}:
            fallback_count += 1

    unique_products = {str(product["productId"]): product for product in products if product.get("productId")}

    if not dry_run:
        output_dir = config.output.output_dir
        data_dir = output_dir.parent
        file_stamp = output_file_stamp("ownerclan", config.timezone)
        save_raw_samples(
            data_dir / "raw" / f"{file_stamp}_raw.json",
            collected_at,
            unique_products.values(),
            config.output.raw_sample_limit,
        )
        merge_product_snapshots(
            output_dir / f"{file_stamp}_product-snapshots.json",
            collected_at,
            (_without_raw(product) for product in unique_products.values()),
            failures,
        )
        update_latest_and_history(
            latest_path=config.output.state_dir / "latest-products.json",
            history_path=data_dir / "history" / f"{file_stamp}_product-history.json",
            collected_at=collected_at,
            products=(_without_raw(product) for product in unique_products.values()),
        )
        if failures:
            save_failures(data_dir / "summaries" / f"{file_stamp}_failures.json", collected_at, failures)

    return {
        "trackedCount": len(product_keys),
        "successCount": len(unique_products),
        "failureCount": len(failures),
        "fallbackBatchCount": fallback_count,
    }


def _without_raw(product: dict[str, Any]) -> dict[str, Any]:
    result = dict(product)
    result.pop("raw", None)
    return result


def fetch_items_batch(client: Any, keys: list[str]) -> list[dict[str, Any]]:
    if not keys:
        return []
    try:
        data = client.graphql(items_query(keys, "items"))
        client.last_detail_strategy = "items"
        return _list_from_field(data, "items")
    except OwnerclanGraphQLError as exc:
        if not exc.looks_like_unknown_field():
            raise
        if not _unknown_root_field(exc, "items"):
            data = client.graphql(items_query(keys, "items", minimal=True))
            client.last_detail_strategy = "items_minimal"
            return _list_from_field(data, "items")
    try:
        data = client.graphql(items_query(keys, "itemsByKeys"))
        client.last_detail_strategy = "itemsByKeys"
        return _list_from_field(data, "itemsByKeys")
    except OwnerclanGraphQLError as exc:
        if not exc.looks_like_unknown_field():
            raise
        if not _unknown_root_field(exc, "itemsByKeys"):
            data = client.graphql(items_query(keys, "itemsByKeys", minimal=True))
            client.last_detail_strategy = "itemsByKeys_minimal"
            return _list_from_field(data, "itemsByKeys")
    items: list[dict[str, Any]] = []
    client.last_detail_strategy = "item"
    for key in keys:
        try:
            try:
                data = client.graphql(item_query(key))
            except OwnerclanGraphQLError as exc:
                if not exc.looks_like_unknown_field() or _unknown_root_field(exc, "item"):
                    raise
                data = client.graphql(item_query(key, minimal=True))
                client.last_detail_strategy = "item_minimal"
            item = data.get("item")
            if isinstance(item, dict):
                items.append(item)
        except Exception as exc:
            LOGGER.error("failed ownerclan single item key=%s error=%s", key, exc)
    return items


def _list_from_field(data: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = data.get(field)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _unknown_root_field(exc: OwnerclanGraphQLError, field_name: str) -> bool:
    text = str(exc).lower()
    field = field_name.lower()
    return re.search(rf"field\s+\"?{re.escape(field)}\"?\b", text) is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect Ownerclan Seller API product detail snapshots.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit active product keys for a small real API run.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write output files.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    config = load_config(Path(args.config) if args.config else project_root / "ownerclan_API" / "config.yaml", project_root)
    configure_logging(config.output.log_dir)
    result = collect_details(project_root, config, product_limit=args.limit, dry_run=args.dry_run)
    print(result)
    return 1 if result["failureCount"] and not result["successCount"] else 0


if __name__ == "__main__":
    sys.exit(main())

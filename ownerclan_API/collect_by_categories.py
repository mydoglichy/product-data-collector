from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from postgres_storage import save_product_raw_samples_if_enabled, save_product_snapshots_if_enabled

from .categories import load_or_refresh_leaf_categories
from .client import OwnerclanGraphQLError
from .config import OwnerclanConfig, find_project_root, load_config
from .discover_products import make_client
from .logging_config import configure_logging
from .normalization import extract_connection_items, normalize_item
from .queries import all_items_query
from .storage import load_tracked_products, merge_discovered_product, save_tracked_products
from .time_utils import now_iso


LOGGER = logging.getLogger("ownerclan_API.collect_by_categories")


def collect_by_categories(
    project_root: Path,
    config: OwnerclanConfig,
    *,
    category_limit: int | None = None,
    page_limit: int | None = None,
    item_limit: int | None = None,
    refresh_categories: bool = False,
    dry_run: bool = False,
    client: Any | None = None,
) -> dict[str, int]:
    client = client or make_client(project_root, config)
    categories = load_or_refresh_leaf_categories(project_root, config, refresh=refresh_categories, client=client)
    if category_limit is not None:
        categories = categories[:category_limit]

    collected_at = now_iso(config.timezone)
    tracked = load_tracked_products(config.output.tracked_products_path)
    products_by_key: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    category_pages = 0

    for category in categories:
        category_key = str(category.get("key") or "")
        if not category_key:
            continue
        after: str | None = None
        seen_cursors: set[str] = set()
        while True:
            try:
                try:
                    data = client.graphql(
                        all_items_query(first=config.incremental.page_size, category=category_key, after=after)
                    )
                except OwnerclanGraphQLError as exc:
                    if not exc.looks_like_unknown_field() or "allitems" in str(exc).lower():
                        raise
                    data = client.graphql(
                        all_items_query(
                            first=config.incremental.page_size,
                            category=category_key,
                            after=after,
                            minimal=True,
                        )
                    )
                items, page_info = extract_connection_items(data, "allItems")
                category_pages += 1
            except Exception as exc:
                failures.append({"categoryKey": category_key, "error": str(exc)})
                LOGGER.error("failed ownerclan category collection category=%s error=%s", category_key, exc)
                break

            for item in items:
                product_key = str(item.get("key") or "")
                if not product_key:
                    continue
                product = normalize_item(item, collected_at)
                products_by_key[product_key] = product
                merge_discovered_product(tracked, product_key, None, f"category:{category_key}", collected_at)
                if item_limit is not None and len(products_by_key) >= item_limit:
                    break

            if item_limit is not None and len(products_by_key) >= item_limit:
                break
            next_cursor = page_info.get("endCursor")
            if not page_info.get("hasNextPage") or not next_cursor:
                break
            if page_limit is not None and category_pages >= page_limit:
                break
            if str(next_cursor) in seen_cursors or next_cursor == after:
                LOGGER.warning("stopping ownerclan item pagination due to repeated cursor category=%s cursor=%s", category_key, next_cursor)
                break
            seen_cursors.add(str(next_cursor))
            after = str(next_cursor)

        if item_limit is not None and len(products_by_key) >= item_limit:
            break
        if page_limit is not None and category_pages >= page_limit:
            break

    if not dry_run:
        save_tracked_products(config.output.tracked_products_path, tracked)
        save_product_raw_samples_if_enabled(
            project_root=project_root,
            platform="ownerclan",
            collected_at=collected_at,
            products=products_by_key.values(),
            limit=config.output.raw_sample_limit,
            logger=LOGGER,
        )
        save_product_snapshots_if_enabled(
            project_root=project_root,
            platform="ownerclan",
            collected_at=collected_at,
            products=(_without_raw(product) for product in products_by_key.values()),
            logger=LOGGER,
        )

    return {
        "categoryCount": len(categories),
        "pageCount": category_pages,
        "successCount": len(products_by_key),
        "trackedCount": len(tracked),
        "failureCount": len(failures),
    }


def _without_raw(product: dict[str, Any]) -> dict[str, Any]:
    result = dict(product)
    result.pop("raw", None)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect Ownerclan products by cached leaf categories.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--category-limit", type=int, default=None, help="Limit categories for a small real API run.")
    parser.add_argument("--page-limit", type=int, default=None, help="Limit allItems pages for a small real API run.")
    parser.add_argument("--item-limit", type=int, default=None, help="Limit unique items for a small real API run.")
    parser.add_argument("--refresh-categories", action="store_true", help="Refresh the leaf category cache before collecting.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write state/output files.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    config = load_config(Path(args.config) if args.config else project_root / "ownerclan_API" / "config.yaml", project_root)
    configure_logging(config.output.log_dir)
    result = collect_by_categories(
        project_root,
        config,
        category_limit=args.category_limit,
        page_limit=args.page_limit,
        item_limit=args.item_limit,
        refresh_categories=args.refresh_categories,
        dry_run=args.dry_run,
    )
    print(result)
    return 1 if result["failureCount"] and not result["successCount"] else 0


if __name__ == "__main__":
    sys.exit(main())

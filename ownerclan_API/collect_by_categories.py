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
from .storage import clear_state, load_state, save_state
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
    state_path = config.output.state_dir / "category-collection-state.json"
    state = load_state(state_path)
    if isinstance(state.get("runCollectedAt"), str):
        collected_at = str(state["runCollectedAt"])
    resume_category_key = str(state.get("categoryKey") or "") or None
    resume_after = str(state.get("after") or "") or None
    tracked = load_tracked_products(config.output.tracked_products_path)
    failures: list[dict[str, Any]] = []
    category_pages = 0
    success_count = 0

    start_index = _category_start_index(categories, resume_category_key)
    for category_index, category in enumerate(categories[start_index:], start=start_index):
        category_key = str(category.get("key") or "")
        if not category_key:
            continue
        after: str | None = resume_after if resume_category_key == category_key else None
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

            page_products_by_key: dict[str, dict[str, Any]] = {}
            for item in items:
                product_key = str(item.get("key") or "")
                if not product_key:
                    continue
                product = normalize_item(item, collected_at)
                page_products_by_key[product_key] = product
                merge_discovered_product(tracked, product_key, None, f"category:{category_key}", collected_at)
                if item_limit is not None and success_count + len(page_products_by_key) >= item_limit:
                    break

            if not dry_run:
                _save_ownerclan_category_page(
                    project_root=project_root,
                    config=config,
                    collected_at=collected_at,
                    tracked=tracked,
                    products=page_products_by_key,
                )
            success_count += len(page_products_by_key)

            if item_limit is not None and success_count >= item_limit:
                if not dry_run:
                    save_state(
                        state_path,
                        {"runCollectedAt": collected_at, "categoryKey": category_key, "after": after},
                    )
                break
            next_cursor = page_info.get("endCursor")
            if not page_info.get("hasNextPage") or not next_cursor:
                if not dry_run:
                    next_category = _next_category_key(categories, category_index)
                    if next_category:
                        save_state(
                            state_path,
                            {"runCollectedAt": collected_at, "categoryKey": next_category, "after": None},
                        )
                break
            if page_limit is not None and category_pages >= page_limit:
                if not dry_run:
                    save_state(
                        state_path,
                        {"runCollectedAt": collected_at, "categoryKey": category_key, "after": str(next_cursor)},
                    )
                break
            if str(next_cursor) in seen_cursors or next_cursor == after:
                LOGGER.warning("stopping ownerclan item pagination due to repeated cursor category=%s cursor=%s", category_key, next_cursor)
                if not dry_run:
                    save_state(
                        state_path,
                        {"runCollectedAt": collected_at, "categoryKey": category_key, "after": after},
                    )
                break
            seen_cursors.add(str(next_cursor))
            after = str(next_cursor)
            if not dry_run:
                save_state(
                    state_path,
                    {"runCollectedAt": collected_at, "categoryKey": category_key, "after": after},
                )

        resume_category_key = None
        resume_after = None
        if item_limit is not None and success_count >= item_limit:
            break
        if page_limit is not None and category_pages >= page_limit:
            break

    if not dry_run and not failures and item_limit is None and page_limit is None:
        clear_state(state_path)

    return {
        "categoryCount": len(categories),
        "pageCount": category_pages,
        "successCount": success_count,
        "trackedCount": len(tracked),
        "failureCount": len(failures),
    }


def _save_ownerclan_category_page(
    *,
    project_root: Path,
    config: OwnerclanConfig,
    collected_at: str,
    tracked: dict[str, dict[str, Any]],
    products: dict[str, dict[str, Any]],
) -> None:
    save_tracked_products(config.output.tracked_products_path, tracked)
    save_product_raw_samples_if_enabled(
        project_root=project_root,
        platform="ownerclan",
        collected_at=collected_at,
        products=products.values(),
        limit=config.output.raw_sample_limit,
        logger=LOGGER,
    )
    save_product_snapshots_if_enabled(
        project_root=project_root,
        platform="ownerclan",
        collected_at=collected_at,
        products=(_without_raw(product) for product in products.values()),
        logger=LOGGER,
    )


def _category_start_index(categories: list[dict[str, Any]], category_key: str | None) -> int:
    if not category_key:
        return 0
    for index, category in enumerate(categories):
        if str(category.get("key") or "") == category_key:
            return index
    return 0


def _next_category_key(categories: list[dict[str, Any]], index: int) -> str | None:
    if index + 1 >= len(categories):
        return None
    key = categories[index + 1].get("key")
    return str(key) if key not in (None, "") else None


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

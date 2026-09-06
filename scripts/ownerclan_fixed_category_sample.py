from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ownerclan_API.api.queries import all_items_query
from ownerclan_API.config import find_project_root, load_config
from ownerclan_API.persistence.storage import FileLock, atomic_write_json, load_json_object
from ownerclan_API.services.categories import load_or_refresh_leaf_categories
from ownerclan_API.services.logging_config import configure_logging
from ownerclan_API.services.normalization import extract_connection_items, normalize_item
from ownerclan_API.services.time_utils import now_iso
from ownerclan_API.workflows.collect_by_categories import make_client
from ownerclan_API.api.client import OwnerclanGraphQLError
from postgres_storage import save_product_raw_samples_if_enabled, save_product_snapshots_if_enabled


DEFAULT_CATEGORY_FILE = Path("tests/tmp/ownerclan_fixed_categories.json")
DEFAULT_RESULT_FILE = Path("tests/tmp/ownerclan_fixed_category_sample_last_run.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect a fixed Ownerclan leaf-category sample into PostgreSQL."
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--category-count", type=int, default=100)
    parser.add_argument("--items-per-category", type=int, default=100)
    parser.add_argument("--category-file", default=str(DEFAULT_CATEGORY_FILE))
    parser.add_argument("--result-file", default=str(DEFAULT_RESULT_FILE))
    parser.add_argument("--refresh-categories", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.category_count < 1:
        raise ValueError("--category-count must be greater than zero")
    if args.items_per_category < 1 or args.items_per_category > 1000:
        raise ValueError("--items-per-category must be between 1 and 1000")

    project_root = find_project_root(Path.cwd())
    config = load_config(
        Path(args.config) if args.config else project_root / "ownerclan_API" / "config" / "config.yaml",
        project_root,
    )
    configure_logging(config.output.log_dir)

    category_file = _resolve(project_root, args.category_file)
    result_file = _resolve(project_root, args.result_file)
    collected_at = now_iso(config.timezone)

    with FileLock(config.output.log_dir / "fixed-category-sample.lock"):
        client = make_client(project_root, config)
        categories = _load_or_create_fixed_categories(
            project_root=project_root,
            config=config,
            client=client,
            path=category_file,
            count=args.category_count,
            refresh=args.refresh_categories,
            collected_at=collected_at,
        )

        category_results: list[dict[str, Any]] = []
        total_seen = 0
        total_unique_saved = 0
        seen_product_ids: set[str] = set()

        for index, category in enumerate(categories, start=1):
            category_key = str(category.get("key") or "")
            if not category_key:
                continue
            items = _fetch_category_items(client, category_key, first=args.items_per_category)
            products_by_key: dict[str, dict[str, Any]] = {}
            for item in items[: args.items_per_category]:
                product_key = str(item.get("key") or "")
                if not product_key:
                    continue
                products_by_key[product_key] = normalize_item(item, collected_at)

            total_seen += len(products_by_key)
            seen_product_ids.update(products_by_key)
            saved_count = 0
            raw_saved_count = 0
            if not args.dry_run:
                raw_saved_count = save_product_raw_samples_if_enabled(
                    project_root=project_root,
                    platform="ownerclan",
                    collected_at=collected_at,
                    products=products_by_key.values(),
                    limit=config.output.raw_sample_limit,
                )
                saved_count = save_product_snapshots_if_enabled(
                    project_root=project_root,
                    platform="ownerclan",
                    collected_at=collected_at,
                    products=(_without_raw(product) for product in products_by_key.values()),
                )
            total_unique_saved += saved_count
            category_results.append(
                {
                    "index": index,
                    "categoryKey": category_key,
                    "categoryName": category.get("name"),
                    "requestedItemCount": args.items_per_category,
                    "fetchedUniqueItemCount": len(products_by_key),
                    "savedProductCount": saved_count,
                    "savedRawSampleCount": raw_saved_count,
                    "productIds": sorted(products_by_key),
                }
            )
            print(
                f"{index}/{len(categories)} category={category_key} "
                f"fetched={len(products_by_key)} saved={saved_count}"
            )

        result = {
            "source": "ownerclan",
            "collectedAt": collected_at,
            "dryRun": args.dry_run,
            "categoryFile": str(category_file),
            "categoryCount": len(categories),
            "itemsPerCategory": args.items_per_category,
            "fetchedUniqueItemCountIncludingCategoryDuplicates": total_seen,
            "fetchedUniqueProductCount": len(seen_product_ids),
            "savedProductCountIncludingCategoryDuplicates": total_unique_saved,
            "categories": category_results,
        }
        atomic_write_json(result_file, result)
        print(f"wrote result: {result_file}")
        print(
            "summary "
            f"categories={len(categories)} itemsPerCategory={args.items_per_category} "
            f"uniqueProducts={len(seen_product_ids)} saved={total_unique_saved} "
            f"collectedAt={collected_at}"
        )
    return 0


def _resolve(project_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def _load_or_create_fixed_categories(
    *,
    project_root: Path,
    config: Any,
    client: Any,
    path: Path,
    count: int,
    refresh: bool,
    collected_at: str,
) -> list[dict[str, Any]]:
    if path.exists() and not refresh:
        payload = load_json_object(path)
        categories = payload.get("categories")
        if not isinstance(categories, list) or not categories:
            raise ValueError(f"category file has no categories: {path}")
        return [category for category in categories[:count] if isinstance(category, dict)]

    leaves = load_or_refresh_leaf_categories(project_root, config, refresh=refresh, client=client)
    selected = leaves[:count]
    atomic_write_json(
        path,
        {
            "source": "ownerclan",
            "collectedAt": collected_at,
            "selection": "first sorted leaf categories",
            "categoryCount": len(selected),
            "categories": selected,
        },
    )
    return selected


def _fetch_category_items(client: Any, category_key: str, *, first: int) -> list[dict[str, Any]]:
    try:
        data = client.graphql(all_items_query(first=first, category=category_key))
    except OwnerclanGraphQLError as exc:
        if not exc.looks_like_unknown_field() or "allitems" in str(exc).lower():
            raise
        data = client.graphql(all_items_query(first=first, category=category_key, minimal=True))
    items, _page_info = extract_connection_items(data, "allItems")
    return items


def _without_raw(product: dict[str, Any]) -> dict[str, Any]:
    result = dict(product)
    result.pop("raw", None)
    return result


if __name__ == "__main__":
    raise SystemExit(main())

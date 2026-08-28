from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .api_client import DomeggookApiError, DomeggookClient, ListRequest, create_domeggook_client
from .categories import load_or_refresh_categories
from .config import DomeggookConfig, find_project_root, load_api_keys, load_config
from .logging_config import configure_logging
from .parsing import parse_list_items, parse_product_id
from .storage import append_search_ranks, load_tracked_products, merge_discovered_product, save_tracked_products
from .time_utils import now_iso, output_file_stamp


LOGGER = logging.getLogger("domeggook_API.discover_products")


def discover(
    project_root: Path,
    config: DomeggookConfig,
    *,
    keyword_limit: int | None = None,
    dry_run: bool = False,
    client: DomeggookClient | None = None,
) -> dict[str, int]:
    if client is None:
        api_keys = load_api_keys(project_root)
        client = create_domeggook_client(api_keys, config)

    data_dir = project_root / "domeggook_API" / "data"
    categories = load_or_refresh_categories(data_dir / "state" / "categories.json", client, dry_run=dry_run)
    if keyword_limit is not None:
        categories = categories[:keyword_limit]

    tracked_path = data_dir / "state" / "tracked_products.json"
    tracked = load_tracked_products(tracked_path)
    search_rank_records: list[dict[str, object]] = []
    discovered = 0
    new_products = 0
    failures = 0

    for category in categories:
        for market in config.discovery.markets:
            for reason, sort_code in config.discovery.sorts.items():
                collected_at = now_iso(config.timezone)
                try:
                    payload = client.get_item_list(
                        ListRequest(
                            market=market,
                            sort=sort_code,
                            size=config.discovery.items_per_keyword,
                            category_code=category.code,
                        )
                    )
                    items = parse_list_items(payload)
                except DomeggookApiError as exc:
                    failures += 1
                    LOGGER.error(
                        "failed list category=%s category_name=%r market=%s sort=%s error=%s",
                        category.code,
                        category.name,
                        market,
                        sort_code,
                        exc,
                    )
                    continue

                for rank, item in enumerate(items, start=1):
                    product_id = parse_product_id(item)
                    if not product_id:
                        LOGGER.warning(
                            "list item missing product id category=%s category_name=%r market=%s sort=%s rank=%d",
                            category.code,
                            category.name,
                            market,
                            sort_code,
                            rank,
                        )
                        continue
                    discovered += 1
                    if merge_discovered_product(tracked, product_id, category.name, market, reason, collected_at):
                        new_products += 1
                    search_rank_records.append(
                        {
                            "collectedAt": collected_at,
                            "keyword": category.name,
                            "categoryCode": category.code,
                            "categoryName": category.name,
                            "categoryPath": list(category.path),
                            "market": market,
                            "sort": sort_code,
                            "reason": reason,
                            "productId": product_id,
                            "rank": rank,
                        }
                    )

    if not dry_run:
        save_tracked_products(tracked_path, tracked)
        append_search_ranks(
            data_dir / "processed" / f"{output_file_stamp('domeggook', config.timezone)}_search-ranks.json",
            search_rank_records,
        )

    return {
        "categoryCount": len(categories),
        "discoveredCount": discovered,
        "newProductCount": new_products,
        "trackedCount": len(tracked),
        "failureCount": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover Domeggook/Domeme product ids from category searches.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit categories for a small real API run.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write data files.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    configure_logging(project_root / "domeggook_API" / "data" / "logs")
    config = load_config(Path(args.config) if args.config else project_root / "domeggook_API" / "config.yaml")
    result = discover(project_root, config, keyword_limit=args.limit, dry_run=args.dry_run)
    print(result)
    return 1 if result["failureCount"] and not result["discoveredCount"] else 0


if __name__ == "__main__":
    sys.exit(main())

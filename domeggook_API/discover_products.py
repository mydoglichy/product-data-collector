from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .api_client import DomeggookApiError, DomeggookClient, ListRequest
from .config import DomeggookConfig, find_project_root, load_api_key, load_config, load_keywords
from .logging_config import configure_logging
from .parsing import parse_list_items, parse_product_id
from .rate_limiter import RateLimiter
from .storage import append_search_ranks, load_tracked_products, merge_discovered_product, save_tracked_products
from .time_utils import now_iso, today_string


LOGGER = logging.getLogger("domeggook_API.discover_products")


def discover(
    project_root: Path,
    config: DomeggookConfig,
    *,
    keyword_limit: int | None = None,
    dry_run: bool = False,
    client: DomeggookClient | None = None,
) -> dict[str, int]:
    keywords = load_keywords(project_root / "domeggook_API" / "keywords.txt")
    if keyword_limit is not None:
        keywords = keywords[:keyword_limit]

    if client is None:
        api_key = load_api_key(project_root)
        client = DomeggookClient(
            api_key=api_key,
            rate_limiter=RateLimiter(config.request.max_requests_per_minute),
            timeout_seconds=config.request.timeout_seconds,
            max_retries=config.request.max_retries,
        )

    tracked_path = project_root / "domeggook_API" / "tracked_products.json"
    tracked = load_tracked_products(tracked_path)
    search_rank_records: list[dict[str, object]] = []
    discovered = 0
    new_products = 0
    failures = 0

    for keyword in keywords:
        for market in config.discovery.markets:
            for reason, sort_code in config.discovery.sorts.items():
                collected_at = now_iso(config.timezone)
                try:
                    payload = client.get_item_list(
                        ListRequest(
                            keyword=keyword,
                            market=market,
                            sort=sort_code,
                            size=config.discovery.items_per_keyword,
                        )
                    )
                    items = parse_list_items(payload)
                except DomeggookApiError as exc:
                    failures += 1
                    LOGGER.error("failed list keyword=%r market=%s sort=%s error=%s", keyword, market, sort_code, exc)
                    continue

                for rank, item in enumerate(items, start=1):
                    product_id = parse_product_id(item)
                    if not product_id:
                        LOGGER.warning("list item missing product id keyword=%r market=%s sort=%s rank=%d", keyword, market, sort_code, rank)
                        continue
                    discovered += 1
                    if merge_discovered_product(tracked, product_id, keyword, market, reason, collected_at):
                        new_products += 1
                    search_rank_records.append(
                        {
                            "collectedAt": collected_at,
                            "keyword": keyword,
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
            project_root / "domeggook_API" / "output" / f"search-ranks-{today_string(config.timezone)}.json",
            search_rank_records,
        )

    return {
        "keywordCount": len(keywords),
        "discoveredCount": discovered,
        "newProductCount": new_products,
        "trackedCount": len(tracked),
        "failureCount": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover Domeggook/Domeme product ids from keyword searches.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit keywords for a small real API run.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write tracked/output files.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    configure_logging(project_root / "domeggook_API" / "logs")
    config = load_config(Path(args.config) if args.config else project_root / "domeggook_API" / "config.yaml")
    result = discover(project_root, config, keyword_limit=args.limit, dry_run=args.dry_run)
    print(result)
    return 1 if result["failureCount"] and not result["discoveredCount"] else 0


if __name__ == "__main__":
    sys.exit(main())

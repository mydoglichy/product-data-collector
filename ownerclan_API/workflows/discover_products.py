from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from ..api.auth import JwtProvider
from ..api.client import OwnerclanClient, OwnerclanGraphQLError
from ..config import OwnerclanConfig, find_project_root, load_config, load_credentials, load_keywords
from ..services.logging_config import configure_logging
from ..services.normalization import extract_connection_items
from ..api.queries import all_items_query
from ..api.rate_limiter import RateLimiter
from ..services.time_utils import now_iso
from postgres_storage import save_discovered_product_ids_if_enabled


LOGGER = logging.getLogger("ownerclan_API.discover_products")


def discover(
    project_root: Path,
    config: OwnerclanConfig,
    *,
    keyword_limit: int | None = None,
    dry_run: bool = False,
    client: Any | None = None,
) -> dict[str, int]:
    keywords = load_keywords(config.discovery.keyword_file)
    if keyword_limit is not None:
        keywords = keywords[:keyword_limit]
    client = client or make_client(project_root, config)

    discovered = 0
    new_products = 0
    failures = 0
    discovery_target_records: list[dict[str, Any]] = []
    seen_product_keys: set[str] = set()

    searches = [
        ("default", None, config.discovery.top_limit_per_keyword),
        ("registerDateDesc", "registerDateDesc", config.discovery.new_limit_per_keyword),
    ]
    for keyword in keywords:
        for stored_sort_by, request_sort_by, limit in searches:
            collected_at = now_iso(config.timezone)
            try:
                query = all_items_query(search=keyword, sort_by=request_sort_by, first=limit)
                try:
                    data = client.graphql(query)
                except OwnerclanGraphQLError as exc:
                    if not exc.looks_like_unknown_field() or _unknown_all_items_root(exc):
                        raise
                    data = client.graphql(all_items_query(search=keyword, sort_by=request_sort_by, first=limit, minimal=True))
                items, _page_info = extract_connection_items(data, "allItems")
            except Exception as exc:
                failures += 1
                LOGGER.error("failed ownerclan discovery keyword=%r sort_by=%s error=%s", keyword, stored_sort_by, exc)
                continue

            for rank, item in enumerate(items[:limit], start=1):
                product_key = item.get("key")
                if product_key in (None, ""):
                    LOGGER.warning("ownerclan list item missing key keyword=%r sort_by=%s rank=%d", keyword, stored_sort_by, rank)
                    continue
                product_key = str(product_key)
                discovered += 1
                if product_key not in seen_product_keys:
                    seen_product_keys.add(product_key)
                    new_products += 1
                discovery_target_records.append(
                    {
                        "collectedAt": collected_at,
                        "keyword": keyword,
                        "reason": stored_sort_by,
                        "productId": product_key,
                    }
                )

    if not dry_run:
        save_discovered_product_ids_if_enabled(
            project_root=project_root,
            platform="ownerclan",
            records=discovery_target_records,
            logger=LOGGER,
        )

    return {
        "keywordCount": len(keywords),
        "discoveredCount": discovered,
        "newProductCount": new_products,
        "trackedCount": 0,
        "failureCount": failures,
    }


def make_client(project_root: Path, config: OwnerclanConfig, *, rate_limiter: RateLimiter | None = None) -> OwnerclanClient:
    username, password = load_credentials(project_root)
    session = None
    provider = JwtProvider(username, password, config.environment, config.request.timeout_seconds, session=session)
    return OwnerclanClient(
        provider,
        config.environment,
        rate_limiter or RateLimiter(config.request.interval_seconds),
        config.request.timeout_seconds,
        config.request.max_retries,
        config.request.retry_after_max_seconds,
        session=session,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover Ownerclan Seller API product keys from keyword searches.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit keywords for a small real API run.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write tracked/output files.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    config = load_config(
        Path(args.config) if args.config else project_root / "ownerclan_API" / "config" / "config.yaml",
        project_root,
    )
    configure_logging(config.output.log_dir)
    result = discover(project_root, config, keyword_limit=args.limit, dry_run=args.dry_run)
    print(result)
    return 1 if result["failureCount"] and not result["discoveredCount"] else 0


def _unknown_all_items_root(exc: OwnerclanGraphQLError) -> bool:
    return "allitems" in str(exc).lower()


if __name__ == "__main__":
    sys.exit(main())

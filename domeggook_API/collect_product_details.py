from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .api_client import DomeggookApiError, DomeggookClient
from .config import DomeggookConfig, find_project_root, load_api_key, load_config
from .logging_config import configure_logging
from .parsing import parse_detail_products
from .rate_limiter import RateLimiter
from .storage import active_product_ids, chunked, load_tracked_products, merge_product_snapshots
from .time_utils import now_iso, today_string


LOGGER = logging.getLogger("domeggook_API.collect_product_details")


def collect_details(
    project_root: Path,
    config: DomeggookConfig,
    *,
    product_limit: int | None = None,
    dry_run: bool = False,
    client: DomeggookClient | None = None,
) -> dict[str, int]:
    tracked = load_tracked_products(project_root / "domeggook_API" / "tracked_products.json")
    product_ids = active_product_ids(tracked)
    if product_limit is not None:
        product_ids = product_ids[:product_limit]

    if client is None:
        api_key = load_api_key(project_root)
        client = DomeggookClient(
            api_key=api_key,
            rate_limiter=RateLimiter(config.request.max_requests_per_minute),
            timeout_seconds=config.request.timeout_seconds,
            max_retries=config.request.max_retries,
        )

    collected_at = now_iso(config.timezone)
    products: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []

    for batch in chunked(product_ids, config.details.batch_size):
        try:
            payload = client.get_item_view(batch)
            parsed_products, parsed_failures = parse_detail_products(payload, collected_at)
            products.extend(parsed_products)
            failures.extend(parsed_failures)
        except DomeggookApiError as exc:
            LOGGER.error("failed detail batch product_ids=%s error=%s", ",".join(batch), exc)
            failures.extend({"productId": product_id, "error": str(exc)} for product_id in batch)
        except Exception as exc:
            LOGGER.exception("unexpected detail batch failure product_ids=%s error=%s", ",".join(batch), exc)
            failures.extend({"productId": product_id, "error": str(exc)} for product_id in batch)

    unique_products: dict[str, dict[str, object]] = {}
    for product in products:
        product_id = product.get("productId")
        if product_id is not None:
            unique_products[str(product_id)] = product

    if not dry_run:
        merge_product_snapshots(
            project_root / "domeggook_API" / "output" / f"product-snapshots-{today_string(config.timezone)}.json",
            collected_at,
            unique_products.values(),
            failures,
        )

    return {
        "trackedCount": len(product_ids),
        "successCount": len(unique_products),
        "failureCount": len(failures),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect Domeggook/Domeme product detail snapshots.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit active product ids for a small real API run.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write output files.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    configure_logging(project_root / "domeggook_API" / "logs")
    config = load_config(Path(args.config) if args.config else project_root / "domeggook_API" / "config.yaml")
    result = collect_details(project_root, config, product_limit=args.limit, dry_run=args.dry_run)
    print(result)
    return 1 if result["failureCount"] and not result["successCount"] else 0


if __name__ == "__main__":
    sys.exit(main())

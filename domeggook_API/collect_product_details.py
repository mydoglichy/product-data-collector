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
from product_history import append_collection_run

from .storage import (
    active_product_ids,
    chunked,
    load_tracked_products,
    merge_product_snapshots,
    save_failures,
    save_raw_samples,
    update_latest_and_history,
)
from .time_utils import now_iso, output_file_stamp


LOGGER = logging.getLogger("domeggook_API.collect_product_details")


def collect_details(
    project_root: Path,
    config: DomeggookConfig,
    *,
    product_limit: int | None = None,
    dry_run: bool = False,
    client: DomeggookClient | None = None,
) -> dict[str, int]:
    data_dir = project_root / "domeggook_API" / "data"
    tracked = load_tracked_products(data_dir / "state" / "tracked_products.json")
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
    started_at = collected_at
    products: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    raw_remaining = config.details.raw_sample_limit

    for batch in chunked(product_ids, config.details.batch_size):
        try:
            payload = client.get_item_view(batch)
            parsed_products, parsed_failures = parse_detail_products(payload, collected_at, raw_limit=raw_remaining)
            products.extend(parsed_products)
            failures.extend(parsed_failures)
            raw_remaining = max(raw_remaining - len(parsed_products), 0)
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
        file_stamp = output_file_stamp("domeggook", config.timezone)
        save_raw_samples(
            data_dir / "raw" / f"{file_stamp}_raw.json",
            collected_at,
            unique_products.values(),
            config.details.raw_sample_limit,
        )
        merge_product_snapshots(
            data_dir / "processed" / f"{file_stamp}_product-snapshots.json",
            collected_at,
            (_without_raw(product) for product in unique_products.values()),
            failures,
        )
        change_stats = update_latest_and_history(
            latest_path=data_dir / "state" / "latest-products.json",
            history_path=data_dir / "history" / f"{file_stamp}_product-history.json",
            collected_at=collected_at,
            products=(_without_raw(product) for product in unique_products.values()),
        )
        if failures:
            save_failures(data_dir / "summaries" / f"{file_stamp}_failures.json", collected_at, failures)
        append_collection_run(
            data_dir / "state" / "collection-runs.json",
            platform="domeggook",
            started_at=started_at,
            ended_at=now_iso(config.timezone),
            success=not failures,
            queried_product_count=len(product_ids),
            new_product_count=change_stats["newProductCount"],
            changed_product_count=change_stats["changedProductCount"],
            unchanged_product_count=change_stats["unchangedProductCount"],
            failed_product_count=len(failures),
        )

    return {
        "trackedCount": len(product_ids),
        "successCount": len(unique_products),
        "failureCount": len(failures),
    }


def _without_raw(product: dict[str, object]) -> dict[str, object]:
    result = dict(product)
    result.pop("raw", None)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect Domeggook/Domeme product detail snapshots.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit active product ids for a small real API run.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write data files.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    configure_logging(project_root / "domeggook_API" / "data" / "logs")
    config = load_config(Path(args.config) if args.config else project_root / "domeggook_API" / "config.yaml")
    result = collect_details(project_root, config, product_limit=args.limit, dry_run=args.dry_run)
    print(result)
    return 1 if result["failureCount"] and not result["successCount"] else 0


if __name__ == "__main__":
    sys.exit(main())

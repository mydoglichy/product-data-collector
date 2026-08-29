from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .api_client import DomeggookApiError, DomeggookClient, create_domeggook_client
from .config import DomeggookConfig, find_project_root, load_api_keys, load_config
from .logging_config import configure_logging
from .parsing import parse_detail_products
from postgres_storage import save_product_raw_samples_if_enabled, save_product_snapshots_if_enabled

from .storage import (
    active_product_ids,
    chunked,
    load_tracked_products,
)
from .time_utils import now_iso


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
        api_keys = load_api_keys(project_root)
        client = create_domeggook_client(api_keys, config)

    collected_at = now_iso(config.timezone)
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
        save_product_raw_samples_if_enabled(
            project_root=project_root,
            platform="domeggook",
            collected_at=collected_at,
            products=unique_products.values(),
            limit=config.details.raw_sample_limit,
            logger=LOGGER,
        )
        save_product_snapshots_if_enabled(
            project_root=project_root,
            platform="domeggook",
            collected_at=collected_at,
            products=(_without_raw(product) for product in unique_products.values()),
            logger=LOGGER,
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

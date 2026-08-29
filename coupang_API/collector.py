from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from .checkpoint import Checkpoint
from .client import CoupangApiError, CoupangPartnersClient, SearchRequest
from .config import CollectorConfig, load_config, load_credentials, load_keywords
from .models import parse_product_records
from .rate_limiter import RateLimiter
from .storage import JsonlWriter, prune_raw_samples, save_raw_response, save_summary
from .time_utils import output_file_stamp
from postgres_storage import save_product_snapshots_if_enabled
from product_history import append_collection_run, upsert_product_changes


LOGGER = logging.getLogger("coupang_API")


def collect_once(project_root: Path, config: CollectorConfig) -> int:
    access_key, secret_key = load_credentials(project_root)
    client = CoupangPartnersClient(
        access_key=access_key,
        secret_key=secret_key,
        rate_limiter=RateLimiter(max_calls=config.requests_per_minute, period_seconds=60.0),
    )
    keywords = load_keywords(project_root / "coupang_API" / "keywords.txt")
    started_at = datetime.now(timezone.utc)
    run_stamp = output_file_stamp("coupang", dt=started_at)
    processed_path = project_root / "coupang_API" / "data" / "processed" / f"{run_stamp}_products.jsonl"
    checkpoint = Checkpoint.load(project_root / "coupang_API" / "data" / "state" / "product_search_checkpoint.json")
    success_keywords: list[str] = []
    failure_keywords: list[str] = []
    skipped_keywords = [keyword for keyword in keywords if checkpoint.is_completed(keyword)]
    total_products = 0
    duplicate_products = 0
    raw_saved_count = 0
    collected_products: dict[str, dict[str, object]] = {}

    LOGGER.info(
        "starting collection total=%d skipped_completed=%d pending=%d requests_per_minute=%d",
        len(keywords),
        len(skipped_keywords),
        len(keywords) - len(skipped_keywords),
        config.requests_per_minute,
    )

    with JsonlWriter(processed_path) as writer:
        for keyword in keywords:
            if checkpoint.is_completed(keyword):
                continue
            request = SearchRequest(
                keyword=keyword,
                limit=10,
                image_size=config.image_size,
                srp_link_only=False,
                sub_id=config.sub_id,
            )
            collected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            try:
                payload = client.search_products(request)
                if raw_saved_count < config.raw_sample_limit:
                    save_raw_response(
                        project_root / "coupang_API" / "data" / "raw",
                        run_stamp,
                        keyword,
                        payload,
                    )
                    raw_saved_count += 1
                records = parse_product_records(
                    payload,
                    requested_keyword=keyword,
                    collected_at=collected_at,
                )
                written = writer.write_many_dedup(records)
                duplicates = len(records) - written
                total_products += written
                duplicate_products += duplicates
                for record in records:
                    product_id = record.get("productId")
                    if product_id not in (None, ""):
                        collected_products[str(product_id)] = record
                checkpoint.mark_completed(keyword)
                success_keywords.append(keyword)
                LOGGER.info("success keyword=%r products=%d duplicates=%d", keyword, written, duplicates)
            except CoupangApiError as exc:
                failure_keywords.append(keyword)
                LOGGER.error("failed keyword=%r error=%s", keyword, exc)
            except Exception as exc:
                failure_keywords.append(keyword)
                LOGGER.exception("unexpected failure keyword=%r error=%s", keyword, exc)

    ended_at = datetime.now(timezone.utc)
    all_completed = len(checkpoint.completed_keywords.intersection(keywords)) == len(keywords)
    if all_completed and not failure_keywords:
        checkpoint.clear()
    removed_raw_files = prune_raw_samples(project_root / "coupang_API" / "data" / "raw", config.raw_sample_limit)
    data_dir = project_root / "coupang_API" / "data"
    change_stats = upsert_product_changes(
        platform="coupang",
        current_path=data_dir / "state" / "latest-products.json",
        history_path=data_dir / "history" / f"{run_stamp}_product-history.json",
        collected_at=ended_at.isoformat().replace("+00:00", "Z"),
        products=collected_products.values(),
    )
    save_product_snapshots_if_enabled(
        project_root=project_root,
        platform="coupang",
        collected_at=ended_at.isoformat().replace("+00:00", "Z"),
        products=collected_products.values(),
        logger=LOGGER,
    )
    append_collection_run(
        data_dir / "state" / "collection-runs.json",
        platform="coupang",
        started_at=started_at.isoformat().replace("+00:00", "Z"),
        ended_at=ended_at.isoformat().replace("+00:00", "Z"),
        success=not failure_keywords,
        queried_product_count=len(collected_products) + len(failure_keywords),
        new_product_count=change_stats["newProductCount"],
        changed_product_count=change_stats["changedProductCount"],
        unchanged_product_count=change_stats["unchangedProductCount"],
        failed_product_count=len(failure_keywords),
        extra={"successKeywords": success_keywords, "failureKeywords": failure_keywords},
    )

    summary = {
        "runStartedAt": started_at.isoformat().replace("+00:00", "Z"),
        "runEndedAt": ended_at.isoformat().replace("+00:00", "Z"),
        "totalKeywords": len(keywords),
        "skippedCompletedKeywords": len(skipped_keywords),
        "processedKeywords": len(success_keywords) + len(failure_keywords),
        "successCount": len(success_keywords),
        "failureCount": len(failure_keywords),
        "collectedProductCount": total_products,
        "duplicateProductCount": duplicate_products,
        "newProductCount": change_stats["newProductCount"],
        "changedProductCount": change_stats["changedProductCount"],
        "unchangedProductCount": change_stats["unchangedProductCount"],
        "rawSampleLimit": config.raw_sample_limit,
        "rawSavedCount": raw_saved_count,
        "removedRawFileCount": removed_raw_files,
        "successKeywords": success_keywords,
        "failureKeywords": failure_keywords,
        "source": "coupang_partners_product_search",
    }
    save_summary(project_root / "coupang_API" / "data" / "summaries", run_stamp, summary)
    LOGGER.info(
        "finished collection total=%d processed=%d success=%d failure=%d products=%d duplicates=%d",
        len(keywords),
        summary["processedKeywords"],
        len(success_keywords),
        len(failure_keywords),
        total_products,
        duplicate_products,
    )
    if success_keywords:
        LOGGER.info("success keywords=%s", ", ".join(success_keywords))
    if failure_keywords:
        LOGGER.info("failed keywords=%s", ", ".join(failure_keywords))

    return 1 if failure_keywords and not success_keywords else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect Coupang Partners keyword product search data.")
    parser.add_argument("--config", default=None, help="Path to config.yaml. Defaults to coupang_API/config.yaml.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    project_root = find_project_root(Path.cwd())
    config_path = Path(args.config) if args.config else project_root / "coupang_API" / "config.yaml"
    config = load_config(config_path)
    return collect_once(project_root, config)


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    candidates = [current, *current.parents]
    for candidate in candidates:
        if (candidate / "coupang_API").is_dir() and (
            (candidate / ".env").exists()
            or (candidate / ".env.example").exists()
            or (candidate / "requirements.txt").exists()
        ):
            return candidate
    for candidate in candidates:
        if (candidate / "coupang_API").is_dir():
            return candidate
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    sys.exit(main())

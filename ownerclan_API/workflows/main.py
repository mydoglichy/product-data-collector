from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .collect_by_categories import collect_by_categories
from ..config import find_project_root, load_config
from ..services.logging_config import configure_logging
from ..persistence.storage import FileLock
from .sync_incremental import sync_incremental


LOGGER = logging.getLogger("ownerclan_API.workflows.main")
EMPTY_INCREMENTAL_RESULT = {
    "pageCount": 0,
    "successCount": 0,
    "historyCount": 0,
    "failureCount": 0,
    "rateLimitFailureCount": 0,
    "stateUpdated": 0,
}


def run(
    project_root: Path,
    config_path: Path,
    *,
    limit: int | None = None,
    refresh_categories: bool = False,
    dry_run: bool = False,
    rate_limit_retry_seconds: int = 300,
) -> dict[str, dict[str, int]]:
    config = load_config(config_path, project_root)
    with FileLock(config.output.log_dir / "collector.lock"):
        while True:
            category_collection = collect_by_categories(
                project_root,
                config,
                category_limit=limit,
                page_limit=limit,
                item_limit=limit,
                refresh_categories=refresh_categories,
                dry_run=dry_run,
            )
            if _should_retry_after_rate_limit(category_collection, rate_limit_retry_seconds, dry_run):
                _sleep_before_retry("categoryCollection", rate_limit_retry_seconds)
                refresh_categories = False
                continue
            if category_collection["failureCount"]:
                return {
                    "categoryCollection": category_collection,
                    "incremental": dict(EMPTY_INCREMENTAL_RESULT),
                }

            incremental = sync_incremental(project_root, config, page_limit=limit, item_limit=limit, dry_run=dry_run)
            if _should_retry_after_rate_limit(incremental, rate_limit_retry_seconds, dry_run):
                _sleep_before_retry("incremental", rate_limit_retry_seconds)
                refresh_categories = False
                continue

            return {"categoryCollection": category_collection, "incremental": incremental}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Ownerclan category collection and incremental sync.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit categories, collected items, and incremental pages/items for a small real API run.")
    parser.add_argument("--refresh-categories", action="store_true", help="Refresh the leaf category cache before collecting.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write data files.")
    parser.add_argument(
        "--rate-limit-retry-seconds",
        type=int,
        default=300,
        help="Wait this many seconds and automatically resume when Ownerclan returns a 429/rate-limit failure. Use 0 to disable.",
    )
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    config_path = Path(args.config) if args.config else project_root / "ownerclan_API" / "config" / "config.yaml"
    config = load_config(config_path, project_root)
    configure_logging(config.output.log_dir)
    result = run(
        project_root,
        config_path,
        limit=args.limit,
        refresh_categories=args.refresh_categories,
        dry_run=args.dry_run,
        rate_limit_retry_seconds=max(args.rate_limit_retry_seconds, 0),
    )
    print("Ownerclan collection summary")
    print(f"categoryCollection={result['categoryCollection']}")
    print(f"incremental={result['incremental']}")
    return 1 if any(stage["failureCount"] for stage in result.values()) else 0


def _should_retry_after_rate_limit(stage_result: dict[str, int], retry_seconds: int, dry_run: bool) -> bool:
    return not dry_run and retry_seconds > 0 and int(stage_result.get("rateLimitFailureCount") or 0) > 0


def _sleep_before_retry(stage: str, seconds: int) -> None:
    LOGGER.warning(
        "ownerclan_rate_limit_restart_wait stage=%s seconds=%d message=rate_limit_failure_saved_state_then_resume",
        stage,
        seconds,
    )
    time.sleep(seconds)


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from ..api.client import create_domeggook_client
from .collect_product_details import collect_details
from ..config import find_project_root, load_api_keys, load_config
from .discover_products import discover
from .run_budget import RunBudget
from ..services.logging_config import configure_logging
from ..persistence.storage import FileLock


LOGGER = logging.getLogger("domeggook_API")


def run(
    project_root: Path,
    config_path: Path,
    *,
    limit: int | None = None,
    page_limit: int | None = None,
    max_runtime_seconds: float | None = None,
    max_api_calls: int | None = None,
    mode: str = "full",
    recent_pages_per_position: int = 1,
    dry_run: bool = False,
) -> dict[str, dict[str, int]]:
    config = load_config(config_path)
    api_keys = load_api_keys(project_root)
    client = create_domeggook_client(api_keys, config)
    deadline_monotonic = None
    if max_runtime_seconds is not None and max_runtime_seconds > 0:
        deadline_monotonic = time.monotonic() + max_runtime_seconds
    run_budget = RunBudget(max_api_calls if max_api_calls is not None else config.request.max_requests_per_day)
    data_dir = project_root / "domeggook_API" / "data"
    discovery_state_path = data_dir / "state" / "discovery-state.json"
    detail_state_path = data_dir / "state" / "detail-collection-state.json"
    with FileLock(project_root / "domeggook_API" / "data" / "logs" / "collector.lock"):
        if mode == "daily":
            details = collect_details(
                project_root,
                config,
                product_limit=limit,
                deadline_monotonic=deadline_monotonic,
                run_budget=run_budget,
                dry_run=dry_run,
                client=client,
            )
            if (
                int(details.get("failureCount") or 0)
                or int(details.get("runtimeLimitReached") or 0)
                or int(details.get("dailyRequestLimitReached") or 0)
                or not run_budget.can_call()
            ):
                recent_discovery = _empty_recent_discovery("skipped_until_detail_collection_finishes")
            else:
                recent_discovery = discover(
                    project_root,
                    config,
                    allowed_reasons={"recent"},
                    max_pages_per_position=recent_pages_per_position,
                    state_filename="recent-discovery-state.json",
                    deadline_monotonic=deadline_monotonic,
                    run_budget=run_budget,
                    dry_run=dry_run,
                    client=client,
                )
            return {"details": details, "recentDiscovery": recent_discovery}

        if detail_state_path.exists() and not discovery_state_path.exists() and limit is None and page_limit is None:
            discovery = {
                "categoryCount": 0,
                "pageCount": 0,
                "discoveredCount": 0,
                "newProductCount": 0,
                "trackedCount": 0,
                "failureCount": 0,
                "runtimeLimitReached": 0,
                "dailyRequestLimitReached": 0,
                "skippedBecauseDetailResume": 1,
            }
        else:
            discovery = discover(
                project_root,
                config,
                keyword_limit=limit,
                page_limit=page_limit,
                deadline_monotonic=deadline_monotonic,
                run_budget=run_budget,
                dry_run=dry_run,
                client=client,
            )
        if int(discovery.get("runtimeLimitReached") or 0) or int(discovery.get("dailyRequestLimitReached") or 0):
            details = {
                "trackedCount": 0,
                "successCount": 0,
                "failureCount": 0,
                "runtimeLimitReached": int(discovery.get("runtimeLimitReached") or 0),
                "dailyRequestLimitReached": int(discovery.get("dailyRequestLimitReached") or 0),
            }
        else:
            details = collect_details(
                project_root,
                config,
                product_limit=limit,
                deadline_monotonic=deadline_monotonic,
                run_budget=run_budget,
                dry_run=dry_run,
                client=client,
            )
    return {"discovery": discovery, "details": details}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Domeggook/Domeme discovery and daily detail snapshot collection.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit keywords and active product ids for a small real API run.")
    parser.add_argument("--page-limit", type=int, default=None, help="Limit discovery pages for a small real API run.")
    parser.add_argument("--max-runtime-hours", type=float, default=None, help="Stop cleanly after this many hours and resume next run.")
    parser.add_argument("--max-api-calls", type=int, default=None, help="Stop cleanly after this many Domeggook API calls in this run.")
    parser.add_argument("--mode", choices=("full", "daily"), default="full", help="Use daily to collect known product details first, then refresh recent product ids with leftover calls.")
    parser.add_argument("--recent-pages-per-position", type=int, default=1, help="Recent discovery pages per category/market position in daily mode.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write data files.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    configure_logging(project_root / "domeggook_API" / "data" / "logs")
    config_path = Path(args.config) if args.config else project_root / "domeggook_API" / "config" / "config.yaml"
    max_runtime_seconds = args.max_runtime_hours * 3600 if args.max_runtime_hours is not None else None
    result = run(
        project_root,
        config_path,
        limit=args.limit,
        page_limit=args.page_limit,
        max_runtime_seconds=max_runtime_seconds,
        max_api_calls=args.max_api_calls,
        mode=args.mode,
        recent_pages_per_position=max(args.recent_pages_per_position, 1),
        dry_run=args.dry_run,
    )
    print("Domeggook collection summary")
    print(f"details={result['details']}")
    if "discovery" in result:
        print(f"discovery={result['discovery']}")
    if "recentDiscovery" in result:
        print(f"recentDiscovery={result['recentDiscovery']}")
    return 1 if any(stage["failureCount"] for stage in result.values()) else 0


def _empty_recent_discovery(reason: str) -> dict[str, int | str]:
    return {
        "categoryCount": 0,
        "pageCount": 0,
        "discoveredCount": 0,
        "newProductCount": 0,
        "insertedTargetCount": 0,
        "trackedCount": 0,
        "failureCount": 0,
        "runtimeLimitReached": 0,
        "dailyRequestLimitReached": 0,
        "skipReason": reason,
    }


if __name__ == "__main__":
    sys.exit(main())

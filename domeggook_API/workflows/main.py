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
    dry_run: bool = False,
) -> dict[str, dict[str, int]]:
    config = load_config(config_path)
    api_keys = load_api_keys(project_root)
    client = create_domeggook_client(api_keys, config)
    deadline_monotonic = None
    if max_runtime_seconds is not None and max_runtime_seconds > 0:
        deadline_monotonic = time.monotonic() + max_runtime_seconds
    with FileLock(project_root / "domeggook_API" / "data" / "logs" / "collector.lock"):
        discovery = discover(
            project_root,
            config,
            keyword_limit=limit,
            page_limit=page_limit,
            deadline_monotonic=deadline_monotonic,
            dry_run=dry_run,
            client=client,
        )
        if int(discovery.get("runtimeLimitReached") or 0):
            details = {"trackedCount": 0, "successCount": 0, "failureCount": 0, "runtimeLimitReached": 1}
        else:
            details = collect_details(
                project_root,
                config,
                product_limit=limit,
                deadline_monotonic=deadline_monotonic,
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
        dry_run=args.dry_run,
    )
    print("Domeggook collection summary")
    print(f"discovery={result['discovery']}")
    print(f"details={result['details']}")
    return 1 if result["discovery"]["failureCount"] or result["details"]["failureCount"] else 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .collect_by_categories import collect_by_categories
from .config import find_project_root, load_config
from .logging_config import configure_logging
from .storage import FileLock
from .sync_incremental import sync_incremental


def run(
    project_root: Path,
    config_path: Path,
    *,
    limit: int | None = None,
    refresh_categories: bool = False,
    dry_run: bool = False,
) -> dict[str, dict[str, int]]:
    config = load_config(config_path, project_root)
    with FileLock(config.output.log_dir / "collector.lock"):
        category_collection = collect_by_categories(
            project_root,
            config,
            category_limit=limit,
            page_limit=limit,
            item_limit=limit,
            refresh_categories=refresh_categories,
            dry_run=dry_run,
        )
        incremental = sync_incremental(project_root, config, page_limit=limit, item_limit=limit, dry_run=dry_run)
    return {"categoryCollection": category_collection, "incremental": incremental}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Ownerclan category collection and incremental sync.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit categories, collected items, and incremental pages/items for a small real API run.")
    parser.add_argument("--refresh-categories", action="store_true", help="Refresh the leaf category cache before collecting.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write data files.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    config_path = Path(args.config) if args.config else project_root / "ownerclan_API" / "config.yaml"
    config = load_config(config_path, project_root)
    configure_logging(config.output.log_dir)
    result = run(project_root, config_path, limit=args.limit, refresh_categories=args.refresh_categories, dry_run=args.dry_run)
    print("Ownerclan collection summary")
    print(f"categoryCollection={result['categoryCollection']}")
    print(f"incremental={result['incremental']}")
    return 1 if any(stage["failureCount"] for stage in result.values()) else 0


if __name__ == "__main__":
    sys.exit(main())

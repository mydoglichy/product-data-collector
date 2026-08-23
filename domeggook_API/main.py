from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .collect_product_details import collect_details
from .config import find_project_root, load_config
from .discover_products import discover
from .logging_config import configure_logging
from .storage import FileLock


LOGGER = logging.getLogger("domeggook_API")


def run(project_root: Path, config_path: Path, *, limit: int | None = None, dry_run: bool = False) -> dict[str, dict[str, int]]:
    config = load_config(config_path)
    with FileLock(project_root / "domeggook_API" / "logs" / "collector.lock"):
        discovery = discover(project_root, config, keyword_limit=limit, dry_run=dry_run)
        details = collect_details(project_root, config, product_limit=limit, dry_run=dry_run)
    return {"discovery": discovery, "details": details}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Domeggook/Domeme discovery and daily detail snapshot collection.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Limit keywords and active product ids for a small real API run.")
    parser.add_argument("--dry-run", action="store_true", help="Call API but do not write tracked/output files.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    configure_logging(project_root / "domeggook_API" / "logs")
    config_path = Path(args.config) if args.config else project_root / "domeggook_API" / "config.yaml"
    result = run(project_root, config_path, limit=args.limit, dry_run=args.dry_run)
    print("Domeggook collection summary")
    print(f"discovery={result['discovery']}")
    print(f"details={result['details']}")
    return 1 if result["discovery"]["failureCount"] or result["details"]["failureCount"] else 0


if __name__ == "__main__":
    sys.exit(main())

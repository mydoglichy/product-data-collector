from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import find_project_root, load_config
from .discover_products import make_client
from .logging_config import configure_logging
from .queries import all_items_query


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Ownerclan Seller API authentication and GraphQL connectivity.")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)
    project_root = find_project_root(Path.cwd())
    config = load_config(Path(args.config) if args.config else project_root / "ownerclan_API" / "config.yaml", project_root)
    configure_logging(config.output.log_dir)
    client = make_client(project_root, config)
    data = client.graphql(all_items_query(first=1))
    count = len((data.get("allItems") or {}).get("edges") or [])
    print({"ok": True, "environment": config.environment, "sampleCount": count})
    return 0


if __name__ == "__main__":
    sys.exit(main())


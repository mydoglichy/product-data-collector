from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import find_project_root
from .storage import migrate_sortby_schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate Ownerclan stored rank data to sortBy-only schema.")
    parser.add_argument("--data-dir", default=None, help="Ownerclan data directory. Defaults to ownerclan_API/data.")
    args = parser.parse_args(argv)

    project_root = find_project_root(Path.cwd())
    data_dir = Path(args.data_dir) if args.data_dir else project_root / "ownerclan_API" / "data"
    stats = migrate_sortby_schema(data_dir)
    print(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())

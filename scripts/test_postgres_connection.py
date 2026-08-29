from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from postgres_storage import connect, init_schema, load_postgres_config, test_connection as check_postgres_connection

__test__ = False


def main() -> int:
    config = load_postgres_config(PROJECT_ROOT)
    with connect(config) as connection:
        init_schema(connection)
    result = check_postgres_connection(PROJECT_ROOT)
    print(f"PostgreSQL connection ok: database={result['database']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

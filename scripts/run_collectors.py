from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from domeggook_API.workflows.main import run as run_domeggook
from ownerclan_API.workflows.main import run as run_ownerclan
from postgres_storage import product_counts, postgres_enabled, test_connection

LOGGER = logging.getLogger("collector.runner")


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    _configure_logging()
    _require_environment()
    _check_postgres()

    limit = _optional_positive_int(os.getenv("COLLECTOR_LIMIT"), "COLLECTOR_LIMIT")
    dry_run = _truthy(os.getenv("COLLECTOR_DRY_RUN"))
    ownerclan_refresh = _truthy(os.getenv("OWNERCLAN_REFRESH_CATEGORIES", "true"))
    failures = 0

    LOGGER.info(
        "collector_start limit=%s dryRun=%s ownerclanRefreshCategories=%s",
        limit if limit is not None else "none",
        dry_run,
        ownerclan_refresh,
    )
    _log_product_counts("before")

    if not _truthy(os.getenv("SKIP_OWNERCLAN")):
        failures += _run_stage(
            "ownerclan",
            lambda: run_ownerclan(
                PROJECT_ROOT,
                PROJECT_ROOT / "ownerclan_API" / "config" / "config.yaml",
                limit=limit,
                refresh_categories=ownerclan_refresh,
                dry_run=dry_run,
            ),
        )
        _log_product_counts("after_ownerclan")

    if not _truthy(os.getenv("SKIP_DOMEGGOOK")):
        failures += _run_stage(
            "domeggook",
            lambda: run_domeggook(
                PROJECT_ROOT,
                PROJECT_ROOT / "domeggook_API" / "config" / "config.yaml",
                limit=limit,
                page_limit=limit,
                dry_run=dry_run,
            ),
        )
        _log_product_counts("after_domeggook")

    LOGGER.info("collector_finished failedStages=%d", failures)
    return 1 if failures else 0


def _run_stage(name: str, callback: Any) -> int:
    LOGGER.info("stage_start platform=%s", name)
    try:
        result = callback()
    except Exception:
        LOGGER.exception("stage_failed platform=%s", name)
        return 1
    stage_failures = _failure_count(result)
    LOGGER.info("stage_finished platform=%s result=%s failureCount=%d", name, result, stage_failures)
    return 1 if stage_failures else 0


def _failure_count(value: Any) -> int:
    if isinstance(value, dict):
        total = 0
        for child in value.values():
            if isinstance(child, dict):
                total += int(child.get("failureCount") or 0)
        return total
    return 0


def _check_postgres() -> None:
    if not postgres_enabled(PROJECT_ROOT):
        raise RuntimeError("POSTGRES_ENABLED must be true for operating collection")
    result = test_connection(PROJECT_ROOT)
    LOGGER.info("postgres_connection_ok database=%s", result["database"])


def _log_product_counts(label: str) -> None:
    counts = product_counts(PROJECT_ROOT)
    total = sum(counts.values())
    LOGGER.info("postgres_product_counts label=%s total=%d byPlatform=%s", label, total, counts)


def _require_environment() -> None:
    required = [
        "DOMEGGOOK_API_KEY_1",
        "OWNERCLAN_USERNAME",
        "OWNERCLAN_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"missing required environment variables: {', '.join(missing)}")


def _optional_positive_int(value: str | None, name: str) -> int | None:
    if value in (None, ""):
        return None
    parsed = int(value)
    if parsed < 1:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _configure_logging() -> None:
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "collector-runner.log", encoding="utf-8"),
        ],
        force=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())

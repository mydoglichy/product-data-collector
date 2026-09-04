from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from coupang_API.config import load_config as load_coupang_config
from coupang_API.workflows.collector import collect_once as collect_coupang_once
from domeggook_API.workflows.main import run as run_domeggook
from ownerclan_API.workflows.main import run as run_ownerclan


LOGGER = logging.getLogger("daily_collector")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one daily product collector and write an operation status file.")
    parser.add_argument("--platform", required=True, choices=("ownerclan", "domeggook", "coupang"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ownerclan-workers", type=int, default=8)
    parser.add_argument("--ownerclan-rate-limit-retry-seconds", type=int, default=90)
    parser.add_argument("--ownerclan-failure-retry-seconds", type=int, default=60)
    parser.add_argument("--ownerclan-max-failure-restarts", type=int, default=50)
    parser.add_argument("--ownerclan-refresh-categories", action="store_true")
    parser.add_argument("--domeggook-max-runtime-hours", type=float, default=None)
    parser.add_argument("--domeggook-max-api-calls", type=int, default=None)
    parser.add_argument("--domeggook-recent-pages-per-position", type=int, default=1)
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    started_at = _utc_now()
    exit_code = 0
    result: Any
    try:
        result = _run_platform(args)
        exit_code = _exit_code(args.platform, result)
    except Exception as exc:
        LOGGER.exception("daily collector failed platform=%s", args.platform)
        result = {"error": str(exc)}
        exit_code = 1

    status = {
        "platform": args.platform,
        "status": _status(args.platform, result, exit_code),
        "reason": _reason(args.platform, result, exit_code),
        "startedAt": started_at,
        "endedAt": _utc_now(),
        "result": result,
    }
    _write_status(args.platform, status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return exit_code


def _run_platform(args: argparse.Namespace) -> Any:
    if args.platform == "ownerclan":
        return run_ownerclan(
            PROJECT_ROOT,
            PROJECT_ROOT / "ownerclan_API" / "config" / "config.yaml",
            refresh_categories=args.ownerclan_refresh_categories,
            dry_run=args.dry_run,
            rate_limit_retry_seconds=max(args.ownerclan_rate_limit_retry_seconds, 0),
            failure_retry_seconds=max(args.ownerclan_failure_retry_seconds, 0),
            max_failure_restarts=max(args.ownerclan_max_failure_restarts, 0),
            category_workers=max(args.ownerclan_workers, 1),
        )
    if args.platform == "domeggook":
        max_runtime_seconds = None
        if args.domeggook_max_runtime_hours is not None and args.domeggook_max_runtime_hours > 0:
            max_runtime_seconds = args.domeggook_max_runtime_hours * 3600
        return run_domeggook(
            PROJECT_ROOT,
            PROJECT_ROOT / "domeggook_API" / "config" / "config.yaml",
            max_runtime_seconds=max_runtime_seconds,
            max_api_calls=args.domeggook_max_api_calls,
            mode="daily",
            recent_pages_per_position=max(args.domeggook_recent_pages_per_position, 1),
            dry_run=args.dry_run,
        )
    config = load_coupang_config(PROJECT_ROOT / "coupang_API" / "config" / "config.yaml")
    return {"exitCode": collect_coupang_once(PROJECT_ROOT, config, dry_run=args.dry_run)}


def _exit_code(platform: str, result: Any) -> int:
    if platform == "coupang":
        return int(result.get("exitCode") or 0) if isinstance(result, dict) else 1
    if not isinstance(result, dict):
        return 1
    for stage in result.values():
        if isinstance(stage, dict) and int(stage.get("failureCount") or 0) > 0:
            return 1
    return 0


def _status(platform: str, result: Any, exit_code: int) -> str:
    if exit_code:
        return "failed"
    if platform == "domeggook" and (_runtime_limit_reached(result) or _daily_request_limit_reached(result)):
        return "paused"
    return "completed"


def _reason(platform: str, result: Any, exit_code: int) -> str:
    if exit_code:
        if platform == "ownerclan" and _rate_limit_failure(result):
            return "rate_limit_retry_exhausted"
        return "failure"
    if platform == "domeggook" and _runtime_limit_reached(result):
        return "runtime_limit_reached"
    if platform == "domeggook" and _daily_request_limit_reached(result):
        return "daily_request_limit_reached"
    if platform == "ownerclan":
        return "all_categories_finished"
    if platform == "domeggook":
        if _recent_discovery_ran(result):
            return "all_domeggook_details_finished_and_recent_products_checked"
        return "all_domeggook_details_finished"
    return "all_coupang_keywords_finished"


def _runtime_limit_reached(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    return any(
        isinstance(stage, dict) and int(stage.get("runtimeLimitReached") or 0) > 0
        for stage in result.values()
    )


def _daily_request_limit_reached(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    return any(
        isinstance(stage, dict) and int(stage.get("dailyRequestLimitReached") or 0) > 0
        for stage in result.values()
    )


def _recent_discovery_ran(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    recent = result.get("recentDiscovery")
    return isinstance(recent, dict) and not recent.get("skipReason")


def _rate_limit_failure(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    return any(
        isinstance(stage, dict) and int(stage.get("rateLimitFailureCount") or 0) > 0
        for stage in result.values()
    )


def _write_status(platform: str, status: dict[str, Any]) -> None:
    path = PROJECT_ROOT / f"{platform}_API" / "data" / "state" / "daily-run-status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())

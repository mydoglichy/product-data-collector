from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ownerclan_API.api.auth import JwtProvider
from ownerclan_API.api.client import API_ENDPOINTS
from ownerclan_API.config import find_project_root, load_config, load_credentials


PROBE_QUERY = (
    "query { allItems(first: 1) { "
    "pageInfo { hasNextPage endCursor } "
    "edges { cursor node { key } } "
    "} }"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe Ownerclan GraphQL per-minute request limits without writing API data."
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--rpm", type=float, required=True, help="Target GraphQL requests per minute.")
    parser.add_argument("--duration", type=float, default=60.0, help="Probe duration in seconds.")
    parser.add_argument("--timeout", type=float, default=None, help="Override request timeout in seconds.")
    parser.add_argument("--quiet", action="store_true", help="Only print start, rate-limit, error, and summary events.")
    parser.add_argument(
        "--continue-after-limit",
        action="store_true",
        help="Keep probing after the first 429 or GraphQL rate-limit error.",
    )
    args = parser.parse_args(argv)

    if args.rpm <= 0:
        raise SystemExit("--rpm must be greater than zero")
    if args.duration <= 0:
        raise SystemExit("--duration must be greater than zero")

    project_root = find_project_root(Path.cwd())
    config_path = Path(args.config) if args.config else project_root / "ownerclan_API" / "config" / "config.yaml"
    config = load_config(config_path, project_root)
    username, password = load_credentials(project_root)

    timeout = args.timeout if args.timeout is not None else config.request.timeout_seconds
    session = requests.Session()
    provider = JwtProvider(username, password, config.environment, timeout, session=session)
    token = provider.token()
    endpoint = API_ENDPOINTS[config.environment]

    interval = 60.0 / args.rpm
    started = time.monotonic()
    next_at = started
    deadline = started + args.duration
    results: list[dict[str, Any]] = []
    first_rate_limit: dict[str, Any] | None = None

    print(
        json.dumps(
            {
                "event": "start",
                "environment": config.environment,
                "targetRpm": args.rpm,
                "durationSeconds": args.duration,
                "intervalSeconds": interval,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    attempt = 0
    while time.monotonic() < deadline:
        now = time.monotonic()
        if next_at > now:
            time.sleep(next_at - now)
        attempt += 1
        sent_at = time.monotonic()
        result = send_probe(session, endpoint, token, timeout)
        result["attempt"] = attempt
        result["elapsedSeconds"] = round(sent_at - started, 3)
        results.append(result)
        if not args.quiet or result["rateLimited"] or not result["ok"]:
            print(json.dumps(result, ensure_ascii=False), flush=True)

        if result["rateLimited"] and first_rate_limit is None:
            first_rate_limit = result
            if not args.continue_after_limit:
                break

        next_at += interval

    summary = summarize(results, started, first_rate_limit)
    print(json.dumps({"event": "summary", **summary}, ensure_ascii=False), flush=True)
    return 2 if first_rate_limit else 0


def send_probe(session: requests.Session, endpoint: str, token: str, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        response = session.get(
            endpoint,
            params={"query": PROBE_QUERY},
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        return {
            "ok": False,
            "status": None,
            "rateLimited": False,
            "latencyMs": round((time.monotonic() - started) * 1000, 1),
            "error": exc.__class__.__name__,
        }

    payload = parse_json(response)
    errors = payload.get("errors") if isinstance(payload, dict) else None
    error_text = summarize_errors(errors)
    rate_limited = response.status_code == 429 or looks_like_rate_limit(error_text)
    ok = response.status_code < 400 and not errors
    return {
        "ok": ok,
        "status": response.status_code,
        "rateLimited": rate_limited,
        "latencyMs": round((time.monotonic() - started) * 1000, 1),
        "retryAfter": response.headers.get("Retry-After"),
        "error": error_text or None,
    }


def parse_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def summarize_errors(errors: Any) -> str:
    if not isinstance(errors, list):
        return ""
    messages: list[str] = []
    for error in errors[:3]:
        if isinstance(error, dict):
            messages.append(str(error.get("message") or "GraphQL error"))
        else:
            messages.append(str(error))
    return "; ".join(messages)[:300]


def looks_like_rate_limit(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in ("too many requests", "rate limit", "quota"))


def summarize(
    results: list[dict[str, Any]],
    started: float,
    first_rate_limit: dict[str, Any] | None,
) -> dict[str, Any]:
    elapsed = max(time.monotonic() - started, 0.001)
    return {
        "attempts": len(results),
        "okCount": sum(1 for result in results if result["ok"]),
        "rateLimitCount": sum(1 for result in results if result["rateLimited"]),
        "errorCount": sum(1 for result in results if not result["ok"] and not result["rateLimited"]),
        "elapsedSeconds": round(elapsed, 3),
        "observedRpm": round(len(results) * 60.0 / elapsed, 2),
        "firstRateLimitAttempt": first_rate_limit["attempt"] if first_rate_limit else None,
        "firstRateLimitElapsedSeconds": first_rate_limit["elapsedSeconds"] if first_rate_limit else None,
    }


if __name__ == "__main__":
    sys.exit(main())

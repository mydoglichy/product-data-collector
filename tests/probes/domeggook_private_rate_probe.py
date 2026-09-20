from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SSL_API_URL = "https://www.domeggook.com/ssl/api/"
KST = timezone(timedelta(hours=9))
DEFAULT_PLAN = "40:120,80:120,120:180,160:240,180:300,190:300,200:300"
SECRET_PARAM_KEYS = {"aid", "id", "pw", "sId", "sid", "sellerId", "Authorization"}
RATE_LIMIT_TERMS = (
    "429",
    "too many",
    "rate limit",
    "ratelimit",
    "quota",
    "blocked",
    "limit exceeded",
    "요청 횟수",
    "사용 횟수",
    "초과",
    "차단",
    "제한",
    "분당",
)
THREAD_LOCAL = threading.local()


@dataclass(frozen=True)
class Stage:
    rpm: float
    duration_seconds: float


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe Domeggook private getItemViewES rate limits.")
    parser.add_argument("--plan", default=DEFAULT_PLAN, help="Comma-separated RPM:seconds plan.")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--stage-cooldown", type=float, default=30.0)
    parser.add_argument("--limit-cooldown", type=float, default=180.0)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-consecutive-errors", type=int, default=3)
    parser.add_argument("--error-rate-stop", type=float, default=0.02)
    parser.add_argument("--output-dir", default="tests/probes/logs")
    parser.add_argument("--item-no", action="append", default=[])
    args = parser.parse_args(argv)

    if args.batch_size < 1:
        raise SystemExit("--batch-size must be greater than zero")
    stages = parse_plan(args.plan)
    root = find_project_root(Path.cwd())
    load_dotenv(root / ".env", override=False)

    out_dir = root / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(KST).strftime("domeggook_private_rate_%Y%m%d_%H%M%S")
    events_path = out_dir / f"{run_id}.jsonl"
    summary_path = out_dir / f"{run_id}_summary.json"

    session = requests.Session()
    api_label, api_key = choose_api_key()
    member_id = env_first("DOMEGGOOK_ID", "DOMEGGOOK_MEMBER_ID")
    password = env_first("DOMEGGOOK_PASSWORD", "DOMEGGOOK_PW")
    sid = login(session, api_key, member_id, password, args.timeout) if member_id and password else None

    item_nos = [str(value).strip() for value in args.item_no if str(value).strip()]
    if not item_nos:
        item_nos = collect_item_nos(session, api_key, member_id, sid, args.timeout, root)
    item_nos = list(dict.fromkeys(item_nos))[: args.batch_size]
    if not item_nos:
        raise SystemExit("No item numbers available for probe.")

    run_meta = {
        "event": "start",
        "runId": run_id,
        "apiKeyLabel": api_label,
        "apiKeyHash": stable_hash(api_key),
        "hasLoginSession": bool(sid),
        "batchSize": len(item_nos),
        "targetItemsPerRequest": args.batch_size,
        "plan": [{"rpm": stage.rpm, "durationSeconds": stage.duration_seconds} for stage in stages],
        "eventsPath": str(events_path),
        "summaryPath": str(summary_path),
        "startedAt": datetime.now(KST).isoformat(),
    }
    append_jsonl(events_path, run_meta)
    print(json.dumps(mask_secrets(run_meta), ensure_ascii=False), flush=True)

    stage_summaries: list[dict[str, Any]] = []
    final_reason = "completed"
    first_rate_limit: dict[str, Any] | None = None

    for index, stage in enumerate(stages, start=1):
        stage_summary = run_stage(
            session=session,
            api_key=api_key,
            member_id=member_id,
            sid=sid,
            item_nos=item_nos,
            stage=stage,
            stage_index=index,
            timeout=args.timeout,
            events_path=events_path,
            max_consecutive_errors=args.max_consecutive_errors,
            error_rate_stop=args.error_rate_stop,
            concurrency=args.concurrency,
        )
        stage_summaries.append(stage_summary)
        append_jsonl(events_path, {"event": "stage_summary", **stage_summary})
        print(json.dumps({"event": "stage_summary", **stage_summary}, ensure_ascii=False), flush=True)

        if stage_summary["rateLimitCount"] > 0:
            final_reason = "rate_limited"
            first_rate_limit = stage_summary.get("firstRateLimit")
            cooldown = max(args.limit_cooldown, retry_after_seconds(first_rate_limit) or 0.0)
            cooldown_event = {"event": "cooldown", "reason": final_reason, "seconds": cooldown}
            append_jsonl(events_path, cooldown_event)
            print(json.dumps(cooldown_event, ensure_ascii=False), flush=True)
            time.sleep(cooldown)
            break

        if stage_summary["stopReason"] != "duration_complete":
            final_reason = stage_summary["stopReason"]
            break

        if index < len(stages) and args.stage_cooldown > 0:
            cooldown_event = {
                "event": "cooldown",
                "reason": "between_stages",
                "seconds": args.stage_cooldown,
                "nextRpm": stages[index].rpm,
            }
            append_jsonl(events_path, cooldown_event)
            print(json.dumps(cooldown_event, ensure_ascii=False), flush=True)
            time.sleep(args.stage_cooldown)

    summary = summarize_run(run_meta, stage_summaries, final_reason, first_rate_limit)
    summary_path.write_text(json.dumps(mask_secrets(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    append_jsonl(events_path, {"event": "summary", **summary})
    print(json.dumps({"event": "summary", **mask_secrets(summary)}, ensure_ascii=False), flush=True)
    return 2 if final_reason == "rate_limited" else 0


def run_stage(
    *,
    session: requests.Session,
    api_key: str,
    member_id: str | None,
    sid: str | None,
    item_nos: list[str],
    stage: Stage,
    stage_index: int,
    timeout: float,
    events_path: Path,
    max_consecutive_errors: int,
    error_rate_stop: float,
    concurrency: int,
) -> dict[str, Any]:
    interval = 60.0 / stage.rpm
    started = time.monotonic()
    deadline = started + stage.duration_seconds
    next_at = started
    attempt = 0
    consecutive_errors = 0
    results: list[dict[str, Any]] = []
    stop_reason = "duration_complete"
    first_rate_limit: dict[str, Any] | None = None

    append_jsonl(
        events_path,
        {
            "event": "stage_start",
            "stageIndex": stage_index,
            "targetRpm": stage.rpm,
            "durationSeconds": stage.duration_seconds,
            "intervalSeconds": interval,
        },
    )

    pending: dict[Future[dict[str, Any]], tuple[int, float]] = {}
    with ThreadPoolExecutor(max_workers=max(concurrency, 1)) as executor:
        while time.monotonic() < deadline or pending:
            now = time.monotonic()
            while time.monotonic() < deadline and len(pending) < max(concurrency, 1) and now >= next_at:
                attempt += 1
                sent_at = time.monotonic()
                future = executor.submit(
                    call_get_item_view_es_threaded,
                    api_key,
                    member_id,
                    sid,
                    item_nos,
                    timeout,
                )
                pending[future] = (attempt, sent_at)
                next_at += interval
                if next_at < time.monotonic():
                    # Skip missed slots after slow responses; do not send catch-up bursts.
                    next_at = time.monotonic()
                now = time.monotonic()

            wait_timeout = 0.1
            if time.monotonic() < deadline and next_at > time.monotonic():
                wait_timeout = min(wait_timeout, max(next_at - time.monotonic(), 0.0))
            done: set[Future[dict[str, Any]]] = set()
            if pending:
                done, _ = wait(pending, timeout=wait_timeout, return_when=FIRST_COMPLETED)
            elif time.monotonic() < deadline:
                time.sleep(max(min(next_at - time.monotonic(), 0.1), 0.0))

            for future in done:
                result = future.result()
                current_attempt, sent_at = pending.pop(future)
                result.update(
                    {
                        "event": "attempt",
                        "stageIndex": stage_index,
                        "targetRpm": stage.rpm,
                        "attempt": current_attempt,
                        "elapsedSeconds": round(sent_at - started, 3),
                    }
                )
                results.append(result)

                if result["rateLimited"]:
                    first_rate_limit = result
                    append_jsonl(events_path, result)
                    stop_reason = "rate_limited"
                    break

                if not result["ok"]:
                    consecutive_errors += 1
                    append_jsonl(events_path, result)
                else:
                    consecutive_errors = 0

                if max_consecutive_errors > 0 and consecutive_errors >= max_consecutive_errors:
                    stop_reason = "consecutive_errors"
                    break

                if len(results) >= 20 and error_rate_stop > 0:
                    non_limit_errors = sum(1 for item in results if not item["ok"] and not item["rateLimited"])
                    if non_limit_errors / len(results) > error_rate_stop:
                        stop_reason = "error_rate_exceeded"
                        break

            if stop_reason != "duration_complete":
                for future in pending:
                    future.cancel()
                break

    return summarize_stage(stage, stage_index, started, results, stop_reason, first_rate_limit)


def call_get_item_view_es(
    session: requests.Session,
    api_key: str,
    member_id: str | None,
    sid: str | None,
    item_nos: list[str],
    timeout: float,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "ver": "4.0",
        "mode": "getItemViewES",
        "aid": api_key,
        "no": ",".join(item_nos),
        "allItem": "true",
        "om": "json",
    }
    if member_id and sid:
        params["sellerId"] = member_id
        params["sId"] = sid

    started = time.monotonic()
    try:
        response = session.get(SSL_API_URL, params=params, timeout=timeout)
        latency_ms = round((time.monotonic() - started) * 1000, 1)
    except (requests.Timeout, requests.ConnectionError) as exc:
        return {
            "ok": False,
            "status": None,
            "latencyMs": round((time.monotonic() - started) * 1000, 1),
            "rateLimited": False,
            "retryAfter": None,
            "error": exc.__class__.__name__,
            "itemCount": 0,
        }

    retry_after = response.headers.get("Retry-After")
    payload: Any
    text_for_error = ""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
        text_for_error = response.text[:500]

    error_text = extract_error_text(payload) or text_for_error
    rate_limited = response.status_code == 429 or bool(retry_after) or looks_like_rate_limit(error_text)
    ok = response.status_code < 400 and not error_text
    return {
        "ok": ok,
        "status": response.status_code,
        "latencyMs": latency_ms,
        "rateLimited": rate_limited,
        "retryAfter": retry_after,
        "error": error_text[:300] if error_text else None,
        "itemCount": count_detail_items(payload),
    }


def call_get_item_view_es_threaded(
    api_key: str,
    member_id: str | None,
    sid: str | None,
    item_nos: list[str],
    timeout: float,
) -> dict[str, Any]:
    return call_get_item_view_es(get_thread_session(), api_key, member_id, sid, item_nos, timeout)


def get_thread_session() -> requests.Session:
    session = getattr(THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        THREAD_LOCAL.session = session
    return session


def collect_item_nos(
    session: requests.Session,
    api_key: str,
    member_id: str | None,
    sid: str | None,
    timeout: float,
    root: Path,
) -> list[str]:
    item_nos: list[str] = []
    if member_id and sid:
        today = datetime.now(KST).strftime("%Y%m%d")
        for date in (today, None):
            params = {
                "ver": "1.1",
                "mode": "getAllSupplyChk",
                "aid": api_key,
                "id": member_id,
                "sId": sid,
                "type": "all",
                "om": "json",
                "status": "OPEN_RESTART_CLOSE_SOLDOUT_DEL_AMT_OPTAMT_OPTSOLDOUT_OPTRESTART",
                "ic": "500",
                "pg": "1",
            }
            if date:
                params["date"] = date
            try:
                response = session.post(SSL_API_URL, data=params, timeout=timeout)
                payload = response.json()
            except (requests.RequestException, ValueError):
                payload = {}
            item_nos.extend(extract_supply_item_nos(payload))
            if len(set(item_nos)) >= 100:
                return list(dict.fromkeys(item_nos))

    for path in sorted((root / "tests" / "tmp" / "domeggook_all_supply_chk").glob("**/*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        item_nos.extend(extract_supply_item_nos(payload))
        item_nos.extend(extract_detail_item_nos(payload))
        if len(set(item_nos)) >= 100:
            break
    return list(dict.fromkeys(item_nos))


def login(
    session: requests.Session,
    api_key: str,
    member_id: str | None,
    password: str | None,
    timeout: float,
) -> str | None:
    if not member_id or not password:
        return None
    params = {
        "ver": "4.1",
        "mode": "setLogin",
        "aid": api_key,
        "id": member_id,
        "pw": password,
        "om": "json",
        "loginKeep": "off",
        "userAgent": "product-data-collector-private-rate-probe/1.0",
        "ip": os.getenv("DOMEGGOOK_LOGIN_IP") or resolve_public_ip(session),
        "device": "Third Party",
    }
    try:
        response = session.post(SSL_API_URL, data=params, timeout=timeout)
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    root = domeggook_root(payload)
    sid = first_value(root, "sId", "sid")
    return str(sid) if sid else None


def summarize_stage(
    stage: Stage,
    stage_index: int,
    started: float,
    results: list[dict[str, Any]],
    stop_reason: str,
    first_rate_limit: dict[str, Any] | None,
) -> dict[str, Any]:
    elapsed = max(time.monotonic() - started, 0.001)
    latencies = sorted(float(item["latencyMs"]) for item in results if item.get("latencyMs") is not None)
    ok_count = sum(1 for item in results if item["ok"])
    error_count = sum(1 for item in results if not item["ok"] and not item["rateLimited"])
    rate_limit_count = sum(1 for item in results if item["rateLimited"])
    observed_rpm = len(results) * 60.0 / elapsed
    return {
        "stageIndex": stage_index,
        "targetRpm": stage.rpm,
        "durationSeconds": stage.duration_seconds,
        "stopReason": stop_reason,
        "attempts": len(results),
        "okCount": ok_count,
        "errorCount": error_count,
        "rateLimitCount": rate_limit_count,
        "elapsedSeconds": round(elapsed, 3),
        "observedRpm": round(observed_rpm, 2),
        "itemCountPerRequestMedian": percentile([float(item.get("itemCount") or 0) for item in results], 50),
        "latencyMsP50": percentile(latencies, 50),
        "latencyMsP95": percentile(latencies, 95),
        "latencyMsMax": max(latencies) if latencies else None,
        "firstRateLimit": compact_attempt(first_rate_limit),
    }


def summarize_run(
    run_meta: dict[str, Any],
    stage_summaries: list[dict[str, Any]],
    final_reason: str,
    first_rate_limit: dict[str, Any] | None,
) -> dict[str, Any]:
    stable_stages = [
        stage
        for stage in stage_summaries
        if stage["stopReason"] == "duration_complete"
        and stage["rateLimitCount"] == 0
        and stage["errorCount"] == 0
        and stage["observedRpm"] >= stage["targetRpm"] * 0.95
    ]
    best = max(stable_stages, key=lambda item: item["targetRpm"], default=None)
    batch_size = int(run_meta["batchSize"])
    stable_rpm = float(best["targetRpm"]) if best else 0.0
    success_rate = (float(best["okCount"]) / float(best["attempts"])) if best and best["attempts"] else 0.0
    projected_daily_items = int(stable_rpm * 1440 * batch_size * success_rate)
    required_rpm_for_4m = 4_000_000 / (1440 * batch_size * max(success_rate, 0.001)) if batch_size else None
    return {
        **run_meta,
        "finishedAt": datetime.now(KST).isoformat(),
        "finalReason": final_reason,
        "stageSummaries": stage_summaries,
        "stableRpm": stable_rpm,
        "stableBatchSize": batch_size,
        "stableSuccessRate": round(success_rate, 6),
        "projectedDailyItems": projected_daily_items,
        "requiredRpmFor4m": round(required_rpm_for_4m, 2) if required_rpm_for_4m is not None else None,
        "canCollect4mPerDay": projected_daily_items >= 4_000_000,
        "firstRateLimit": compact_attempt(first_rate_limit),
    }


def parse_plan(value: str) -> list[Stage]:
    stages: list[Stage] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        rpm_text, _, seconds_text = token.partition(":")
        if not rpm_text or not seconds_text:
            raise SystemExit(f"Invalid plan token: {token}")
        rpm = float(rpm_text)
        seconds = float(seconds_text)
        if rpm <= 0 or seconds <= 0:
            raise SystemExit(f"Invalid plan token: {token}")
        stages.append(Stage(rpm=rpm, duration_seconds=seconds))
    if not stages:
        raise SystemExit("--plan must contain at least one stage")
    return stages


def choose_api_key() -> tuple[str, str]:
    for name in (
        "DOMEGGOOK_PRIVATE_API_KEY",
        "DOMEGGOOK_PrivateAPI_KEY_2",
        "DOMEGGOOK_API_KEY_1",
        "DOMEGGOOK_API_KEY",
    ):
        value = os.getenv(name)
        if value:
            return name, value
    raise SystemExit("Missing Domeggook API key env.")


def extract_error_text(payload: Any) -> str:
    root = domeggook_root(payload)
    candidates: list[Any] = []
    if isinstance(payload, dict):
        candidates.append(payload.get("errors"))
        candidates.append(payload.get("error"))
        candidates.append(payload.get("message"))
        candidates.append(payload.get("msg"))
    if isinstance(root, dict):
        candidates.append(root.get("errors"))
        candidates.append(root.get("error"))
        candidates.append(root.get("message"))
        candidates.append(root.get("msg"))
        if str(root.get("status", "")).lower() in {"fail", "error"}:
            candidates.append(root)
    messages: list[str] = []
    for candidate in candidates:
        collect_messages(candidate, messages)
    return "; ".join(dict.fromkeys(message for message in messages if message))


def collect_messages(value: Any, messages: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        messages.append(value)
        return
    if isinstance(value, dict):
        for key in ("code", "message", "msg", "dcode", "dmessage"):
            child = value.get(key)
            if child is not None:
                messages.append(str(child))
        return
    if isinstance(value, list):
        for item in value[:3]:
            collect_messages(item, messages)


def looks_like_rate_limit(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in RATE_LIMIT_TERMS)


def count_detail_items(payload: Any) -> int:
    root = domeggook_root(payload)
    if not isinstance(root, dict):
        return 0
    for key in ("item", "items", "itemView", "data"):
        value = root.get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            nested = value.get("item") or value.get("items")
            if isinstance(nested, list):
                return len(nested)
            if isinstance(nested, dict):
                return 1
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return 1
    return 1 if root else 0


def extract_supply_item_nos(payload: Any) -> list[str]:
    root = domeggook_root(payload)
    if not isinstance(root, dict):
        return []
    candidates: list[Any] = []
    items = root.get("items")
    if isinstance(items, dict):
        candidates.append(items.get("item"))
    candidates.append(root.get("item"))
    result: list[str] = []
    for candidate in candidates:
        rows = candidate if isinstance(candidate, list) else [candidate]
        for row in rows:
            if isinstance(row, dict) and row.get("no") is not None:
                result.append(str(row["no"]))
    return result


def extract_detail_item_nos(payload: Any) -> list[str]:
    root = domeggook_root(payload.get("payload") if isinstance(payload, dict) else payload)
    if not isinstance(root, dict):
        return []
    rows: list[Any] = []
    for key in ("item", "items", "itemView", "data"):
        value = root.get(key)
        if isinstance(value, list):
            rows.extend(value)
        elif isinstance(value, dict):
            nested = value.get("item") or value.get("items")
            if isinstance(nested, list):
                rows.extend(nested)
            else:
                rows.append(value)
    result: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        basis = row.get("basis") if isinstance(row.get("basis"), dict) else {}
        no = basis.get("no") or row.get("no") or row.get("itemNo")
        if no is not None:
            result.append(str(no))
    return result


def domeggook_root(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("domeggook"), dict):
        return payload["domeggook"]
    return payload if isinstance(payload, dict) else {}


def first_value(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value:
            return str(value)
    return None


def env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def resolve_public_ip(session: requests.Session) -> str:
    try:
        response = session.get("https://api.ipify.org", timeout=5)
        response.raise_for_status()
        if response.text.strip():
            return response.text.strip()
    except requests.RequestException:
        pass
    return socket.gethostbyname(socket.gethostname())


def retry_after_seconds(attempt: dict[str, Any] | None) -> float | None:
    if not attempt:
        return None
    value = attempt.get("retryAfter")
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return None


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * pct / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def compact_attempt(attempt: dict[str, Any] | None) -> dict[str, Any] | None:
    if not attempt:
        return None
    return {
        "stageIndex": attempt.get("stageIndex"),
        "targetRpm": attempt.get("targetRpm"),
        "attempt": attempt.get("attempt"),
        "elapsedSeconds": attempt.get("elapsedSeconds"),
        "status": attempt.get("status"),
        "retryAfter": attempt.get("retryAfter"),
        "error": attempt.get("error"),
    }


def stable_hash(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return "sha256:" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def mask_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if key in SECRET_PARAM_KEYS or key.lower() in {"password", "passwd"}:
                result[key] = "****"
            else:
                result[key] = mask_secrets(child)
        return result
    if isinstance(value, list):
        return [mask_secrets(child) for child in value]
    return value


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(mask_secrets(payload), ensure_ascii=False) + "\n")


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "domeggook_API").is_dir() and (candidate / ".env").exists():
            return candidate
    return PROJECT_ROOT


if __name__ == "__main__":
    sys.exit(main())

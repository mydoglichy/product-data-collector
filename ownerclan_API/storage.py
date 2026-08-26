from __future__ import annotations

import copy
import json
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from product_history import upsert_product_changes


class FileLock:
    def __init__(self, path: Path, stale_after_seconds: float = 12 * 60 * 60) -> None:
        self.path = path
        self.stale_after_seconds = stale_after_seconds
        self._fd: int | None = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_stale_lock()
        try:
            self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"another ownerclan_API collection appears to be running: {self.path}") from exc
        os.write(self._fd, str(os.getpid()).encode("ascii"))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def _remove_stale_lock(self) -> None:
        if self.stale_after_seconds <= 0 or not self.path.exists():
            return
        try:
            if time.time() - self.path.stat().st_mtime > self.stale_after_seconds:
                self.path.unlink()
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2, sort_keys=True)
        fp.write("\n")
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp_path, path)


def load_json_object(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(default or {})
    with path.open("r", encoding="utf-8-sig") as fp:
        payload = json.load(fp)
    return payload if isinstance(payload, dict) else copy.deepcopy(default or {})


def load_tracked_products(path: Path) -> dict[str, dict[str, Any]]:
    payload = load_json_object(path)
    return {str(key): _normalize_tracked_product(value) for key, value in payload.items() if isinstance(value, dict)}


def save_tracked_products(path: Path, tracked: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(path, tracked)


def merge_discovered_product(
    tracked: dict[str, dict[str, Any]],
    product_key: str,
    keyword: str | None,
    reason: str,
    seen_at: str,
) -> bool:
    created = product_key not in tracked
    record = tracked.setdefault(
        product_key,
        {
            "productId": product_key,
            "productKey": product_key,
            "keywords": [],
            "reasons": [],
            "firstSeenAt": seen_at,
            "lastSeenAt": seen_at,
            "active": True,
        },
    )
    record.pop("searchTypes", None)
    record["productId"] = str(record.get("productId") or product_key)
    record["productKey"] = str(record.get("productKey") or product_key)
    if keyword:
        record["keywords"] = _append_unique(record.get("keywords"), keyword)
    record["reasons"] = _append_unique(record.get("reasons"), reason)
    record.setdefault("firstSeenAt", seen_at)
    record["lastSeenAt"] = seen_at
    record["active"] = bool(record.get("active", True))
    return created


def active_product_keys(tracked: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(str(key) for key, record in tracked.items() if record.get("active", True))


def append_search_ranks(path: Path, records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    payload = load_json_object(path, {"collectedAt": None, "ranks": []})
    ranks = [_normalize_rank_record(record) for record in payload.get("ranks", []) if isinstance(record, dict)]
    seen = {_rank_key(record) for record in ranks if isinstance(record, dict)}
    for record in records:
        normalized = _normalize_rank_record(record)
        key = _rank_key(normalized)
        if key in seen:
            continue
        seen.add(key)
        ranks.append(normalized)
    result = {"collectedAt": ranks[-1].get("collectedAt") if ranks else payload.get("collectedAt"), "ranks": ranks}
    atomic_write_json(path, result)
    return result


def migrate_sortby_schema(data_dir: Path) -> dict[str, int]:
    stats = {"trackedFiles": 0, "rankFiles": 0}
    tracked_path = data_dir / "state" / "tracked_products.json"
    if tracked_path.exists():
        save_tracked_products(tracked_path, load_tracked_products(tracked_path))
        stats["trackedFiles"] += 1

    for path in sorted((data_dir / "processed").glob("*_search-ranks.json")):
        append_search_ranks(path, [])
        stats["rankFiles"] += 1
    return stats


def merge_product_snapshots(
    path: Path,
    collected_at: str,
    products: Iterable[dict[str, Any]],
    failures: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    existing = load_json_object(path, {"products": [], "failures": []})
    by_product_id: dict[str, dict[str, Any]] = {}
    for record in existing.get("products", []):
        if isinstance(record, dict) and record.get("productId") is not None:
            by_product_id[str(record["productId"])] = record
    for product in products:
        product_id = product.get("productId")
        if product_id is not None:
            by_product_id[str(product_id)] = product

    failure_records = [failure for failure in existing.get("failures", []) if isinstance(failure, dict)]
    failure_seen = {json.dumps(failure, ensure_ascii=False, sort_keys=True) for failure in failure_records}
    for failure in failures:
        key = json.dumps(failure, ensure_ascii=False, sort_keys=True)
        if key not in failure_seen:
            failure_seen.add(key)
            failure_records.append(failure)
    merged_products = sorted(by_product_id.values(), key=lambda record: str(record.get("productId")))
    payload = {
        "collectedAt": collected_at,
        "successCount": len(merged_products),
        "failureCount": len(failure_records),
        "products": merged_products,
        "failures": failure_records,
    }
    atomic_write_json(path, payload)
    return payload


def save_raw_samples(
    path: Path,
    collected_at: str,
    products: Iterable[dict[str, Any]],
    limit: int,
) -> dict[str, Any]:
    if limit < 0:
        raise ValueError("limit must be zero or greater")
    limit = min(limit, 3)
    items: list[dict[str, Any]] = []
    for product in products:
        if len(items) >= limit:
            break
        raw = product.get("raw")
        if raw is None:
            continue
        items.append(
            {
                "productId": product.get("productId"),
                "productKey": product.get("productKey"),
                "raw": raw,
            }
        )
    payload = {"collectedAt": collected_at, "items": items}
    atomic_write_json(path, payload)
    return payload


def update_latest_and_history(
    *,
    latest_path: Path,
    history_path: Path,
    collected_at: str,
    products: Iterable[dict[str, Any]],
) -> dict[str, int]:
    stats = upsert_product_changes(
        platform="ownerclan",
        current_path=latest_path,
        history_path=history_path,
        collected_at=collected_at,
        products=products,
    )
    latest = load_json_object(latest_path, {"products": {}})
    latest_products = latest.get("products") if isinstance(latest.get("products"), dict) else {}
    return {"latestCount": len(latest_products), "changedCount": stats["newProductCount"] + stats["changedProductCount"], **stats}


def save_failures(path: Path, collected_at: str, failures: Iterable[dict[str, Any]]) -> None:
    payload = load_json_object(path, {"collectedAt": None, "failures": []})
    records = payload.get("failures") if isinstance(payload.get("failures"), list) else []
    records.extend(failures)
    atomic_write_json(path, {"collectedAt": collected_at, "failures": records})


def load_state(path: Path) -> dict[str, Any]:
    return load_json_object(path)


def save_state(path: Path, state: dict[str, Any]) -> None:
    atomic_write_json(path, state)


def chunked(values: list[str], size: int) -> list[list[str]]:
    if size < 1:
        raise ValueError("size must be greater than zero")
    return [values[index : index + size] for index in range(0, len(values), size)]


def _append_unique(values: Any, value: str) -> list[str]:
    result = [str(item) for item in values] if isinstance(values, list) else []
    if value not in result:
        result.append(value)
    return result


def _normalize_tracked_product(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    normalized.pop("searchTypes", None)
    return normalized


def _normalize_rank_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    normalized.pop("searchType", None)
    if normalized.get("sortBy") is None:
        normalized["sortBy"] = "default"
    return normalized


def _rank_key(record: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(record.get("collectedAt")),
        str(record.get("keyword")),
        str(record.get("sortBy")),
        str(record.get("productId")),
        str(record.get("rank")),
    )



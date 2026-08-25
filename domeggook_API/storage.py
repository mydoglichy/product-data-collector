from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any


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
            raise RuntimeError(f"another domeggook_API collection appears to be running: {self.path}") from exc
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
            age_seconds = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if age_seconds > self.stale_after_seconds:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def load_tracked_products(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError(f"tracked products file must contain an object: {path}")
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def merge_discovered_product(
    tracked: dict[str, dict[str, Any]],
    product_id: str,
    keyword: str,
    market: str,
    reason: str,
    seen_at: str,
) -> bool:
    created = product_id not in tracked
    record = tracked.setdefault(
        product_id,
        {
            "productId": product_id,
            "keywords": [],
            "markets": [],
            "reasons": [],
            "firstSeenAt": seen_at,
            "lastSeenAt": seen_at,
            "active": True,
        },
    )
    record["productId"] = str(record.get("productId") or product_id)
    record["keywords"] = _append_unique(record.get("keywords"), keyword)
    record["markets"] = _append_unique(record.get("markets"), market)
    record["reasons"] = _append_unique(record.get("reasons"), reason)
    record.setdefault("firstSeenAt", seen_at)
    record["lastSeenAt"] = seen_at
    record["active"] = bool(record.get("active", True))
    return created


def active_product_ids(tracked: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(str(product_id) for product_id, record in tracked.items() if record.get("active", True))


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2, sort_keys=True)
        fp.write("\n")
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp_path, path)


def save_tracked_products(path: Path, tracked: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(path, tracked)


def append_search_ranks(path: Path, records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    existing = _load_or_default(path, {"collectedAt": None, "ranks": []})
    ranks = existing.get("ranks") if isinstance(existing, dict) else []
    if not isinstance(ranks, list):
        ranks = []
    seen = {_rank_key(record) for record in ranks if isinstance(record, dict)}
    for record in records:
        key = _rank_key(record)
        if key in seen:
            continue
        seen.add(key)
        ranks.append(record)
    collected_at = ranks[-1].get("collectedAt") if ranks and isinstance(ranks[-1], dict) else existing.get("collectedAt")
    payload = {"collectedAt": collected_at, "ranks": ranks}
    atomic_write_json(path, payload)
    return payload


def merge_product_snapshots(
    path: Path,
    collected_at: str,
    products: Iterable[dict[str, Any]],
    failures: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    existing = _load_or_default(path, {"products": [], "failures": []})
    by_product_id: dict[str, dict[str, Any]] = {}
    for record in existing.get("products", []):
        if isinstance(record, dict) and record.get("productId") is not None:
            by_product_id[str(record["productId"])] = record
    for record in products:
        product_id = record.get("productId")
        if product_id is None:
            continue
        by_product_id[str(product_id)] = record

    failure_records = [failure for failure in existing.get("failures", []) if isinstance(failure, dict)]
    failure_seen = {json.dumps(failure, ensure_ascii=False, sort_keys=True) for failure in failure_records}
    for failure in failures:
        key = json.dumps(failure, ensure_ascii=False, sort_keys=True)
        if key in failure_seen:
            continue
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
    items: list[dict[str, Any]] = []
    for product in products:
        if len(items) >= limit:
            break
        raw = product.get("raw")
        if raw is None:
            continue
        items.append({"productId": product.get("productId"), "raw": raw})
    payload = {"collectedAt": collected_at, "items": items}
    atomic_write_json(path, payload)
    return payload


def chunked(values: list[str], size: int) -> list[list[str]]:
    if size < 1:
        raise ValueError("size must be greater than zero")
    return [values[index : index + size] for index in range(0, len(values), size)]


def _load_or_default(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    return payload if isinstance(payload, dict) else default


def _append_unique(values: Any, value: str) -> list[str]:
    result = [str(item) for item in values] if isinstance(values, list) else []
    if value not in result:
        result.append(value)
    return result


def _rank_key(record: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(record.get("collectedAt")),
        str(record.get("keyword")),
        str(record.get("market")),
        str(record.get("sort")),
        str(record.get("productId")),
    )


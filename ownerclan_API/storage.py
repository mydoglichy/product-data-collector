from __future__ import annotations

import copy
import json
import os
import time
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


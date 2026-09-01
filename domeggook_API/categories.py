from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from .api_client import DomeggookClient
from .storage import atomic_write_json


CATEGORY_CACHE_MAX_AGE_DAYS = 7
CATEGORY_CACHE_VERSION = 2


@dataclass(frozen=True)
class Category:
    code: str
    name: str
    depth: int
    path: tuple[str, ...]
    int_code: int | None = None
    locked: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "depth": self.depth,
            "path": list(self.path),
            "intCode": self.int_code,
            "locked": self.locked,
        }


def load_or_refresh_categories(
    path: Path,
    client: DomeggookClient,
    *,
    max_age_days: int = CATEGORY_CACHE_MAX_AGE_DAYS,
    dry_run: bool = False,
) -> list[Category]:
    if _is_cache_fresh(path, max_age_days=max_age_days) and _is_cache_version_current(path):
        return load_categories(path)

    payload = client.get_category_list()
    categories = parse_searchable_categories(payload)
    if not dry_run:
        atomic_write_json(
            path,
            {
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "source": "domeggook",
                "version": CATEGORY_CACHE_VERSION,
                "categories": [category.to_json() for category in categories],
            },
        )
    return categories


def load_categories(path: Path) -> list[Category]:
    with path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    raw_categories = payload.get("categories") if isinstance(payload, dict) else None
    if not isinstance(raw_categories, list):
        raise ValueError(f"categories file must contain a categories list: {path}")

    categories: list[Category] = []
    for item in raw_categories:
        if not isinstance(item, dict):
            continue
        code = _string_or_none(item.get("code"))
        name = _string_or_none(item.get("name"))
        depth = item.get("depth")
        if not code or not name or not isinstance(depth, int):
            continue
        raw_path = item.get("path")
        path_names = tuple(str(value) for value in raw_path) if isinstance(raw_path, list) else (name,)
        categories.append(
            Category(
                code=code,
                name=name,
                depth=depth,
                path=path_names,
                int_code=_int_or_none(item.get("intCode")),
                locked=_string_or_none(item.get("locked")),
            )
        )
    if not categories:
        raise ValueError(f"categories file does not contain searchable categories: {path}")
    return categories


def parse_searchable_categories(payload: dict[str, Any]) -> list[Category]:
    categories: list[Category] = []
    seen: set[str] = set()
    root = payload.get("domeggook") if isinstance(payload.get("domeggook"), dict) else payload
    for item in _as_items(root.get("items") if isinstance(root, dict) else root):
        _walk_category(item, (), categories, seen)
    if not categories:
        raise ValueError("getCategoryList response did not contain searchable categories")
    return categories


def _walk_category(
    item: Any,
    parent_path: tuple[str, ...],
    categories: list[Category],
    seen: set[str],
) -> None:
    if not isinstance(item, dict):
        return

    code = _string_or_none(item.get("code"))
    name = _string_or_none(item.get("name"))
    current_path = (*parent_path, name) if name else parent_path
    depth = _category_depth(code)
    children = _as_items(item.get("child"))
    if code and name and depth >= 2 and not children and code not in seen:
        seen.add(code)
        categories.append(
            Category(
                code=code,
                name=name,
                depth=depth,
                path=current_path,
                int_code=_int_or_none(item.get("int")),
                locked=_string_or_none(item.get("locked")),
            )
        )

    for child in children:
        _walk_category(child, current_path, categories, seen)


def _is_cache_fresh(path: Path, *, max_age_days: int) -> bool:
    if not path.exists():
        return False
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.now(timezone.utc) - modified_at < timedelta(days=max_age_days)


def _is_cache_version_current(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("version") == CATEGORY_CACHE_VERSION


def _as_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if "item" in value:
            return _as_items(value["item"])
        return [value]
    return []


def _category_depth(code: str | None) -> int:
    if not code:
        return 0
    return sum(1 for part in code.split("_") if part and part != "00")


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

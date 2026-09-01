from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..config import OwnerclanConfig
from ..workflows.discover_products import make_client
from .normalization import extract_connection_items
from ..api.queries import category_descendants_query
from ..persistence.storage import atomic_write_json, load_json_object
from .time_utils import now_iso


LOGGER = logging.getLogger("ownerclan_API.categories")
ROOT_CATEGORY_KEY = "00000000"


def load_or_refresh_leaf_categories(
    project_root: Path,
    config: OwnerclanConfig,
    *,
    refresh: bool = False,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    if not refresh:
        cached = load_leaf_categories(config.output.category_cache_path)
        if cached:
            return cached
    return refresh_leaf_categories(project_root, config, client=client)


def refresh_leaf_categories(
    project_root: Path,
    config: OwnerclanConfig,
    *,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    client = client or make_client(project_root, config)
    categories = fetch_all_categories(client, page_size=config.incremental.page_size)
    leaves = leaf_categories(categories)
    payload = {
        "source": "ownerclan",
        "rootCategoryKey": ROOT_CATEGORY_KEY,
        "collectedAt": now_iso(config.timezone),
        "totalCategoryCount": len(categories),
        "leafCategoryCount": len(leaves),
        "categories": leaves,
    }
    atomic_write_json(config.output.category_cache_path, payload)
    LOGGER.info("saved ownerclan leaf category cache count=%d path=%s", len(leaves), config.output.category_cache_path)
    return leaves


def fetch_all_categories(client: Any, *, page_size: int) -> list[dict[str, Any]]:
    categories: list[dict[str, Any]] = []
    after: str | None = None
    seen_cursors: set[str] = set()
    while True:
        data = client.graphql(category_descendants_query(first=page_size, after=after))
        root = data.get("category") if isinstance(data.get("category"), dict) else {}
        items, page_info = extract_connection_items(root, "descendants")
        categories.extend(normalize_category(item) for item in items if item.get("key"))
        next_cursor = page_info.get("endCursor")
        if not page_info.get("hasNextPage") or not next_cursor:
            break
        if str(next_cursor) in seen_cursors or next_cursor == after:
            LOGGER.warning("stopping ownerclan category pagination due to repeated cursor=%s", next_cursor)
            break
        seen_cursors.add(str(next_cursor))
        after = str(next_cursor)
    return categories


def leaf_categories(categories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    leaves = [category for category in categories if not category.get("children")]
    return sorted(leaves, key=lambda category: str(category.get("key") or ""))


def load_leaf_categories(path: Path) -> list[dict[str, Any]]:
    payload = load_json_object(path)
    categories = payload.get("categories")
    if not isinstance(categories, list):
        return []
    return [normalize_category(category) for category in categories if isinstance(category, dict) and category.get("key")]


def normalize_category(category: dict[str, Any]) -> dict[str, Any]:
    children = category.get("children") if isinstance(category.get("children"), list) else []
    return {
        "key": str(category.get("key")),
        "id": category.get("id"),
        "name": category.get("name"),
        "fullName": category.get("fullName"),
        "children": [
            {
                "key": str(child.get("key")),
                "id": child.get("id"),
                "name": child.get("name"),
            }
            for child in children
            if isinstance(child, dict) and child.get("key")
        ],
    }

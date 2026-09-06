from __future__ import annotations

import hashlib
import json
from typing import Any


def item_list_hash(items: list[str]) -> str:
    payload = json.dumps(items, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resume_index(items: list[str], state: dict[str, Any], list_hash: str) -> int:
    if state.get("trackedListHash") == list_hash:
        try:
            return min(max(int(state.get("nextIndex", 0)), 0), len(items))
        except (TypeError, ValueError):
            return 0
    last_completed = state.get("lastCompletedProductId")
    if last_completed in (None, ""):
        return 0
    try:
        return items.index(str(last_completed)) + 1
    except ValueError:
        return 0

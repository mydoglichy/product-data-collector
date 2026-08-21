from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Checkpoint:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.completed_keywords: set[str] = set()

    @classmethod
    def load(cls, path: Path) -> "Checkpoint":
        checkpoint = cls(path)
        if not path.exists():
            return checkpoint

        with path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
        completed = payload.get("completedKeywords", [])
        if isinstance(completed, list):
            checkpoint.completed_keywords = {item for item in completed if isinstance(item, str)}
        return checkpoint

    def is_completed(self, keyword: str) -> bool:
        return keyword in self.completed_keywords

    def mark_completed(self, keyword: str) -> None:
        self.completed_keywords.add(keyword)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"completedKeywords": sorted(self.completed_keywords)}
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2, sort_keys=True)
            fp.write("\n")
        tmp_path.replace(self.path)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

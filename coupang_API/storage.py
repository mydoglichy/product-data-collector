from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


class JsonlWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._seen: set[str] = set()
        self._fp = None

    def __enter__(self) -> "JsonlWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = self.path.open("x", encoding="utf-8")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fp:
            self._fp.close()

    def write_many_dedup(self, records: Iterable[dict[str, Any]]) -> int:
        written = 0
        for record in records:
            key = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if key in self._seen:
                continue
            self._seen.add(key)
            self.write(record)
            written += 1
        return written

    def write(self, record: dict[str, Any]) -> None:
        if not self._fp:
            raise RuntimeError("writer is not open")
        self._fp.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def save_raw_response(raw_dir: Path, run_stamp: str, keyword: str, payload: dict[str, Any]) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{run_stamp}_{slugify(keyword)}_raw.json"
    with path.open("x", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2, sort_keys=True)
        fp.write("\n")
    return path


def save_summary(summary_dir: Path, run_stamp: str, payload: dict[str, Any]) -> Path:
    summary_dir.mkdir(parents=True, exist_ok=True)
    path = summary_dir / f"{run_stamp}_summary.json"
    with path.open("x", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2, sort_keys=True)
        fp.write("\n")
    return path


def slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", value.strip())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:80] or "keyword"

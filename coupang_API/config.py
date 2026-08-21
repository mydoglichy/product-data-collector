from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

MAX_REQUESTS_PER_MINUTE = 50
DEFAULT_REQUESTS_PER_MINUTE = 40


@dataclass(frozen=True)
class CollectorConfig:
    limit: int = 10
    image_size: str | None = None
    srp_link_only: bool = False
    sub_id: str | None = None
    requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE


def load_config(path: Path) -> CollectorConfig:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")

    with path.open("r", encoding="utf-8") as fp:
        payload = yaml.safe_load(fp) or {}

    request = payload.get("request") or {}
    if not isinstance(request, dict):
        raise ValueError("config.yaml request must be a mapping")
    requests_per_minute = int(payload.get("requests_per_minute", DEFAULT_REQUESTS_PER_MINUTE))
    if requests_per_minute < 1:
        raise ValueError("requests_per_minute must be greater than zero")

    return CollectorConfig(
        limit=10,
        image_size=request.get("image_size"),
        srp_link_only=False,
        sub_id=request.get("sub_id"),
        requests_per_minute=min(requests_per_minute, MAX_REQUESTS_PER_MINUTE),
    )


def load_keywords(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"keywords file not found: {path}")

    seen: set[str] = set()
    keywords: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        keyword = line.strip()
        if not keyword or keyword.startswith("#"):
            continue
        if keyword in seen:
            continue
        seen.add(keyword)
        keywords.append(keyword)

    if not keywords:
        raise ValueError("keywords.txt must contain at least one keyword")
    return keywords


def load_credentials(project_root: Path) -> tuple[str, str]:
    load_dotenv(project_root / ".env", override=False)
    access_key = os.getenv("COUPANG_ACCESS_KEY")
    secret_key = os.getenv("COUPANG_SECRET_KEY")
    missing = [
        name
        for name, value in (
            ("COUPANG_ACCESS_KEY", access_key),
            ("COUPANG_SECRET_KEY", secret_key),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"missing required environment variables: {', '.join(missing)}")
    return access_key or "", secret_key or ""

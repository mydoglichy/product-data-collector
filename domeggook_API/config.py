from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


OFFICIAL_RATE_LIMIT_PER_MINUTE = 180
OFFICIAL_LIST_MAX_SIZE = 100
OFFICIAL_DETAIL_MAX_BATCH_SIZE = 100
DEFAULT_REQUESTS_PER_MINUTE = 120


@dataclass(frozen=True)
class DiscoveryConfig:
    markets: tuple[str, ...]
    sorts: dict[str, str]
    items_per_keyword: int


@dataclass(frozen=True)
class DetailsConfig:
    batch_size: int


@dataclass(frozen=True)
class RequestConfig:
    max_requests_per_minute: int
    timeout_seconds: float
    max_retries: int


@dataclass(frozen=True)
class DomeggookConfig:
    discovery: DiscoveryConfig
    details: DetailsConfig
    request: RequestConfig
    timezone: str


def load_config(path: Path) -> DomeggookConfig:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")

    with path.open("r", encoding="utf-8") as fp:
        payload = yaml.safe_load(fp) or {}
    if not isinstance(payload, dict):
        raise ValueError("config.yaml must be a mapping")

    discovery = payload.get("discovery") or {}
    details = payload.get("details") or {}
    request = payload.get("request") or {}
    for section_name, section in (("discovery", discovery), ("details", details), ("request", request)):
        if not isinstance(section, dict):
            raise ValueError(f"config.yaml {section_name} must be a mapping")

    markets = tuple(discovery.get("markets") or ("dome", "supply"))
    invalid_markets = sorted(set(markets) - {"dome", "supply"})
    if invalid_markets:
        raise ValueError(f"discovery.markets contains unsupported values: {', '.join(invalid_markets)}")

    sorts = dict(discovery.get("sorts") or {"popular": "ha", "recent": "da"})
    invalid_sorts = sorted(set(sorts.values()) - {"ha", "da"})
    if invalid_sorts:
        raise ValueError(f"discovery.sorts contains unsupported values: {', '.join(invalid_sorts)}")

    items_per_keyword = int(discovery.get("items_per_keyword", 20))
    if not 1 <= items_per_keyword <= OFFICIAL_LIST_MAX_SIZE:
        raise ValueError(f"discovery.items_per_keyword must be between 1 and {OFFICIAL_LIST_MAX_SIZE}")

    batch_size = int(details.get("batch_size", OFFICIAL_DETAIL_MAX_BATCH_SIZE))
    if not 1 <= batch_size <= OFFICIAL_DETAIL_MAX_BATCH_SIZE:
        raise ValueError(f"details.batch_size must be between 1 and {OFFICIAL_DETAIL_MAX_BATCH_SIZE}")

    max_requests = int(request.get("max_requests_per_minute", DEFAULT_REQUESTS_PER_MINUTE))
    if not 1 <= max_requests < OFFICIAL_RATE_LIMIT_PER_MINUTE:
        raise ValueError(
            f"request.max_requests_per_minute must be between 1 and {OFFICIAL_RATE_LIMIT_PER_MINUTE - 1}"
        )

    timeout = float(request.get("timeout_seconds", 20))
    if timeout <= 0:
        raise ValueError("request.timeout_seconds must be greater than zero")

    max_retries = int(request.get("max_retries", 3))
    if max_retries < 0:
        raise ValueError("request.max_retries must be zero or greater")

    return DomeggookConfig(
        discovery=DiscoveryConfig(markets=markets, sorts=sorts, items_per_keyword=items_per_keyword),
        details=DetailsConfig(batch_size=batch_size),
        request=RequestConfig(max_requests_per_minute=max_requests, timeout_seconds=timeout, max_retries=max_retries),
        timezone=str(payload.get("timezone") or "Asia/Seoul"),
    )


def load_keywords(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"keywords file not found: {path}")

    seen: set[str] = set()
    keywords: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        keyword = line.strip()
        if not keyword or keyword.startswith("#") or keyword in seen:
            continue
        seen.add(keyword)
        keywords.append(keyword)

    if not keywords:
        raise ValueError("keywords.txt must contain at least one keyword")
    return keywords


def load_api_key(project_root: Path) -> str:
    load_dotenv(project_root / ".env", override=False)
    api_key = os.getenv("DOMEGGOOK_API_KEY")
    if not api_key:
        raise RuntimeError("missing required environment variable: DOMEGGOOK_API_KEY")
    return api_key


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "domeggook_API").is_dir() and (
            (candidate / ".env").exists()
            or (candidate / ".env.example").exists()
            or (candidate / "requirements.txt").exists()
        ):
            return candidate
    return Path(__file__).resolve().parents[1]


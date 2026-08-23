from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


VALID_ENVIRONMENTS = {"sandbox", "production"}
MAX_ALL_ITEMS_FIRST = 1000


@dataclass(frozen=True)
class DiscoveryConfig:
    keyword_file: Path
    top_limit_per_keyword: int
    new_limit_per_keyword: int


@dataclass(frozen=True)
class DetailsConfig:
    batch_size: int


@dataclass(frozen=True)
class IncrementalConfig:
    page_size: int
    overlap_minutes: int
    include_item_histories: bool


@dataclass(frozen=True)
class RequestConfig:
    interval_seconds: float
    timeout_seconds: float
    max_retries: int
    retry_after_max_seconds: float


@dataclass(frozen=True)
class OutputConfig:
    tracked_products_path: Path
    output_dir: Path
    state_dir: Path
    log_dir: Path
    raw_retention_per_product: int


@dataclass(frozen=True)
class OwnerclanConfig:
    environment: str
    discovery: DiscoveryConfig
    details: DetailsConfig
    incremental: IncrementalConfig
    request: RequestConfig
    output: OutputConfig
    timezone: str


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "ownerclan_API").is_dir() and (
            (candidate / ".env").exists()
            or (candidate / ".env.example").exists()
            or (candidate / "requirements.txt").exists()
        ):
            return candidate
    return Path(__file__).resolve().parents[1]


def load_config(path: Path, project_root: Path | None = None) -> OwnerclanConfig:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    root = project_root or find_project_root(path.parent)
    with path.open("r", encoding="utf-8") as fp:
        payload = yaml.safe_load(fp) or {}
    if not isinstance(payload, dict):
        raise ValueError("config.yaml must be a mapping")

    env = str(payload.get("environment") or os.getenv("OWNERCLAN_ENV") or "production")
    if env not in VALID_ENVIRONMENTS:
        raise ValueError("environment must be sandbox or production")

    discovery = _mapping(payload, "discovery")
    details = _mapping(payload, "details")
    incremental = _mapping(payload, "incremental")
    request = _mapping(payload, "request")
    output = _mapping(payload, "output")
    timezone = str(payload.get("timezone") or "Asia/Seoul")

    keyword_file = _resolve(root, discovery.get("keyword_file") or "ownerclan_API/keywords.txt")
    top_limit = _positive_int(discovery.get("top_limit_per_keyword", 10), "discovery.top_limit_per_keyword")
    new_limit = _positive_int(discovery.get("new_limit_per_keyword", 10), "discovery.new_limit_per_keyword")
    if top_limit > MAX_ALL_ITEMS_FIRST or new_limit > MAX_ALL_ITEMS_FIRST:
        raise ValueError("discovery limits must be 1000 or less")

    batch_size = _positive_int(details.get("batch_size", 100), "details.batch_size")
    if batch_size > 5000:
        raise ValueError("details.batch_size must be 5000 or less")

    page_size = _positive_int(incremental.get("page_size", 1000), "incremental.page_size")
    if page_size > MAX_ALL_ITEMS_FIRST:
        raise ValueError("incremental.page_size must be 1000 or less")

    raw_retention = int(output.get("raw_retention_per_product", 3))
    if raw_retention < 0:
        raise ValueError("output.raw_retention_per_product must be zero or greater")

    return OwnerclanConfig(
        environment=env,
        discovery=DiscoveryConfig(
            keyword_file=keyword_file,
            top_limit_per_keyword=top_limit,
            new_limit_per_keyword=new_limit,
        ),
        details=DetailsConfig(batch_size=batch_size),
        incremental=IncrementalConfig(
            page_size=page_size,
            overlap_minutes=max(int(incremental.get("overlap_minutes", 120)), 0),
            include_item_histories=bool(incremental.get("include_item_histories", False)),
        ),
        request=RequestConfig(
            interval_seconds=max(float(request.get("interval_seconds", 1.0)), 0.0),
            timeout_seconds=_positive_float(request.get("timeout_seconds", 20), "request.timeout_seconds"),
            max_retries=max(int(request.get("max_retries", 3)), 0),
            retry_after_max_seconds=_positive_float(
                request.get("retry_after_max_seconds", 60), "request.retry_after_max_seconds"
            ),
        ),
        output=OutputConfig(
            tracked_products_path=_resolve(root, output.get("tracked_products_path") or "ownerclan_API/tracked_products.json"),
            output_dir=_resolve(root, output.get("output_dir") or "ownerclan_API/output"),
            state_dir=_resolve(root, output.get("state_dir") or "ownerclan_API/state"),
            log_dir=_resolve(root, output.get("log_dir") or "ownerclan_API/logs"),
            raw_retention_per_product=raw_retention,
        ),
        timezone=timezone,
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
        raise ValueError("keywords file must contain at least one keyword")
    return keywords


def load_credentials(project_root: Path) -> tuple[str, str]:
    load_dotenv(project_root / ".env", override=False)
    username = os.getenv("OWNERCLAN_USERNAME")
    password = os.getenv("OWNERCLAN_PASSWORD")
    if not username:
        raise RuntimeError("missing required environment variable: OWNERCLAN_USERNAME")
    if not password:
        raise RuntimeError("missing required environment variable: OWNERCLAN_PASSWORD")
    return username, password


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key) or {}
    if not isinstance(value, dict):
        raise ValueError(f"config.yaml {key} must be a mapping")
    return value


def _resolve(root: Path, value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else root / path


def _positive_int(value: Any, name: str) -> int:
    result = int(value)
    if result < 1:
        raise ValueError(f"{name} must be greater than zero")
    return result


def _positive_float(value: Any, name: str) -> float:
    result = float(value)
    if result <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return result

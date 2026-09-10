from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from postgres_storage import MAX_RAW_SAMPLE_RETENTION


VALID_ENVIRONMENTS = {"sandbox", "production"}
MAX_ALL_ITEMS_FIRST = 1000


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
    category_cache_path: Path
    state_dir: Path
    log_dir: Path
    raw_sample_limit: int


@dataclass(frozen=True)
class OwnerclanConfig:
    environment: str
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
    return Path(__file__).resolve().parents[2]


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

    incremental = _mapping(payload, "incremental")
    request = _mapping(payload, "request")
    output = _mapping(payload, "output")
    timezone = str(payload.get("timezone") or "Asia/Seoul")

    page_size = _positive_int(incremental.get("page_size", 1000), "incremental.page_size")
    if page_size > MAX_ALL_ITEMS_FIRST:
        raise ValueError("incremental.page_size must be 1000 or less")

    raw_sample_limit = int(
        output.get("raw_sample_limit", output.get("raw_retention_per_product", MAX_RAW_SAMPLE_RETENTION))
    )
    if raw_sample_limit < 0:
        raise ValueError("output.raw_sample_limit must be zero or greater")

    return OwnerclanConfig(
        environment=env,
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
            category_cache_path=_resolve(root, output.get("category_cache_path") or "ownerclan_API/data/state/categories.json"),
            state_dir=_resolve(root, output.get("state_dir") or "ownerclan_API/data/state"),
            log_dir=_resolve(root, output.get("log_dir") or "ownerclan_API/data/logs"),
            raw_sample_limit=raw_sample_limit,
        ),
        timezone=timezone,
    )


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

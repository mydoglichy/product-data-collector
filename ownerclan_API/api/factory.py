from __future__ import annotations

from pathlib import Path

from .auth import JwtProvider
from .client import OwnerclanClient
from .rate_limiter import RateLimiter
from ..config import OwnerclanConfig, load_credentials


def make_client(project_root: Path, config: OwnerclanConfig, *, rate_limiter: RateLimiter | None = None) -> OwnerclanClient:
    username, password = load_credentials(project_root)
    session = None
    provider = JwtProvider(username, password, config.environment, config.request.timeout_seconds, session=session)
    return OwnerclanClient(
        provider,
        config.environment,
        rate_limiter or RateLimiter(config.request.interval_seconds),
        config.request.timeout_seconds,
        config.request.max_retries,
        config.request.retry_after_max_seconds,
        session=session,
    )

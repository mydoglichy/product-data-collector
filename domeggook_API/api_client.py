from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import cycle
from threading import Lock
from typing import Any
from urllib.parse import urlencode

import requests

from .config import DomeggookConfig
from .rate_limiter import RateLimitWindow, RateLimiter


BASE_URL = "https://www.domeggook.com/ssl/api/"
LOGGER = logging.getLogger("domeggook_API.api_client")


class DomeggookApiError(Exception):
    pass


class DomeggookHttpError(DomeggookApiError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


class DomeggookResponseError(DomeggookApiError):
    def __init__(self, code: str | None, message: str | None) -> None:
        super().__init__(f"Domeggook API error code={code!r}, message={message!r}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ListRequest:
    market: str
    sort: str
    size: int
    keyword: str | None = None
    category_code: str | None = None


@dataclass(frozen=True)
class ApiCredential:
    label: str
    api_key: str
    rate_limiter: RateLimiter


class DomeggookClient:
    def __init__(
        self,
        api_key: str | Sequence[str],
        rate_limiter: RateLimiter | Sequence[RateLimiter],
        timeout_seconds: float = 20,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self._credentials = _build_credentials(api_key, rate_limiter)
        self._credential_cycle = cycle(self._credentials)
        self._credential_lock = Lock()
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._session = session or requests.Session()

    def get_item_list(self, request: ListRequest) -> dict[str, Any]:
        if not request.keyword and not request.category_code:
            raise ValueError("ListRequest requires keyword or category_code")
        params = {
            "ver": "4.1",
            "mode": "getItemList",
            "market": request.market,
            "om": "json",
            "so": request.sort,
            "sz": request.size,
        }
        if request.keyword:
            params["kw"] = request.keyword
        if request.category_code:
            params["ca"] = request.category_code
        return self._get(params)

    def get_item_view(self, product_ids: list[str]) -> dict[str, Any]:
        if not product_ids:
            raise ValueError("product_ids must not be empty")
        if len(product_ids) > 100:
            raise ValueError("getItemView supports at most 100 product ids per request")
        params = {
            "ver": "4.6",
            "mode": "getItemView",
            "om": "json",
            "no": ",".join(product_ids),
            "multiple": "true",
        }
        return self._get(params)

    def get_category_list(self) -> dict[str, Any]:
        params = {
            "ver": "1.0",
            "mode": "getCategoryList",
            "om": "json",
        }
        return self._get(params)

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        attempts = self._max_retries + 1
        safe_params = {key: value for key, value in params.items() if key != "aid"}
        credential = self._next_credential()
        request_params = {**params, "aid": credential.api_key}

        for attempt in range(1, attempts + 1):
            credential.rate_limiter.wait()
            url = f"{BASE_URL}?{urlencode(request_params)}"
            try:
                response = self._session.get(url, timeout=self._timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                LOGGER.warning(
                    "network failure key=%s params=%s attempt=%d error=%s",
                    credential.label,
                    safe_params,
                    attempt,
                    exc.__class__.__name__,
                )
                if attempt >= attempts:
                    raise DomeggookApiError(f"network error: {exc.__class__.__name__}") from exc
                time.sleep(min(2 ** (attempt - 1), 30))
                continue

            if response.status_code == 429 and attempt < attempts:
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                LOGGER.warning("rate limited key=%s params=%s attempt=%d status=429", credential.label, safe_params, attempt)
                time.sleep(retry_after if retry_after is not None else min(2 ** (attempt - 1), 30))
                continue

            if 500 <= response.status_code < 600 and attempt < attempts:
                LOGGER.warning(
                    "server error key=%s params=%s attempt=%d status=%d",
                    credential.label,
                    safe_params,
                    attempt,
                    response.status_code,
                )
                time.sleep(min(2 ** (attempt - 1), 30))
                continue

            if response.status_code >= 400:
                raise DomeggookHttpError(response.status_code, _safe_response_message(response))

            try:
                payload = response.json()
            except ValueError as exc:
                raise DomeggookApiError(f"invalid JSON response: HTTP {response.status_code}") from exc
            _raise_for_api_error(payload)
            return payload

        raise DomeggookApiError("request failed after retries")

    def _next_credential(self) -> ApiCredential:
        with self._credential_lock:
            return next(self._credential_cycle)


def create_domeggook_client(
    api_keys: Sequence[str],
    config: DomeggookConfig,
    session: requests.Session | None = None,
) -> DomeggookClient:
    return DomeggookClient(
        api_key=api_keys,
        rate_limiter=[create_api_key_rate_limiter(config) for _ in api_keys],
        timeout_seconds=config.request.timeout_seconds,
        max_retries=config.request.max_retries,
        session=session,
    )


def create_api_key_rate_limiter(config: DomeggookConfig) -> RateLimiter:
    return RateLimiter(
        config.request.max_requests_per_minute,
        windows=[
            RateLimitWindow(config.request.max_requests_per_minute, 60.0),
            RateLimitWindow(config.request.max_requests_per_hour, 60.0 * 60.0),
            RateLimitWindow(config.request.max_requests_per_day, 60.0 * 60.0 * 24.0),
        ],
    )


def _build_credentials(
    api_key: str | Sequence[str],
    rate_limiter: RateLimiter | Sequence[RateLimiter],
) -> list[ApiCredential]:
    api_keys = [api_key] if isinstance(api_key, str) else list(api_key)
    if not api_keys:
        raise ValueError("api_key must contain at least one key")

    rate_limiters = [rate_limiter] if isinstance(rate_limiter, RateLimiter) else list(rate_limiter)
    if len(rate_limiters) == 1 and len(api_keys) > 1:
        template = rate_limiters[0]
        rate_limiters = [
            RateLimiter(template.max_calls, template.period_seconds, windows=list(template.windows))
            for _ in api_keys
        ]
    if len(rate_limiters) != len(api_keys):
        raise ValueError("rate_limiter count must match api_key count")

    return [
        ApiCredential(label=f"KEY_{index}", api_key=key, rate_limiter=limiter)
        for index, (key, limiter) in enumerate(zip(api_keys, rate_limiters), start=1)
    ]


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None


def _safe_response_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.reason or "request failed"
    return str(payload.get("message") or payload.get("msg") or response.reason or "request failed")


def _raise_for_api_error(payload: dict[str, Any]) -> None:
    root = payload.get("domeggook") if isinstance(payload.get("domeggook"), dict) else payload
    error = root.get("error") if isinstance(root, dict) else None
    if isinstance(error, dict):
        raise DomeggookResponseError(_string_or_none(error.get("code")), _string_or_none(error.get("message") or error.get("msg")))
    if isinstance(root, dict) and str(root.get("status", "")).lower() in {"fail", "error"}:
        raise DomeggookResponseError(_string_or_none(root.get("code")), _string_or_none(root.get("message") or root.get("msg")))


def _string_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


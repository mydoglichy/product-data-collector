from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests

from .rate_limiter import RateLimiter


BASE_URL = "https://domeggook.com/ssl/api/"
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
    keyword: str
    market: str
    sort: str
    size: int


class DomeggookClient:
    def __init__(
        self,
        api_key: str,
        rate_limiter: RateLimiter,
        timeout_seconds: float = 20,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self._api_key = api_key
        self._rate_limiter = rate_limiter
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._session = session or requests.Session()

    def get_item_list(self, request: ListRequest) -> dict[str, Any]:
        params = {
            "ver": "4.1",
            "mode": "getItemList",
            "aid": self._api_key,
            "market": request.market,
            "om": "json",
            "kw": request.keyword,
            "so": request.sort,
            "sz": request.size,
        }
        return self._get(params)

    def get_item_view(self, product_ids: list[str]) -> dict[str, Any]:
        if not product_ids:
            raise ValueError("product_ids must not be empty")
        if len(product_ids) > 100:
            raise ValueError("getItemView supports at most 100 product ids per request")
        params = {
            "ver": "4.6",
            "mode": "getItemView",
            "aid": self._api_key,
            "om": "json",
            "no": ",".join(product_ids),
            "multiple": "true",
        }
        return self._get(params)

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        attempts = self._max_retries + 1
        safe_params = {key: value for key, value in params.items() if key != "aid"}

        for attempt in range(1, attempts + 1):
            self._rate_limiter.wait()
            url = f"{BASE_URL}?{urlencode(params)}"
            try:
                response = self._session.get(url, timeout=self._timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                LOGGER.warning("network failure params=%s attempt=%d error=%s", safe_params, attempt, exc.__class__.__name__)
                if attempt >= attempts:
                    raise DomeggookApiError(f"network error: {exc.__class__.__name__}") from exc
                time.sleep(min(2 ** (attempt - 1), 30))
                continue

            if response.status_code == 429 and attempt < attempts:
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                LOGGER.warning("rate limited params=%s attempt=%d status=429", safe_params, attempt)
                time.sleep(retry_after if retry_after is not None else min(2 ** (attempt - 1), 30))
                continue

            if 500 <= response.status_code < 600 and attempt < attempts:
                LOGGER.warning("server error params=%s attempt=%d status=%d", safe_params, attempt, response.status_code)
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


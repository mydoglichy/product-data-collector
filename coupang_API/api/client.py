from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import requests

from ..api.auth import generate_authorization
from ..api.rate_limiter import RateLimiter


BASE_URL = "https://api-gateway.coupang.com"
SEARCH_ENDPOINT = "/v2/providers/affiliate_open_api/apis/openapi/products/search"


class CoupangApiError(Exception):
    pass


class CoupangHttpError(CoupangApiError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


class CoupangResponseError(CoupangApiError):
    def __init__(self, r_code: str | None, r_message: str | None) -> None:
        super().__init__(f"Coupang API rCode={r_code!r}, rMessage={r_message!r}")
        self.r_code = r_code
        self.r_message = r_message


@dataclass(frozen=True)
class SearchRequest:
    keyword: str
    limit: int = 10
    image_size: str | None = None
    srp_link_only: bool = False
    sub_id: str | None = None


class CoupangPartnersClient:
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        rate_limiter: RateLimiter | None = None,
        timeout: float = 10.0,
        max_retries: int = 2,
        session: requests.Session | None = None,
    ) -> None:
        self._access_key = access_key
        self._secret_key = secret_key
        self._rate_limiter = rate_limiter or RateLimiter(max_calls=40, period_seconds=60.0)
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = session or requests.Session()

    def search_products(self, request: SearchRequest) -> dict[str, Any]:
        uri = build_search_uri(request)
        url = f"{BASE_URL}{uri}"
        attempts = self._max_retries + 1

        for attempt in range(1, attempts + 1):
            self._rate_limiter.wait()
            headers = {
                "Authorization": generate_authorization(
                    "GET",
                    uri,
                    self._access_key,
                    self._secret_key,
                )
            }

            try:
                response = self._session.get(url, headers=headers, timeout=self._timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= attempts:
                    raise CoupangApiError(f"network error: {exc.__class__.__name__}") from exc
                time.sleep(min(2 ** (attempt - 1), 5))
                continue

            if response.status_code == 429 and attempt < attempts:
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                time.sleep(retry_after if retry_after is not None else min(2 ** (attempt - 1), 5))
                continue

            if 500 <= response.status_code < 600 and attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 5))
                continue

            if response.status_code >= 400:
                raise CoupangHttpError(response.status_code, _safe_response_message(response))

            payload = response.json()
            r_code = payload.get("rCode")
            if str(r_code) != "0":
                raise CoupangResponseError(None if r_code is None else str(r_code), payload.get("rMessage"))
            return payload

        raise CoupangApiError("request failed after retries")


def build_search_uri(request: SearchRequest) -> str:
    limit = min(max(int(request.limit), 1), 10)
    params: dict[str, str | int] = {
        "keyword": request.keyword,
        "limit": limit,
    }
    if request.sub_id:
        params["subId"] = request.sub_id
    if request.image_size:
        params["imageSize"] = request.image_size
    params["srpLinkOnly"] = "true" if request.srp_link_only else "false"

    query = urlencode(params, quote_via=quote)
    return f"{SEARCH_ENDPOINT}?{query}"


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
    r_message = payload.get("rMessage")
    return str(r_message) if r_message else (response.reason or "request failed")

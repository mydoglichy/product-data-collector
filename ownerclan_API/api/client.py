from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from collector_metrics import ApiMetrics
from ..api.auth import JwtProvider
from ..api.rate_limiter import RateLimiter


API_ENDPOINTS = {
    "production": "https://api.ownerclan.com/v1/graphql",
    "sandbox": "https://api-sandbox.ownerclan.com/v1/graphql",
}
LOGGER = logging.getLogger("ownerclan_API.client")
RETRY_AFTER_BUFFER_SECONDS = 30.0
MIN_BACKOFF_SIGNAL_SECONDS = 90.0
TIMEOUT_BACKOFF_AFTER_ATTEMPT = 2


class OwnerclanApiError(Exception):
    pass


class OwnerclanAuthExpired(OwnerclanApiError):
    pass


class OwnerclanHttpError(OwnerclanApiError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


class OwnerclanGraphQLError(OwnerclanApiError):
    def __init__(self, errors: Any) -> None:
        super().__init__(f"GraphQL errors: {_summarize_errors(errors)}")
        self.errors = errors

    def looks_like_unknown_field(self) -> bool:
        text = _summarize_errors(self.errors).lower()
        return any(term in text for term in ("cannot query field", "unknown field", "did you mean"))

    def is_retryable_rate_limit(self) -> bool:
        text = _summarize_errors(self.errors).lower()
        return any(term in text for term in ("too many requests", "rate limit", "quota"))


class OwnerclanClient:
    def __init__(
        self,
        jwt_provider: JwtProvider,
        environment: str,
        rate_limiter: RateLimiter,
        timeout_seconds: float,
        max_retries: int,
        retry_after_max_seconds: float,
        session: requests.Session | None = None,
    ) -> None:
        self._jwt_provider = jwt_provider
        self._endpoint = API_ENDPOINTS[environment]
        self._rate_limiter = rate_limiter
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._retry_after_max = retry_after_max_seconds
        self._session = session or requests.Session()
        self._metrics = ApiMetrics("ownerclan", LOGGER)

    def graphql(self, query: str) -> dict[str, Any]:
        try:
            return self._graphql_once_with_retries(query, self._jwt_provider.token())
        except OwnerclanAuthExpired:
            token = self._jwt_provider.refresh()
            return self._graphql_once_with_retries(query, token, allow_auth_retry=False)

    def _graphql_once_with_retries(self, query: str, token: str, *, allow_auth_retry: bool = True) -> dict[str, Any]:
        attempts = self._max_retries + 1
        operation = _query_operation(query)
        for attempt in range(1, attempts + 1):
            self._rate_limiter.wait()
            request_started_at = time.monotonic()
            try:
                response = self._session.get(
                    self._endpoint,
                    params={"query": query},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=self._timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                duration_seconds = time.monotonic() - request_started_at
                self._metrics.record_failure(
                    operation=operation,
                    error=exc.__class__.__name__,
                    timed_out=isinstance(exc, requests.Timeout),
                    duration_seconds=duration_seconds,
                )
                LOGGER.warning("ownerclan network failure attempt=%d error=%s", attempt, exc.__class__.__name__)
                if attempt >= attempts:
                    raise OwnerclanApiError(f"network error: {exc.__class__.__name__}") from exc
                backoff_seconds = self._network_backoff_seconds(attempt, exc)
                LOGGER.warning(
                    "ownerclan network backoff attempt=%d seconds=%.1f error=%s",
                    attempt,
                    backoff_seconds,
                    exc.__class__.__name__,
                )
                time.sleep(backoff_seconds)
                continue
            duration_seconds = time.monotonic() - request_started_at

            if response.status_code == 401 and allow_auth_retry:
                self._metrics.record_failure(
                    operation=operation,
                    status_code=response.status_code,
                    error="auth_expired",
                    duration_seconds=duration_seconds,
                )
                raise OwnerclanAuthExpired("ownerclan JWT expired or unauthorized")
            if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts:
                self._metrics.record_failure(
                    operation=operation,
                    status_code=response.status_code,
                    error="transient_http",
                    duration_seconds=duration_seconds,
                )
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"), self._retry_after_max)
                if response.status_code == 429 and retry_after is None:
                    retry_after = MIN_BACKOFF_SIGNAL_SECONDS
                backoff_seconds = self._backoff_seconds(attempt, retry_after)
                LOGGER.warning(
                    "ownerclan transient HTTP status=%d attempt=%d retryAfter=%s backoffSeconds=%.1f",
                    response.status_code,
                    attempt,
                    response.headers.get("Retry-After"),
                    backoff_seconds,
                )
                time.sleep(backoff_seconds)
                continue
            try:
                payload = _json_response(response)
            except ValueError as exc:
                self._metrics.record_failure(
                    operation=operation,
                    status_code=response.status_code,
                    error="invalid_json",
                    duration_seconds=duration_seconds,
                )
                if response.status_code >= 400:
                    raise OwnerclanHttpError(response.status_code, _safe_response_message(response)) from exc
                raise OwnerclanApiError(f"invalid JSON response: HTTP {response.status_code}") from exc
            if response.status_code >= 400 and payload.get("errors"):
                self._metrics.record_failure(
                    operation=operation,
                    status_code=response.status_code,
                    error="graphql_error",
                    duration_seconds=duration_seconds,
                )
                raise OwnerclanGraphQLError(payload["errors"])
            if response.status_code >= 400:
                self._metrics.record_failure(
                    operation=operation,
                    status_code=response.status_code,
                    error="http_error",
                    duration_seconds=duration_seconds,
                )
                raise OwnerclanHttpError(response.status_code, _safe_payload_message(payload, response))
            if payload.get("errors"):
                graphql_error = OwnerclanGraphQLError(payload["errors"])
                if graphql_error.is_retryable_rate_limit() and attempt < attempts:
                    self._metrics.record_failure(
                        operation=operation,
                        status_code=response.status_code,
                        error="graphql_rate_limited",
                        duration_seconds=duration_seconds,
                    )
                    backoff_seconds = self._backoff_seconds(attempt, MIN_BACKOFF_SIGNAL_SECONDS)
                    LOGGER.warning("ownerclan GraphQL rate limited attempt=%d backoffSeconds=%.1f", attempt, backoff_seconds)
                    time.sleep(backoff_seconds)
                    continue
                self._metrics.record_failure(
                    operation=operation,
                    status_code=response.status_code,
                    error="graphql_error",
                    duration_seconds=duration_seconds,
                )
                raise graphql_error
            data = payload.get("data")
            if not isinstance(data, dict):
                self._metrics.record_failure(
                    operation=operation,
                    status_code=response.status_code,
                    error="missing_data",
                    duration_seconds=duration_seconds,
                )
                raise OwnerclanApiError("GraphQL response did not include data object")
            self._metrics.record_success(
                operation=operation,
                status_code=response.status_code,
                duration_seconds=duration_seconds,
            )
            return data
        raise OwnerclanApiError("request failed after retries")

    def _backoff_seconds(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            if retry_after >= MIN_BACKOFF_SIGNAL_SECONDS:
                return min(retry_after, self._retry_after_max)
            return min(max(retry_after + RETRY_AFTER_BUFFER_SECONDS, MIN_BACKOFF_SIGNAL_SECONDS), self._retry_after_max)
        return min(2 ** (attempt - 1), self._retry_after_max)

    def _network_backoff_seconds(self, attempt: int, exc: Exception) -> float:
        if isinstance(exc, requests.Timeout) and attempt >= TIMEOUT_BACKOFF_AFTER_ATTEMPT:
            return min(MIN_BACKOFF_SIGNAL_SECONDS, self._retry_after_max)
        return self._backoff_seconds(attempt, None)


def _retry_after_seconds(value: str | None, maximum: float) -> float | None:
    if not value:
        return None
    try:
        return min(max(float(value), 0.0), maximum)
    except ValueError:
        return None


def _safe_response_message(response: requests.Response) -> str:
    try:
        payload = _json_response(response)
    except ValueError:
        return response.reason or "request failed"
    message = payload.get("message") or payload.get("msg") or response.reason or "request failed"
    return str(message)[:300]


def _safe_payload_message(payload: dict[str, Any], response: requests.Response) -> str:
    message = payload.get("message") or payload.get("msg") or response.reason or "request failed"
    return str(message)[:300]


def _summarize_errors(errors: Any) -> str:
    if isinstance(errors, list):
        messages = []
        for error in errors[:3]:
            if isinstance(error, dict):
                messages.append(str(error.get("message") or "GraphQL error"))
            else:
                messages.append(str(error))
        return "; ".join(messages)
    return str(errors)[:300]


def _json_response(response: requests.Response) -> dict[str, Any]:
    content = getattr(response, "content", None)
    if isinstance(content, bytes) and content:
        payload = json.loads(content.decode("utf-8-sig"))
    else:
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("JSON response must be an object")
    return payload


def _query_operation(query: str) -> str:
    lowered = query.lower()
    for name in ("allitems", "itemhistories", "category"):
        if name in lowered:
            return name
    return "graphql"

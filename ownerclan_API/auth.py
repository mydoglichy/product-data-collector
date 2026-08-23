from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import requests


AUTH_ENDPOINTS = {
    "production": "https://auth.ownerclan.com/auth",
    "sandbox": "https://auth-sandbox.ownerclan.com/auth",
}
LOGGER = logging.getLogger("ownerclan_API.auth")


class OwnerclanAuthError(Exception):
    pass


class JwtProvider:
    def __init__(
        self,
        username: str,
        password: str,
        environment: str,
        timeout_seconds: float,
        session: requests.Session | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._environment = environment
        self._timeout = timeout_seconds
        self._session = session or requests.Session()
        self._token: str | None = None
        self._exp: int | None = None

    def token(self) -> str:
        if self._token and not self._expires_soon():
            return self._token
        return self.refresh()

    def refresh(self) -> str:
        endpoint = AUTH_ENDPOINTS[self._environment]
        try:
            response = self._session.post(
                endpoint,
                json={
                    "service": "ownerclan",
                    "userType": "seller",
                    "username": self._username,
                    "password": self._password,
                },
                timeout=self._timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise OwnerclanAuthError(f"authentication network error: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise OwnerclanAuthError(f"authentication failed: HTTP {response.status_code}")
        token = extract_token_response(response)
        if not token:
            raise OwnerclanAuthError("authentication response did not include a JWT")
        self._token = token
        self._exp = jwt_exp(token)
        LOGGER.info("ownerclan JWT issued exp_present=%s", self._exp is not None)
        return token

    def _expires_soon(self) -> bool:
        if self._exp is None:
            return False
        return time.time() >= self._exp - 60


def extract_token(payload: dict[str, Any]) -> str | None:
    for key in ("token", "jwt", "accessToken", "access_token", "idToken"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        return extract_token(data)
    return None


def extract_token_response(response: requests.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text if _looks_like_jwt(text) else None
    if isinstance(payload, dict):
        return extract_token(payload)
    if isinstance(payload, str) and _looks_like_jwt(payload):
        return payload
    return None


def jwt_exp(token: str) -> int | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    exp = payload.get("exp")
    return int(exp) if isinstance(exp, (int, float)) else None


def _looks_like_jwt(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 3 and all(parts[:2])


def scrub_secret(value: str) -> str:
    result = value
    for marker in ("Bearer ", "password", "token", "jwt"):
        if marker.lower() in result.lower():
            return "[REDACTED]"
    return result

import base64
import json
import logging
import time

import requests

from ownerclan_API.api.auth import JwtProvider, extract_token, extract_token_response, jwt_exp
from ownerclan_API.api.client import OwnerclanClient, OwnerclanGraphQLError
from ownerclan_API.api.rate_limiter import RateLimiter


class Response:
    def __init__(self, status_code=200, payload=None, headers=None, reason="OK", content=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.reason = reason
        self.content = content

    def json(self):
        return self._payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append(("post", url, json, timeout))
        return self.responses.pop(0)

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("get", url, params, headers, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_jwt_response_handling_extracts_token_and_exp():
    token = _jwt({"exp": int(time.time()) + 600})

    assert extract_token({"data": {"token": token}}) == token
    assert jwt_exp(token) is not None


def test_plain_text_jwt_auth_response_is_supported():
    token = _jwt({"exp": int(time.time()) + 600})

    assert extract_token_response(Response(payload=token)) == token


def test_auth_logs_do_not_expose_credentials_or_jwt(caplog):
    token = _jwt({"exp": int(time.time()) + 600})
    session = Session([Response(payload={"token": token})])
    provider = JwtProvider("seller-id", "secret-password", "production", 10, session=session)

    with caplog.at_level(logging.INFO):
        assert provider.token() == token

    logs = caplog.text
    assert "secret-password" not in logs
    assert token not in logs


def test_401_refreshes_jwt_and_retries_once():
    provider = StubProvider(["old-token", "new-token"])
    session = Session([
        Response(status_code=401, payload={"message": "expired"}),
        Response(payload={"data": {"ok": True}}),
    ])
    client = OwnerclanClient(provider, "production", RateLimiter(0), 10, 0, 60, session=session)

    assert client.graphql("query { ok }") == {"ok": True}
    assert provider.refresh_count == 1
    auth_headers = [call[3]["Authorization"] for call in session.calls if call[0] == "get"]
    assert auth_headers == ["Bearer old-token", "Bearer new-token"]


def test_graphql_http_200_errors_are_raised():
    provider = StubProvider(["token"])
    session = Session([Response(payload={"errors": [{"message": "Cannot query field items"}]})])
    client = OwnerclanClient(provider, "production", RateLimiter(0), 10, 0, 60, session=session)

    try:
        client.graphql("query { items { key } }")
    except OwnerclanGraphQLError as exc:
        assert exc.looks_like_unknown_field()
    else:
        raise AssertionError("expected GraphQL error")


def test_graphql_http_400_errors_are_raised_as_graphql_errors():
    provider = StubProvider(["token"])
    session = Session([Response(status_code=400, payload={"errors": [{"message": 'Cannot query field "items"'}]})])
    client = OwnerclanClient(provider, "production", RateLimiter(0), 10, 0, 60, session=session)

    try:
        client.graphql("query { items { key } }")
    except OwnerclanGraphQLError as exc:
        assert exc.looks_like_unknown_field()
    else:
        raise AssertionError("expected GraphQL error")


def test_graphql_too_many_requests_is_retried():
    provider = StubProvider(["token"])
    session = Session([
        Response(payload={"errors": [{"message": "Too many requests."}]}),
        Response(payload={"data": {"ok": True}}),
    ])
    client = OwnerclanClient(provider, "production", RateLimiter(0), 10, 1, 1, session=session)

    assert client.graphql("query { ok }") == {"ok": True}
    assert len([call for call in session.calls if call[0] == "get"]) == 2


def test_retry_after_60_backs_off_for_90_seconds(monkeypatch):
    sleeps = []
    monkeypatch.setattr("ownerclan_API.api.client.time.sleep", lambda seconds: sleeps.append(seconds))
    provider = StubProvider(["token"])
    session = Session([
        Response(status_code=502, headers={"Retry-After": "60"}, payload={}),
        Response(payload={"data": {"ok": True}}),
    ])
    client = OwnerclanClient(provider, "production", RateLimiter(0), 10, 1, 300, session=session)

    assert client.graphql("query { ok }") == {"ok": True}
    assert sleeps == [90.0]


def test_second_timeout_backs_off_for_90_seconds(monkeypatch):
    sleeps = []
    monkeypatch.setattr("ownerclan_API.api.client.time.sleep", lambda seconds: sleeps.append(seconds))
    provider = StubProvider(["token"])
    session = Session([
        requests.ReadTimeout(),
        requests.ReadTimeout(),
        Response(payload={"data": {"ok": True}}),
    ])
    client = OwnerclanClient(provider, "production", RateLimiter(0), 10, 2, 300, session=session)

    assert client.graphql("query { ok }") == {"ok": True}
    assert sleeps == [1, 90.0]


def test_graphql_utf8_content_is_used_before_response_text_decoding():
    provider = StubProvider(["token"])
    content = json.dumps({"data": {"name": "?곹뭹 ?곸꽭?뺣낫??蹂꾨룄 ?쒓린"}}, ensure_ascii=False).encode("utf-8")
    session = Session([Response(payload={"data": {"name": "챙혘혖챠혪혞"}}, content=content)])
    client = OwnerclanClient(provider, "production", RateLimiter(0), 10, 0, 60, session=session)

    assert client.graphql("query { item { name } }") == {"name": "?곹뭹 ?곸꽭?뺣낫??蹂꾨룄 ?쒓린"}


class StubProvider:
    def __init__(self, tokens):
        self.tokens = list(tokens)
        self.refresh_count = 0

    def token(self):
        return self.tokens[0]

    def refresh(self):
        self.refresh_count += 1
        return self.tokens[min(self.refresh_count, len(self.tokens) - 1)]


def _jwt(payload):
    header = _b64({"alg": "none", "typ": "JWT"})
    body = _b64(payload)
    return f"{header}.{body}."


def _b64(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")

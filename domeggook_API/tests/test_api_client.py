import pytest
from urllib.parse import parse_qs, urlparse

from domeggook_API.api_client import DomeggookApiError, DomeggookClient, ListRequest
from domeggook_API.rate_limiter import RateLimiter


class FakeResponse:
    status_code = 200
    headers = {}
    reason = "OK"

    def json(self):
        raise ValueError("not json")


class FakeSession:
    def get(self, url, timeout):
        return FakeResponse()


class JsonResponse:
    status_code = 200
    headers = {}
    reason = "OK"

    def json(self):
        return {"domeggook": {"list": {"item": []}}}


class RecordingSession:
    def __init__(self):
        self.aids = []

    def get(self, url, timeout):
        self.aids.append(parse_qs(urlparse(url).query)["aid"][0])
        return JsonResponse()


def test_invalid_json_response_is_wrapped_as_api_error():
    client = DomeggookClient(
        api_key="test",
        rate_limiter=RateLimiter(100, sleeper=lambda _: None),
        session=FakeSession(),
    )

    with pytest.raises(DomeggookApiError, match="invalid JSON response"):
        client.get_item_list(ListRequest(keyword="case", market="dome", sort="ha", size=1))


def test_multiple_api_keys_are_used_round_robin():
    session = RecordingSession()
    client = DomeggookClient(
        api_key=["key-1", "key-2"],
        rate_limiter=[RateLimiter(100, sleeper=lambda _: None), RateLimiter(100, sleeper=lambda _: None)],
        session=session,
    )

    for _ in range(4):
        client.get_item_list(ListRequest(keyword="case", market="dome", sort="ha", size=1))

    assert session.aids == ["key-1", "key-2", "key-1", "key-2"]

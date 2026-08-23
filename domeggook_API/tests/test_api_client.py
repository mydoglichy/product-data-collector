import pytest

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


def test_invalid_json_response_is_wrapped_as_api_error():
    client = DomeggookClient(
        api_key="test",
        rate_limiter=RateLimiter(100, sleeper=lambda _: None),
        session=FakeSession(),
    )

    with pytest.raises(DomeggookApiError, match="invalid JSON response"):
        client.get_item_list(ListRequest(keyword="case", market="dome", sort="ha", size=1))

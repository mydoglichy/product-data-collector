import pytest

from coupang_API.client import CoupangPartnersClient, CoupangResponseError, SearchRequest, build_search_uri
from coupang_API.models import parse_product_records


def test_normal_response_parsing():
    payload = {
        "rCode": "0",
        "rMessage": "OK",
        "data": {
            "landingUrl": "https://link.coupang.com/search",
            "productData": [
                {
                    "keyword": "선글라스 케이스",
                    "rank": 1,
                    "isRocket": True,
                    "isFreeShipping": False,
                    "productId": 123,
                    "productImage": "https://image",
                    "productName": "상품",
                    "productPrice": 9900,
                    "productUrl": "https://link.coupang.com/product?itemId=456&vendorItemId=789",
                }
            ],
        },
    }

    records = parse_product_records(payload, "선글라스 케이스", "2026-08-21T00:00:00Z")

    assert records == [
        {
            "api": {
                "keyword": "선글라스 케이스",
                "rank": 1,
                "isRocket": True,
                "isFreeShipping": False,
                "productId": 123,
                "itemId": "456",
                "vendorItemId": "789",
                "productImage": "https://image",
                "productName": "상품",
                "productPrice": 9900,
                "productUrl": "https://link.coupang.com/product?itemId=456&vendorItemId=789",
                "landingUrl": "https://link.coupang.com/search",
            },
            "collector": {
                "requestedKeyword": "선글라스 케이스",
                "collectedAt": "2026-08-21T00:00:00Z",
                "source": "coupang_partners_product_search",
            },
        }
    ]


class FakeResponse:
    def __init__(self, status_code, payload, headers=None, reason=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.reason = reason

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, url, headers, timeout):
        assert "Authorization" in headers
        return self.response


class NoWaitLimiter:
    def wait(self):
        return None


def test_rcode_error_handling_from_client_response():
    client = CoupangPartnersClient(
        access_key="access",
        secret_key="secret",
        rate_limiter=NoWaitLimiter(),
        session=FakeSession(FakeResponse(200, {"rCode": "ERROR", "rMessage": "bad request"})),
    )

    with pytest.raises(CoupangResponseError):
        client.search_products(SearchRequest(keyword="선글라스 케이스"))


def test_missing_fields_are_preserved_as_none_and_rank_falls_back_to_position():
    payload = {"rCode": "0", "rMessage": "OK", "data": {"productData": [{"productId": 1}]}}

    records = parse_product_records(payload, "휴대용 안경집", "2026-08-21T00:00:00Z")

    assert records[0]["api"]["productId"] == 1
    assert records[0]["api"]["itemId"] is None
    assert records[0]["api"]["vendorItemId"] is None
    assert records[0]["api"]["rank"] == 1
    assert records[0]["api"]["productName"] is None
    assert records[0]["api"]["landingUrl"] is None


def test_limit_is_capped_at_official_maximum():
    uri = build_search_uri(SearchRequest(keyword="x", limit=99))

    assert "limit=10" in uri

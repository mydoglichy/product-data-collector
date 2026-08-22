from domeggook_API.collect_product_details import collect_details
from domeggook_API.config import DetailsConfig, DiscoveryConfig, DomeggookConfig, RequestConfig
from domeggook_API.discover_products import discover
from domeggook_API.storage import atomic_write_json, load_tracked_products


class FakeClient:
    def __init__(self):
        self.list_requests = []
        self.detail_requests = []

    def get_item_list(self, request):
        self.list_requests.append(request)
        return {"domeggook": {"list": {"item": [{"no": "100"}, {"no": "200"}]}}}

    def get_item_view(self, product_ids):
        self.detail_requests.append(product_ids)
        return {"domeggook": {"item": [{"no": product_id, "title": f"상품 {product_id}"} for product_id in product_ids]}}


def test_discover_uses_all_market_and_sort_combinations_without_real_api(tmp_path):
    api_dir = tmp_path / "domeggook_API"
    api_dir.mkdir()
    (api_dir / "keywords.txt").write_text("안경 케이스\n", encoding="utf-8")
    client = FakeClient()
    config = _config()

    result = discover(tmp_path, config, client=client)

    assert len(client.list_requests) == 4
    assert result["discoveredCount"] == 8
    assert result["newProductCount"] == 2
    tracked = load_tracked_products(api_dir / "tracked_products.json")
    assert set(tracked) == {"100", "200"}
    assert tracked["100"]["markets"] == ["dome", "supply"]
    assert tracked["100"]["reasons"] == ["popular", "recent"]


def test_collect_details_batches_and_writes_snapshot_without_real_api(tmp_path):
    api_dir = tmp_path / "domeggook_API"
    api_dir.mkdir()
    atomic_write_json(
        api_dir / "tracked_products.json",
        {str(value): {"productId": str(value), "active": True} for value in range(205)},
    )
    client = FakeClient()
    config = _config()

    result = collect_details(tmp_path, config, client=client)

    assert [len(batch) for batch in client.detail_requests] == [100, 100, 5]
    assert result["successCount"] == 205
    assert result["failureCount"] == 0


def _config():
    return DomeggookConfig(
        discovery=DiscoveryConfig(markets=("dome", "supply"), sorts={"popular": "ha", "recent": "da"}, items_per_keyword=20),
        details=DetailsConfig(batch_size=100),
        request=RequestConfig(max_requests_per_minute=120, timeout_seconds=20, max_retries=3),
        timezone="Asia/Seoul",
    )


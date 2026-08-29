import json

from coupang_API import collector


class FakeClient:
    calls = []

    def __init__(self, access_key, secret_key, rate_limiter):
        self.rate_limiter = rate_limiter

    def search_products(self, request):
        self.calls.append(request)
        return {
            "rCode": "0",
            "rMessage": "OK",
            "data": {
                "landingUrl": f"https://link.coupang.com/search/{request.keyword}",
                "productData": [
                    {
                        "keyword": request.keyword,
                        "rank": 1,
                        "isRocket": True,
                        "isFreeShipping": True,
                        "productId": 100,
                        "productImage": "https://image",
                        "productName": "product",
                        "productPrice": 1000,
                        "productUrl": "https://link.coupang.com/product",
                    }
                ],
            },
        }


def test_bulk_collector_resumes_from_checkpoint_and_saves_to_postgres(tmp_path, monkeypatch):
    project_root = tmp_path
    api_dir = project_root / "coupang_API"
    api_dir.mkdir()
    (api_dir / "keywords.txt").write_text(
        "completed\n"
        "new-keyword\n"
        "new-keyword\n",
        encoding="utf-8",
    )
    (api_dir / "data" / "state").mkdir(parents=True)
    checkpoint_path = api_dir / "data" / "state" / "product_search_checkpoint.json"
    checkpoint_path.write_text(
        json.dumps({"completedKeywords": ["completed"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    FakeClient.calls = []
    saved = {"raw": [], "snapshots": []}
    monkeypatch.setattr(collector, "load_credentials", lambda root: ("access", "secret"))
    monkeypatch.setattr(collector, "CoupangPartnersClient", FakeClient)
    monkeypatch.setattr(
        collector,
        "save_product_raw_samples_if_enabled",
        lambda **kwargs: saved["raw"].append(kwargs) or 1,
    )
    monkeypatch.setattr(
        collector,
        "save_product_snapshots_if_enabled",
        lambda **kwargs: saved["snapshots"].append(kwargs) or 1,
    )

    exit_code = collector.collect_once(project_root, collector.CollectorConfig(requests_per_minute=40, raw_sample_limit=1))

    assert exit_code == 0
    assert [call.keyword for call in FakeClient.calls] == ["new-keyword"]
    assert FakeClient.calls[0].limit == 10
    assert FakeClient.calls[0].srp_link_only is False
    assert not checkpoint_path.exists()

    assert not list((api_dir / "data" / "summaries").glob("*_summary.json"))
    assert not list((api_dir / "data" / "processed").glob("*_products.jsonl"))
    assert len(saved["raw"]) == 1
    assert len(saved["snapshots"]) == 1
    product = list(saved["snapshots"][0]["products"])[0]
    assert product == {
        "collectedAt": product["collectedAt"],
        "isFreeShipping": True,
        "isRocket": True,
        "itemId": None,
        "keyword": "new-keyword",
        "productId": 100,
        "productName": "product",
        "productPrice": 1000,
        "productUrl": "https://link.coupang.com/product",
        "rank": 1,
        "vendorItemId": None,
    }
    assert "collector" not in product
    assert "landingUrl" not in product
    assert "productImage" not in product
    assert "requestedKeyword" not in product

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
                        "productName": "상품",
                        "productPrice": 1000,
                        "productUrl": "https://link.coupang.com/product",
                    }
                ],
            },
        }


def test_bulk_collector_resumes_from_checkpoint_and_writes_summary(tmp_path, monkeypatch):
    project_root = tmp_path
    api_dir = project_root / "coupang_API"
    api_dir.mkdir()
    (api_dir / "keywords.txt").write_text(
        "이미완료\n"
        "새키워드\n"
        "새키워드\n",
        encoding="utf-8",
    )
    (api_dir / "data" / "state").mkdir(parents=True)
    checkpoint_path = api_dir / "data" / "state" / "product_search_checkpoint.json"
    checkpoint_path.write_text(
        json.dumps({"completedKeywords": ["이미완료"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    FakeClient.calls = []
    monkeypatch.setattr(collector, "load_credentials", lambda root: ("access", "secret"))
    monkeypatch.setattr(collector, "CoupangPartnersClient", FakeClient)

    exit_code = collector.collect_once(project_root, collector.CollectorConfig(requests_per_minute=40, raw_sample_limit=1))

    assert exit_code == 0
    assert [call.keyword for call in FakeClient.calls] == ["새키워드"]
    assert FakeClient.calls[0].limit == 10
    assert FakeClient.calls[0].srp_link_only is False
    assert not checkpoint_path.exists()

    summary_files = list((api_dir / "data" / "summaries").glob("*_summary.json"))
    assert len(summary_files) == 1
    summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
    assert summary["totalKeywords"] == 2
    assert summary["skippedCompletedKeywords"] == 1
    assert summary["successCount"] == 1
    assert summary["failureCount"] == 0
    assert summary["collectedProductCount"] == 1
    assert summary["rawSampleLimit"] == 1
    assert summary["rawSavedCount"] == 1

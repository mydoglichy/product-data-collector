from domeggook_API.workflows.collect_product_details import collect_details
import json

from domeggook_API.config import DetailsConfig, DiscoveryConfig, DomeggookConfig, RequestConfig
from domeggook_API.workflows.discover_products import discover
from domeggook_API.persistence.storage import atomic_write_json


class FakeClient:
    def __init__(self):
        self.list_requests = []
        self.detail_requests = []
        self.category_requests = 0

    def get_item_list(self, request):
        self.list_requests.append(request)
        return {
            "domeggook": {
                "header": {"currentPage": 1, "itemsPerPage": request.size, "sort": request.sort},
                "list": {"item": [{"no": "100"}, {"no": "200"}]},
            }
        }

    def get_category_list(self):
        self.category_requests += 1
        return {
            "domeggook": {
                "items": {
                    "item": [
                        {
                            "code": "01_00_00_00_00",
                            "name": "parent",
                            "child": {"item": [{"code": "01_01_00_00_00", "name": "bag"}]},
                        }
                    ]
                }
            }
        }

    def get_item_view(self, product_ids):
        self.detail_requests.append(product_ids)
        return {"domeggook": {"item": [{"no": product_id, "title": f"product {product_id}"} for product_id in product_ids]}}


def test_discover_uses_all_market_and_sort_combinations_without_real_api(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    api_dir = tmp_path / "domeggook_API"
    api_dir.mkdir()
    saved_targets = []
    monkeypatch.setattr(
        "domeggook_API.workflows.discover_products.save_discovered_product_ids_if_enabled",
        lambda **kwargs: saved_targets.extend(kwargs["records"]) or 2,
    )
    client = FakeClient()
    config = _config()

    result = discover(tmp_path, config, client=client)

    assert client.category_requests == 1
    assert len(client.list_requests) == 6
    assert {request.category_code for request in client.list_requests} == {"01_01_00_00_00"}
    assert result["categoryCount"] == 1
    assert result["discoveredCount"] == 12
    assert result["newProductCount"] == 2
    assert {record["productId"] for record in saved_targets} == {"100", "200"}
    assert {record["categoryName"] for record in saved_targets} == {"bag"}
    assert {record["market"] for record in saved_targets} == {"dome", "supply"}
    assert {record["reason"] for record in saved_targets} == {"popular", "ranking", "recent"}


def test_discover_saves_only_ranked_sorts_with_global_rank(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    api_dir = tmp_path / "domeggook_API"
    api_dir.mkdir()
    saved_records = []

    def fake_save_search_ranks_if_enabled(**kwargs):
        saved_records.extend(kwargs["records"])
        return len(kwargs["records"])

    monkeypatch.setattr(
        "domeggook_API.workflows.discover_products.save_search_ranks_if_enabled",
        fake_save_search_ranks_if_enabled,
    )

    class PageTwoClient(FakeClient):
        def get_item_list(self, request):
            self.list_requests.append(request)
            return {
                "domeggook": {
                    "header": {"currentPage": 2, "itemsPerPage": 200, "sort": request.sort},
                    "list": {"item": [{"no": f"{request.sort}-1"}, {"no": f"{request.sort}-2"}]},
                }
            }

    config = DomeggookConfig(
        discovery=DiscoveryConfig(
            markets=("dome",),
            sorts={"popular": "ha", "ranking": "rd", "recent": "da", "price_low": "aa"},
            items_per_keyword=200,
        ),
        details=DetailsConfig(batch_size=100, raw_sample_limit=20),
        request=RequestConfig(
            max_requests_per_minute=120,
            max_requests_per_hour=9000,
            max_requests_per_day=14000,
            timeout_seconds=20,
            max_retries=3,
        ),
        timezone="Asia/Seoul",
    )

    result = discover(tmp_path, config, client=PageTwoClient())

    assert result["discoveredCount"] == 8
    assert {record["sort"] for record in saved_records} == {"ha", "rd"}
    assert [record["rank"] for record in saved_records] == [201, 202, 201, 202]
    assert not any(record["rank"] == 0 for record in saved_records)


def test_discover_uses_response_sort_for_rank_records(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    (tmp_path / "domeggook_API").mkdir()
    saved_records = []
    monkeypatch.setattr(
        "domeggook_API.workflows.discover_products.save_search_ranks_if_enabled",
        lambda **kwargs: saved_records.extend(kwargs["records"]) or len(kwargs["records"]),
    )

    class ResponseSortClient(FakeClient):
        def get_item_list(self, request):
            self.list_requests.append(request)
            return {
                "domeggook": {
                    "header": {"currentPage": 1, "itemsPerPage": 20, "sort": "rd"},
                    "list": {"item": [{"no": "100"}]},
                }
            }

    config = DomeggookConfig(
        discovery=DiscoveryConfig(markets=("dome",), sorts={"popular": "ha"}, items_per_keyword=20),
        details=DetailsConfig(batch_size=100, raw_sample_limit=20),
        request=RequestConfig(
            max_requests_per_minute=120,
            max_requests_per_hour=9000,
            max_requests_per_day=14000,
            timeout_seconds=20,
            max_retries=3,
        ),
        timezone="Asia/Seoul",
    )

    discover(tmp_path, config, client=ResponseSortClient())

    assert saved_records[0]["sort"] == "rd"
    assert saved_records[0]["requestedSort"] == "ha"


def test_discover_walks_all_list_pages_until_short_page(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    (tmp_path / "domeggook_API").mkdir()
    saved_records = []
    monkeypatch.setattr(
        "domeggook_API.workflows.discover_products.save_search_ranks_if_enabled",
        lambda **kwargs: saved_records.extend(kwargs["records"]) or len(kwargs["records"]),
    )

    class MultiPageClient(FakeClient):
        def get_item_list(self, request):
            self.list_requests.append(request)
            items_by_page = {
                1: [{"no": "100"}, {"no": "200"}],
                2: [{"no": "300"}, {"no": "400"}],
                3: [{"no": "500"}],
            }
            return {
                "domeggook": {
                    "header": {"currentPage": request.page, "itemsPerPage": 2, "sort": request.sort},
                    "list": {"item": items_by_page.get(request.page, [])},
                }
            }

    config = DomeggookConfig(
        discovery=DiscoveryConfig(markets=("dome",), sorts={"ranking": "rd"}, items_per_keyword=2),
        details=DetailsConfig(batch_size=100, raw_sample_limit=20),
        request=RequestConfig(
            max_requests_per_minute=120,
            max_requests_per_hour=9000,
            max_requests_per_day=14000,
            timeout_seconds=20,
            max_retries=3,
        ),
        timezone="Asia/Seoul",
    )
    client = MultiPageClient()

    result = discover(tmp_path, config, client=client)

    assert [request.page for request in client.list_requests] == [1, 2, 3]
    assert result["discoveredCount"] == 5
    assert [record["rank"] for record in saved_records] == [1, 2, 3, 4, 5]


def test_discover_page_limit_saves_resume_state(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    api_dir = tmp_path / "domeggook_API"
    api_dir.mkdir()
    monkeypatch.setattr("domeggook_API.workflows.discover_products.save_search_ranks_if_enabled", lambda **kwargs: 0)

    class MultiPageClient(FakeClient):
        def get_item_list(self, request):
            self.list_requests.append(request)
            return {
                "domeggook": {
                    "header": {"currentPage": request.page, "itemsPerPage": 2, "sort": request.sort},
                    "list": {"item": [{"no": f"{request.page}-1"}, {"no": f"{request.page}-2"}]},
                }
            }

    config = DomeggookConfig(
        discovery=DiscoveryConfig(markets=("dome",), sorts={"ranking": "rd"}, items_per_keyword=2),
        details=DetailsConfig(batch_size=100, raw_sample_limit=20),
        request=RequestConfig(
            max_requests_per_minute=120,
            max_requests_per_hour=9000,
            max_requests_per_day=14000,
            timeout_seconds=20,
            max_retries=3,
        ),
        timezone="Asia/Seoul",
    )
    client = MultiPageClient()

    result = discover(tmp_path, config, page_limit=1, client=client)

    assert result["pageCount"] == 1
    assert [request.page for request in client.list_requests] == [1]
    saved_state = json.loads((api_dir / "data" / "state" / "discovery-state.json").read_text(encoding="utf-8"))
    assert saved_state["nextPage"] == 2


def test_discover_runtime_limit_saves_resume_state_without_calling_api(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    api_dir = tmp_path / "domeggook_API"
    api_dir.mkdir()
    client = FakeClient()

    result = discover(tmp_path, _config(), deadline_monotonic=0, client=client)

    assert result["runtimeLimitReached"] == 1
    assert client.list_requests == []
    saved_state = json.loads((api_dir / "data" / "state" / "discovery-state.json").read_text(encoding="utf-8"))
    assert saved_state["nextPage"] == 1


def test_da_discovery_products_remain_detail_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    api_dir = tmp_path / "domeggook_API"
    api_dir.mkdir()
    client = FakeClient()
    config = DomeggookConfig(
        discovery=DiscoveryConfig(markets=("dome",), sorts={"recent": "da"}, items_per_keyword=20),
        details=DetailsConfig(batch_size=100, raw_sample_limit=20),
        request=RequestConfig(
            max_requests_per_minute=120,
            max_requests_per_hour=9000,
            max_requests_per_day=14000,
            timeout_seconds=20,
            max_retries=3,
        ),
        timezone="Asia/Seoul",
    )
    saved_targets = []
    monkeypatch.setattr(
        "domeggook_API.workflows.discover_products.save_discovered_product_ids_if_enabled",
        lambda **kwargs: saved_targets.extend(kwargs["records"]) or 2,
    )

    discover(tmp_path, config, client=client)
    monkeypatch.setattr(
        "domeggook_API.workflows.collect_product_details.discovered_product_ids",
        lambda **kwargs: sorted({str(record["productId"]) for record in saved_targets}),
    )
    result = collect_details(tmp_path, config, client=client)

    assert result["successCount"] == 2
    assert client.detail_requests == [["100", "200"]]


def test_collect_details_batches_and_writes_snapshot_without_real_api(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    api_dir = tmp_path / "domeggook_API"
    api_dir.mkdir()
    monkeypatch.setattr(
        "domeggook_API.workflows.collect_product_details.discovered_product_ids",
        lambda **kwargs: [str(value) for value in range(205)],
    )
    client = FakeClient()
    config = _config()

    result = collect_details(tmp_path, config, client=client)

    assert [len(batch) for batch in client.detail_requests] == [100, 100, 5]
    assert result["successCount"] == 205
    assert result["failureCount"] == 0


def test_discover_resumes_from_saved_page_after_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    (tmp_path / "domeggook_API").mkdir()
    monkeypatch.setattr("domeggook_API.workflows.discover_products.save_search_ranks_if_enabled", lambda **kwargs: 0)

    class FailingSecondPageClient(FakeClient):
        def get_item_list(self, request):
            self.list_requests.append(request)
            if request.page == 2:
                from domeggook_API.api.client import DomeggookApiError

                raise DomeggookApiError("temporary")
            return {
                "domeggook": {
                    "header": {"currentPage": request.page, "itemsPerPage": 2, "sort": request.sort},
                    "list": {"item": [{"no": "100"}, {"no": "200"}]},
                }
            }

    config = DomeggookConfig(
        discovery=DiscoveryConfig(markets=("dome",), sorts={"ranking": "rd"}, items_per_keyword=2),
        details=DetailsConfig(batch_size=100, raw_sample_limit=20),
        request=RequestConfig(
            max_requests_per_minute=120,
            max_requests_per_hour=9000,
            max_requests_per_day=14000,
            timeout_seconds=20,
            max_retries=3,
        ),
        timezone="Asia/Seoul",
    )
    first_client = FailingSecondPageClient()

    first_result = discover(tmp_path, config, client=first_client)

    assert first_result["failureCount"] == 1
    assert [request.page for request in first_client.list_requests] == [1, 2]

    class ResumingClient(FakeClient):
        def get_item_list(self, request):
            self.list_requests.append(request)
            return {
                "domeggook": {
                    "header": {"currentPage": request.page, "itemsPerPage": 2, "sort": request.sort},
                    "list": {"item": [{"no": "300"}]},
                }
            }

    second_client = ResumingClient()
    second_result = discover(tmp_path, config, client=second_client)

    assert second_result["failureCount"] == 0
    assert [request.page for request in second_client.list_requests] == [2]


def test_collect_details_resumes_from_saved_batch_index(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    api_dir = tmp_path / "domeggook_API"
    api_dir.mkdir()
    monkeypatch.setattr(
        "domeggook_API.workflows.collect_product_details.discovered_product_ids",
        lambda **kwargs: ["100", "200", "300"],
    )
    config = DomeggookConfig(
        discovery=DiscoveryConfig(markets=("dome",), sorts={"ranking": "rd"}, items_per_keyword=2),
        details=DetailsConfig(batch_size=2, raw_sample_limit=20),
        request=RequestConfig(
            max_requests_per_minute=120,
            max_requests_per_hour=9000,
            max_requests_per_day=14000,
            timeout_seconds=20,
            max_retries=3,
        ),
        timezone="Asia/Seoul",
    )

    class FailingSecondBatchClient(FakeClient):
        def get_item_view(self, product_ids):
            self.detail_requests.append(product_ids)
            if product_ids == ["300"]:
                from domeggook_API.api.client import DomeggookApiError

                raise DomeggookApiError("temporary")
            return {"domeggook": {"item": [{"no": product_id, "title": f"product {product_id}"} for product_id in product_ids]}}

    first_client = FailingSecondBatchClient()
    first_result = collect_details(tmp_path, config, client=first_client)

    assert first_result["failureCount"] == 1
    assert first_client.detail_requests == [["100", "200"], ["300"]]

    second_client = FakeClient()
    second_result = collect_details(tmp_path, config, client=second_client)

    assert second_result["failureCount"] == 0
    assert second_client.detail_requests == [["300"]]


def test_collect_details_runtime_limit_saves_resume_index_without_calling_api(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    api_dir = tmp_path / "domeggook_API"
    api_dir.mkdir()
    monkeypatch.setattr(
        "domeggook_API.workflows.collect_product_details.discovered_product_ids",
        lambda **kwargs: ["100", "200"],
    )
    client = FakeClient()

    result = collect_details(tmp_path, _config(), deadline_monotonic=0, client=client)

    assert result["runtimeLimitReached"] == 1
    assert client.detail_requests == []
    saved_state = json.loads((api_dir / "data" / "state" / "detail-collection-state.json").read_text(encoding="utf-8"))
    assert saved_state["nextIndex"] == 0


def _config():
    return DomeggookConfig(
        discovery=DiscoveryConfig(markets=("dome", "supply"), sorts={"popular": "ha", "ranking": "rd", "recent": "da"}, items_per_keyword=20),
        details=DetailsConfig(batch_size=100, raw_sample_limit=20),
        request=RequestConfig(
            max_requests_per_minute=120,
            max_requests_per_hour=9000,
            max_requests_per_day=14000,
            timeout_seconds=20,
            max_retries=3,
        ),
        timezone="Asia/Seoul",
    )

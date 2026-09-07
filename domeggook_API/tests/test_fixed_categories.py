import json

from domeggook_API.config import DetailsConfig, DiscoveryConfig, DomeggookConfig, RequestConfig
from domeggook_API.persistence.storage import atomic_write_json
from domeggook_API.workflows.fixed_categories import (
    _detail_state_filename,
    _discovery_state_filename,
    collect_fixed_category_products,
    save_fixed_leaf_categories,
)


class FakeClient:
    def __init__(self):
        self.category_requests = 0
        self.list_requests = []
        self.detail_requests = []

    def get_category_list(self):
        self.category_requests += 1
        return {
            "domeggook": {
                "items": {
                    "item": [
                        {
                            "code": f"{index:02d}_00_00_00_00",
                            "name": f"parent {index}",
                            "child": {
                                "item": [
                                    {
                                        "code": f"{index:02d}_01_00_00_00",
                                        "name": f"leaf {index}",
                                    }
                                ]
                            },
                        }
                        for index in range(1, 61)
                    ]
                }
            }
        }

    def get_item_list(self, request):
        self.list_requests.append(request)
        items_by_page = {
            1: [{"no": f"{request.category_code}-{request.market}-1"}, {"no": f"{request.category_code}-{request.market}-2"}],
            2: [{"no": f"{request.category_code}-{request.market}-3"}],
        }
        return {
            "domeggook": {
                "header": {"currentPage": request.page, "itemsPerPage": 2, "sort": request.sort},
                "list": {"item": items_by_page.get(request.page, [])},
            }
        }

    def get_item_view(self, product_ids):
        self.detail_requests.append(product_ids)
        return {"domeggook": {"item": [{"no": product_id, "title": f"product {product_id}"} for product_id in product_ids]}}


def test_save_fixed_leaf_categories_writes_requested_count(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    (tmp_path / "domeggook_API").mkdir()
    output_path = tmp_path / "fixed.json"

    result = save_fixed_leaf_categories(
        tmp_path,
        _config(),
        output_path=output_path,
        count=50,
        client=FakeClient(),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["savedCategoryCount"] == 50
    assert payload["categoryCount"] == 50
    assert len(payload["categories"]) == 50
    assert payload["categories"][0]["code"] == "01_01_00_00_00"
    assert payload["categories"][-1]["code"] == "60_01_00_00_00"


def test_collect_fixed_category_products_discovers_then_collects_only_fixed_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    (tmp_path / "domeggook_API").mkdir()
    category_path = tmp_path / "fixed.json"
    atomic_write_json(
        category_path,
        {
            "categories": [
                {"code": "01_01_00_00_00", "name": "leaf 1", "depth": 2, "path": ["parent 1", "leaf 1"]},
                {"code": "02_01_00_00_00", "name": "leaf 2", "depth": 2, "path": ["parent 2", "leaf 2"]},
            ]
        },
    )
    saved_targets = []
    monkeypatch.setattr(
        "domeggook_API.workflows.fixed_categories.save_discovered_product_ids_if_enabled",
        lambda **kwargs: saved_targets.extend(kwargs["records"]) or len(kwargs["records"]),
    )
    monkeypatch.setattr("domeggook_API.workflows.fixed_categories.save_search_ranks_if_enabled", lambda **kwargs: 0)
    client = FakeClient()

    result = collect_fixed_category_products(
        tmp_path,
        _config(),
        category_path=category_path,
        markets=("dome",),
        client=client,
    )

    assert [request.category_code for request in client.list_requests] == [
        "01_01_00_00_00",
        "01_01_00_00_00",
        "02_01_00_00_00",
        "02_01_00_00_00",
    ]
    assert result["discovery"]["uniqueProductCount"] == 6
    assert result["details"]["collectedProductCount"] == 6
    assert result["details"]["successCount"] == 6
    assert [len(batch) for batch in client.detail_requests] == [6]
    assert {record["reason"] for record in saved_targets} == {"fixed_category_full"}


def test_collect_fixed_category_products_limits_unique_products_per_category(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    (tmp_path / "domeggook_API").mkdir()
    category_path = tmp_path / "fixed.json"
    atomic_write_json(
        category_path,
        {
            "categories": [
                {"code": "01_01_00_00_00", "name": "leaf 1", "depth": 2, "path": ["parent 1", "leaf 1"]},
                {"code": "02_01_00_00_00", "name": "leaf 2", "depth": 2, "path": ["parent 2", "leaf 2"]},
            ]
        },
    )
    saved_targets = []
    monkeypatch.setattr(
        "domeggook_API.workflows.fixed_categories.save_discovered_product_ids_if_enabled",
        lambda **kwargs: saved_targets.extend(kwargs["records"]) or len(kwargs["records"]),
    )
    monkeypatch.setattr("domeggook_API.workflows.fixed_categories.save_search_ranks_if_enabled", lambda **kwargs: 0)
    client = FakeClient()

    result = collect_fixed_category_products(
        tmp_path,
        _config(),
        category_path=category_path,
        markets=("dome", "supply"),
        per_category_product_limit=3,
        client=client,
    )

    assert [request.category_code for request in client.list_requests] == [
        "01_01_00_00_00",
        "01_01_00_00_00",
        "02_01_00_00_00",
        "02_01_00_00_00",
    ]
    assert [request.market for request in client.list_requests] == ["dome", "dome", "dome", "dome"]
    assert result["discovery"]["perCategoryProductLimit"] == 3
    assert result["discovery"]["uniqueProductCount"] == 6
    assert result["details"]["collectedProductCount"] == 6
    assert result["details"]["successCount"] == 6
    assert {record["reason"] for record in saved_targets} == {"fixed_category_sample"}


def test_collect_fixed_category_products_discovery_only_skips_details(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    (tmp_path / "domeggook_API").mkdir()
    category_path = tmp_path / "fixed.json"
    atomic_write_json(
        category_path,
        {
            "categories": [
                {"code": "01_01_00_00_00", "name": "leaf 1", "depth": 2, "path": ["parent 1", "leaf 1"]},
            ]
        },
    )
    monkeypatch.setattr("domeggook_API.workflows.fixed_categories.save_discovered_product_ids_if_enabled", lambda **kwargs: 0)
    monkeypatch.setattr("domeggook_API.workflows.fixed_categories.save_search_ranks_if_enabled", lambda **kwargs: 0)
    client = FakeClient()

    result = collect_fixed_category_products(
        tmp_path,
        _config(),
        category_path=category_path,
        markets=("dome",),
        sort_code="da",
        per_category_product_limit=3,
        discovery_only=True,
        client=client,
    )

    assert result["discovery"]["uniqueProductCount"] == 3
    assert result["details"]["trackedCount"] == 0
    assert client.detail_requests == []


def test_fixed_category_sample_state_files_are_separate_by_sort(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_ENABLED", "false")
    (tmp_path / "domeggook_API").mkdir()
    category_path = tmp_path / "fixed.json"
    atomic_write_json(
        category_path,
        {
            "categories": [
                {"code": "01_01_00_00_00", "name": "leaf 1", "depth": 2, "path": ["parent 1", "leaf 1"]},
            ]
        },
    )
    monkeypatch.setattr("domeggook_API.workflows.fixed_categories.save_discovered_product_ids_if_enabled", lambda **kwargs: 0)
    monkeypatch.setattr("domeggook_API.workflows.fixed_categories.save_search_ranks_if_enabled", lambda **kwargs: 0)

    collect_fixed_category_products(
        tmp_path,
        _config(),
        category_path=category_path,
        markets=("dome",),
        sort_code="rd",
        per_category_product_limit=3,
        max_api_calls=1,
        client=FakeClient(),
    )
    collect_fixed_category_products(
        tmp_path,
        _config(),
        category_path=category_path,
        markets=("dome",),
        sort_code="da",
        per_category_product_limit=3,
        max_api_calls=1,
        client=FakeClient(),
    )

    state_dir = tmp_path / "domeggook_API" / "data" / "state"
    assert (state_dir / "fixed-category-discovery-rd-limit-3-state.json").exists()
    assert (state_dir / "fixed-category-discovery-da-limit-3-state.json").exists()
    assert not (state_dir / "fixed-category-discovery-limit-3-state.json").exists()


def test_fixed_category_detail_state_files_are_separate_by_sort():
    assert _detail_state_filename("rd", 200) == "fixed-category-detail-rd-limit-200-state.json"
    assert _detail_state_filename("da", 200) == "fixed-category-detail-da-limit-200-state.json"
    assert _discovery_state_filename("rd", 200) == "fixed-category-discovery-rd-limit-200-state.json"
    assert _discovery_state_filename("da", 200) == "fixed-category-discovery-da-limit-200-state.json"


def _config():
    return DomeggookConfig(
        discovery=DiscoveryConfig(markets=("dome", "supply"), sorts={"ranking": "rd"}, list_page_size=2),
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

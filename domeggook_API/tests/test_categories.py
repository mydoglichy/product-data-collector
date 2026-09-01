import os
import time

from domeggook_API.categories import load_or_refresh_categories, parse_searchable_categories


class FakeCategoryClient:
    def __init__(self):
        self.calls = 0

    def get_category_list(self):
        self.calls += 1
        return _payload("fresh")


def test_parse_searchable_categories_walks_child_tree_and_skips_large_categories():
    categories = parse_searchable_categories(_payload("leaf"))

    assert [category.code for category in categories] == ["01_01_01_00_00"]
    assert categories[0].name == "leaf"
    assert categories[0].path == ("large", "middle", "leaf")
    assert categories[0].depth == 3


def test_load_or_refresh_categories_uses_fresh_cache(tmp_path):
    path = tmp_path / "categories.json"
    path.write_text(
        '{"version":2,"categories":[{"code":"02_01_00_00_00","name":"cached","depth":2,"path":["large","cached"]}]}',
        encoding="utf-8",
    )
    client = FakeCategoryClient()

    categories = load_or_refresh_categories(path, client)

    assert client.calls == 0
    assert [category.name for category in categories] == ["cached"]


def test_load_or_refresh_categories_refreshes_legacy_cache(tmp_path):
    path = tmp_path / "categories.json"
    path.write_text(
        '{"categories":[{"code":"02_01_00_00_00","name":"cached","depth":2,"path":["large","cached"]}]}',
        encoding="utf-8",
    )
    client = FakeCategoryClient()

    categories = load_or_refresh_categories(path, client)

    assert client.calls == 1
    assert [category.name for category in categories] == ["fresh"]


def test_load_or_refresh_categories_refreshes_stale_cache(tmp_path):
    path = tmp_path / "categories.json"
    path.write_text('{"categories":[]}', encoding="utf-8")
    stale_time = time.time() - (8 * 24 * 60 * 60)
    os.utime(path, (stale_time, stale_time))
    client = FakeCategoryClient()

    categories = load_or_refresh_categories(path, client)

    assert client.calls == 1
    assert [category.name for category in categories] == ["fresh"]


def _payload(child_name):
    return {
        "domeggook": {
            "items": {
                "item": [
                    {
                        "code": "01_00_00_00_00",
                        "name": "large",
                        "child": {
                            "item": [
                                {
                                    "code": "01_01_00_00_00",
                                    "int": "101",
                                    "locked": "false",
                                    "name": "middle" if child_name == "leaf" else child_name,
                                    "child": {
                                        "item": [
                                            {
                                                "code": "01_01_01_00_00",
                                                "name": child_name,
                                            }
                                        ]
                                    }
                                    if child_name == "leaf"
                                    else None,
                                }
                            ]
                        },
                    }
                ]
            }
        }
    }

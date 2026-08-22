import pytest

from domeggook_API.config import load_config, load_keywords


def test_keywords_ignore_blank_comments_and_duplicates(tmp_path):
    path = tmp_path / "keywords.txt"
    path.write_text("\n# comment\n안경 케이스\n선글라스 케이스\n안경 케이스\n", encoding="utf-8")

    assert load_keywords(path) == ["안경 케이스", "선글라스 케이스"]


def test_config_rejects_values_above_official_maxima(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "discovery:\n"
        "  items_per_keyword: 101\n"
        "details:\n"
        "  batch_size: 100\n"
        "request:\n"
        "  max_requests_per_minute: 120\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="items_per_keyword"):
        load_config(path)


def test_config_rejects_official_rate_limit_boundary(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "discovery:\n"
        "  items_per_keyword: 20\n"
        "details:\n"
        "  batch_size: 100\n"
        "request:\n"
        "  max_requests_per_minute: 180\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="max_requests_per_minute"):
        load_config(path)


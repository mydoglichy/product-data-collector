import pytest

from domeggook_API.config import load_api_keys, load_config, load_keywords


def test_keywords_ignore_blank_comments_and_duplicates(tmp_path):
    path = tmp_path / "keywords.txt"
    path.write_text("\n# comment\n안경 케이스\n선글라스 케이스\n안경 케이스\n", encoding="utf-8")

    assert load_keywords(path) == ["안경 케이스", "선글라스 케이스"]


def test_config_rejects_values_above_official_maxima(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "discovery:\n"
        "  items_per_keyword: 201\n"
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


def test_config_rejects_daily_rate_limit_boundary(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "discovery:\n"
        "  items_per_keyword: 20\n"
        "details:\n"
        "  batch_size: 100\n"
        "request:\n"
        "  max_requests_per_minute: 120\n"
        "  max_requests_per_hour: 9000\n"
        "  max_requests_per_day: 15000\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="max_requests_per_day"):
        load_config(path)


def test_load_api_keys_uses_primary_numbered_environment_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("DOMEGGOOK_API_KEY_1", "key-1")
    monkeypatch.setenv("DOMEGGOOK_API_KEY_2", "key-2")
    monkeypatch.setenv("DOMEGGOOK_API_KEY", "legacy-key")

    assert load_api_keys(tmp_path) == ["key-1"]


def test_load_api_keys_uses_legacy_environment_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("DOMEGGOOK_API_KEY_1", raising=False)
    monkeypatch.delenv("DOMEGGOOK_API_KEY_2", raising=False)
    monkeypatch.setenv("DOMEGGOOK_API_KEY", "legacy-key")

    assert load_api_keys(tmp_path) == ["legacy-key"]


def test_load_api_keys_requires_primary_or_legacy_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DOMEGGOOK_API_KEY_1", raising=False)
    monkeypatch.delenv("DOMEGGOOK_API_KEY_2", raising=False)
    monkeypatch.delenv("DOMEGGOOK_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DOMEGGOOK_API_KEY_1"):
        load_api_keys(tmp_path)


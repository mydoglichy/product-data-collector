from coupang_API.config import load_config, load_keywords


def test_keywords_txt_ignores_blank_comments_and_deduplicates(tmp_path):
    path = tmp_path / "keywords.txt"
    path.write_text(
        "\n"
        "# comment\n"
        "선글라스 케이스\n"
        "휴대용 안경집\n"
        "선글라스 케이스\n",
        encoding="utf-8",
    )

    assert load_keywords(path) == ["선글라스 케이스", "휴대용 안경집"]


def test_requests_per_minute_defaults_to_40_and_caps_at_50(tmp_path):
    default_path = tmp_path / "default.yaml"
    default_path.write_text("request:\n  image_size: 512x512\n", encoding="utf-8")
    capped_path = tmp_path / "capped.yaml"
    capped_path.write_text("requests_per_minute: 99\nrequest: {}\n", encoding="utf-8")

    assert load_config(default_path).requests_per_minute == 40
    assert load_config(capped_path).requests_per_minute == 50


def test_config_forces_official_search_request_values(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "requests_per_minute: 30\n"
        "request:\n"
        "  limit: 5\n"
        "  srp_link_only: true\n"
        "  image_size: 512x512\n",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.limit == 10
    assert config.srp_link_only is False
    assert config.image_size == "512x512"


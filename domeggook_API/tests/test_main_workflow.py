import json

from domeggook_API.workflows.main import run


def test_run_skips_discovery_when_detail_state_is_pending(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    state_dir = tmp_path / "domeggook_API" / "data" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "detail-collection-state.json").write_text(
        json.dumps({"runCollectedAt": "2026-09-04T00:00:00+09:00", "nextIndex": 100}),
        encoding="utf-8",
    )

    calls = {"discover": 0, "details": 0}

    monkeypatch.setattr("domeggook_API.workflows.main.load_api_keys", lambda project_root: ["key"])
    monkeypatch.setattr("domeggook_API.workflows.main.create_domeggook_client", lambda api_keys, config: object())

    def fake_discover(*args, **kwargs):
        calls["discover"] += 1
        return {"failureCount": 0, "runtimeLimitReached": 0, "dailyRequestLimitReached": 0}

    def fake_collect_details(*args, **kwargs):
        calls["details"] += 1
        return {"trackedCount": 200, "successCount": 100, "failureCount": 0}

    monkeypatch.setattr("domeggook_API.workflows.main.discover", fake_discover)
    monkeypatch.setattr("domeggook_API.workflows.main.collect_details", fake_collect_details)

    result = run(tmp_path, config_path)

    assert calls == {"discover": 0, "details": 1}
    assert result["discovery"]["skippedBecauseDetailResume"] == 1
    assert result["details"]["successCount"] == 100


def test_daily_mode_collects_details_before_recent_discovery(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    calls = []

    monkeypatch.setattr("domeggook_API.workflows.main.load_api_keys", lambda project_root: ["key"])
    monkeypatch.setattr("domeggook_API.workflows.main.create_domeggook_client", lambda api_keys, config: object())

    def fake_collect_details(*args, **kwargs):
        calls.append(("details", kwargs))
        return {"trackedCount": 200, "successCount": 200, "failureCount": 0}

    def fake_discover(*args, **kwargs):
        calls.append(("recent", kwargs))
        return {
            "categoryCount": 1,
            "pageCount": 2,
            "discoveredCount": 40,
            "newProductCount": 40,
            "insertedTargetCount": 3,
            "trackedCount": 0,
            "failureCount": 0,
            "runtimeLimitReached": 0,
            "dailyRequestLimitReached": 0,
        }

    monkeypatch.setattr("domeggook_API.workflows.main.collect_details", fake_collect_details)
    monkeypatch.setattr("domeggook_API.workflows.main.discover", fake_discover)

    result = run(tmp_path, config_path, mode="daily", recent_pages_per_position=2)

    assert [name for name, _ in calls] == ["details", "recent"]
    assert calls[1][1]["allowed_reasons"] == {"recent"}
    assert calls[1][1]["max_pages_per_position"] == 2
    assert calls[1][1]["state_filename"] == "recent-discovery-state.json"
    assert result["recentDiscovery"]["insertedTargetCount"] == 3


def test_daily_mode_skips_recent_discovery_when_detail_collection_pauses(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    calls = {"recent": 0}

    monkeypatch.setattr("domeggook_API.workflows.main.load_api_keys", lambda project_root: ["key"])
    monkeypatch.setattr("domeggook_API.workflows.main.create_domeggook_client", lambda api_keys, config: object())
    monkeypatch.setattr(
        "domeggook_API.workflows.main.collect_details",
        lambda *args, **kwargs: {
            "trackedCount": 200,
            "successCount": 100,
            "failureCount": 0,
            "runtimeLimitReached": 0,
            "dailyRequestLimitReached": 1,
        },
    )

    def fake_discover(*args, **kwargs):
        calls["recent"] += 1
        return {"failureCount": 0}

    monkeypatch.setattr("domeggook_API.workflows.main.discover", fake_discover)

    result = run(tmp_path, config_path, mode="daily")

    assert calls["recent"] == 0
    assert result["recentDiscovery"]["skipReason"] == "skipped_until_detail_collection_finishes"


def _write_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
discovery:
  items_per_keyword: 20
details:
  batch_size: 100
request:
  max_requests_per_minute: 120
  max_requests_per_hour: 9000
  max_requests_per_day: 14000
  timeout_seconds: 20
  max_retries: 3
timezone: Asia/Seoul
""".strip(),
        encoding="utf-8",
    )
    return config_path

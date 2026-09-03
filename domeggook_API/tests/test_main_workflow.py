import json

from domeggook_API.workflows.main import run


def test_run_skips_discovery_when_detail_state_is_pending(tmp_path, monkeypatch):
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

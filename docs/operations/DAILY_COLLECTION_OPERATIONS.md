# Daily Collection Operations

## Goal

Every day around midnight, collect product data into PostgreSQL with separate runs per platform.

- Ownerclan: collect all products once per day. If Ownerclan temporarily rate-limits, wait and resume.
- Domeggook/Domeme: continue the full product run for up to 3 hours per day. It resumes the next day from saved state.
- Coupang: collect the configured keyword search data once per day.

In this document, "full run" means one pass over all configured products/categories for that platform.

## Recommended Commands

Run platforms separately. This keeps limits, stop conditions, and status files clear.

```powershell
python scripts\run_daily_collector.py --platform ownerclan
```

```powershell
python scripts\run_daily_collector.py --platform domeggook --domeggook-max-runtime-hours 3
```

```powershell
python scripts\run_daily_collector.py --platform coupang
```

For a lower-risk midnight schedule, stagger them instead of starting all three at the exact same second.

```text
00:00 ownerclan
00:05 domeggook
00:10 coupang
```

## Ownerclan Behavior

Default daily command settings:

- `ownerclan-workers=8`
- `ownerclan-rate-limit-retry-seconds=90`
- `ownerclan-failure-retry-seconds=60`
- `ownerclan-max-failure-restarts=50`
- `page_size=500`
- `interval_seconds=0.4`, which is about 150 total API calls per minute

The 8 workers share one global rate limiter. Worker count does not multiply the RPM.

Ownerclan stops successfully when all remaining category work is finished and there are no failures. On success, these state files are cleared:

- `ownerclan_API/data/state/category-collection-progress.json`
- `ownerclan_API/data/state/category-collection-state.json`

If a temporary rate limit happens, the collector waits and resumes from saved progress instead of treating it as "done".

## Domeggook/Domeme Behavior

Daily command:

```powershell
python scripts\run_daily_collector.py --platform domeggook --domeggook-max-runtime-hours 3
```

The 3-hour limit is now handled inside the Python workflow. When time is up, it saves the current position and exits cleanly. The next run resumes from that state.

State files:

- `domeggook_API/data/state/discovery-state.json`
- `domeggook_API/data/state/detail-collection-state.json`

When both stages finish without failure or runtime pause, those state files are cleared.

## Status Files

Each daily command writes a human-readable status file:

- `ownerclan_API/data/state/daily-run-status.json`
- `domeggook_API/data/state/daily-run-status.json`
- `coupang_API/data/state/daily-run-status.json`

Important status values:

- `completed`: this platform finished its full run for this execution.
- `paused`: the platform stopped intentionally, usually because the daily runtime limit was reached.
- `failed`: the platform hit an error that needs attention.

Important reason values:

- `all_categories_finished`: Ownerclan finished all categories.
- `runtime_limit_reached`: Domeggook stopped because the configured daily runtime ended.
- `all_domeggook_products_finished`: Domeggook finished both product discovery and detail collection.
- `all_coupang_keywords_finished`: Coupang finished configured keywords.
- `rate_limit_retry_exhausted`: Ownerclan kept hitting rate limits beyond configured retry handling.
- `failure`: general failure.

## Server Scheduling

The code now supports the stop/resume rules. The server still needs a scheduler to start the commands every day.

Use cron, systemd timers, Docker scheduler, or the hosting provider's scheduler. The scheduler should call the commands above and let each command exit on its own.

Do not use `scripts/run_collectors.py` for this daily operation. That script runs platforms as one combined sequence and currently does not pass Ownerclan's 8-worker setting.

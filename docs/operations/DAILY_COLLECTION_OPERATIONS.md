# 일일 수집 운영 문서

매일 자정 전후에 플랫폼별 수집기를 따로 실행해 PostgreSQL에 상품 master와 변경된 핵심 history를 저장합니다. 이 문서는 `scripts/run_daily_collector.py` 기준 운영값만 설명합니다.

플랫폼별 실제 순회 방식, RPM/worker, 동적 재개 구현은 [COLLECTION_METHODS.md](COLLECTION_METHODS.md)를 기준으로 봅니다.

## 권장 실행

플랫폼을 분리해서 실행합니다. 제한, 중단 사유, 상태 파일을 플랫폼별로 명확히 남기기 위해서입니다.

```powershell
python scripts\run_daily_collector.py --platform ownerclan
python scripts\run_daily_collector.py --platform domeggook
python scripts\run_daily_collector.py --platform coupang
```

동시에 시작하지 말고 몇 분 간격을 둡니다.

```text
00:00 ownerclan
00:05 domeggook
00:10 coupang
```

## 오너클랜

wrapper 기본값:

- `ownerclan-workers=8`
- `ownerclan-rate-limit-retry-seconds=90`
- `ownerclan-failure-retry-seconds=60`
- `ownerclan-max-failure-restarts=50`
- `page_size=500`
- `interval_seconds=0.4`, 전체 약 150 RPM

8개 worker는 하나의 전역 rate limiter를 공유합니다. worker 수를 늘려도 RPM이 worker 수만큼 곱해지지 않습니다.

성공 조건은 카테고리 수집과 증분 수집 모두 실패 없이 끝나는 것입니다. 카테고리 수집이 정상 완료되면 아래 파일을 정리합니다.

- `ownerclan_API/data/state/category-collection-progress.json`
- `ownerclan_API/data/state/category-collection-state.json`

rate limit 계열 오류가 발생하면 실패로 끝내지 않고 지정 시간만큼 기다린 뒤 저장된 progress 기준으로 재개합니다.

## 도매꾹/도매매

초기 상품 ID 수집은 서버 배포 전에 로컬에서 먼저 실행합니다.

```powershell
python -m domeggook_API.workflows.discover_products
```

이 결과는 PostgreSQL `product_discovery_targets`에 저장됩니다. 서버의 일일 수집은 저장된 상품 ID 상세 수집을 먼저 수행합니다.

```powershell
python scripts\run_daily_collector.py --platform domeggook
```

기본 API 예산은 `domeggook_API/config/config.yaml`의 `request.max_requests_per_day`입니다. 현재 값은 `14000`이며 공식 15000/day 한도보다 여유를 둔 값입니다.

일일 예산에 도달하면 `detail-collection-state.json`을 저장하고 `paused` 상태로 종료합니다. 다음 실행은 같은 상태에서 이어갑니다. 모든 기존 상품 상세 수집이 끝났고 API 예산이 남으면 `sort=da` 최근 등록 상품 ID를 얕게 확인해 `product_discovery_targets`에 새 상품만 보강합니다.

최근 상품 보강 기본값:

- sort: `recent` / API 코드 `da`
- pages per category/market position: `1`
- state file: `domeggook_API/data/state/recent-discovery-state.json`

최근 상품 누락이 의심될 때만 깊이를 올립니다.

```powershell
python scripts\run_daily_collector.py --platform domeggook --domeggook-recent-pages-per-position 2
```

서버 실행 시간을 강제로 제한해야 할 때만 runtime cap을 사용합니다.

```powershell
python scripts\run_daily_collector.py --platform domeggook --domeggook-max-runtime-hours 3
```

정상 완료 시 정리되는 상태 파일:

- `domeggook_API/data/state/discovery-state.json`
- `domeggook_API/data/state/detail-collection-state.json`
- `domeggook_API/data/state/recent-discovery-state.json`

## 쿠팡

`config/keywords.txt`의 keyword 검색을 1회 수행합니다.

```powershell
python scripts\run_daily_collector.py --platform coupang
```

쿠팡 수집기는 keyword별 성공 여부를 `coupang_API/data/state/product_search_checkpoint.json`에 기록하고, 모든 keyword가 성공하면 checkpoint를 삭제합니다.

## 상태 파일

각 daily command는 사람이 읽을 수 있는 상태 파일을 씁니다.

- `ownerclan_API/data/state/daily-run-status.json`
- `domeggook_API/data/state/daily-run-status.json`
- `coupang_API/data/state/daily-run-status.json`

상태값:

- `completed`: 해당 실행에서 플랫폼 full run이 끝남
- `paused`: 의도적으로 중단됨. 보통 도매꾹/도매매 API 예산 또는 runtime limit 도달
- `failed`: 확인이 필요한 실패 발생

주요 reason 값:

- `all_categories_finished`: 오너클랜 카테고리/증분 수집 완료
- `runtime_limit_reached`: 도매꾹/도매매 runtime limit 도달
- `daily_request_limit_reached`: 도매꾹/도매매 API 예산 도달
- `all_domeggook_details_finished`: 도매꾹/도매매 기존 상세 수집 완료
- `all_domeggook_details_finished_and_recent_products_checked`: 기존 상세 수집 완료 후 최근 상품 보강까지 완료
- `all_coupang_keywords_finished`: 쿠팡 keyword 수집 완료
- `rate_limit_retry_exhausted`: 오너클랜 rate limit 재시도 처리 범위를 벗어남
- `failure`: 일반 실패

## 스케줄러

코드는 중단/재개 규칙을 지원합니다. 서버에서는 cron, systemd timer, Docker scheduler, 호스팅 provider scheduler 중 하나로 위 명령을 매일 실행하면 됩니다.

`scripts/run_collectors.py`는 세 플랫폼을 한 번에 순차 실행하는 편의 스크립트입니다. daily 운영에서는 Ownerclan 8-worker 기본값과 플랫폼별 상태 관리를 명확히 쓰기 위해 `scripts/run_daily_collector.py`를 사용합니다.

# 운영 런북

매일 자정 전후에 플랫폼별 수집기를 따로 실행해 PostgreSQL에 상품 master와 변경된 핵심 history를 저장합니다. 운영 기준 명령은 `scripts/run_daily_collector.py`입니다.

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

## 전체 수집 방식

| 플랫폼 | 기본 수집 단위 | 순회 방식 | 운영 worker | 운영 속도/예산 | 재개 상태 |
| --- | --- | --- | ---: | --- | --- |
| 오너클랜 | 최하위 카테고리의 `allItems` 페이지 | 최하위 카테고리 전체 순회 후 증분 변경분 수집 | 8 | `interval_seconds=0.4`, 전체 약 150 RPM | `category-collection-progress.json`, `incremental-state.json` |
| 도매꾹/도매매 | 최하위 카테고리 + market + sort + page | discovery로 상품 ID 확보 후 상세 상품 상태 수집 | 1 | 분당 120, 시간당 9000, 일당 14000 호출 예산 | `discovery-state.json`, `detail-collection-state.json`, `recent-discovery-state.json` |
| 쿠팡 | keyword 1개당 Search API 1회 | `keywords.txt`를 순차 조회 | 1 | rolling window 40 RPM | `product_search_checkpoint.json` |

## 오너클랜

기본 실행은 카테고리 전체 수집 후 증분 수집을 이어서 실행합니다.

```powershell
python -m ownerclan_API
python -m ownerclan_API --refresh-categories
python -m ownerclan_API --category-workers 8
python scripts\run_daily_collector.py --platform ownerclan
```

운영 wrapper 기본값:

- `ownerclan-workers=8`
- `ownerclan-rate-limit-retry-seconds=90`
- `ownerclan-failure-retry-seconds=60`
- `ownerclan-max-failure-restarts=50`
- `page_size=500`
- `interval_seconds=0.4`, 전체 약 150 RPM

오너클랜은 Seller GraphQL API의 카테고리 트리를 기준으로 전체 상품을 백필합니다. `category(key: "00000000") { descendants }`로 카테고리 캐시를 만들고, children이 없는 최하위 카테고리를 key 기준으로 정렬해 `ownerclan_API/data/state/categories.json`에 저장합니다. 각 최하위 카테고리는 `allItems(first: 500, category: categoryKey, after: cursor)` cursor pagination으로 끝까지 순회합니다.

`category_workers`가 2 이상이면 여러 최하위 카테고리를 병렬 처리합니다. 모든 worker는 하나의 공유 `RateLimiter`를 사용하므로 worker 수를 늘려도 전체 API 호출 간격은 `config/config.yaml`의 `request.interval_seconds` 기준으로 제한됩니다.

병렬 진행상태는 `ownerclan_API/data/state/category-collection-progress.json`에 저장합니다. 재시작 시 완료된 카테고리를 건너뛰고 진행 중이던 카테고리는 저장된 cursor부터 이어갑니다. 카테고리 수집이 정상 완료되면 `category-collection-progress.json`과 legacy `category-collection-state.json`을 삭제합니다.

rate limit 계열 오류가 발생하면 실패로 끝내지 않고 지정 시간만큼 기다린 뒤 저장된 progress 기준으로 재개합니다. 일반 네트워크/서버 실패는 같은 카테고리를 최대 3회까지 내부 재시도하고, 그 이상 실패하면 progress 파일을 보존한 채 상위 실행 루프가 재시작합니다.

## 도매꾹/도매매

`python -m domeggook_API`의 기본 `full` 모드는 discovery를 먼저 실행한 뒤 상세 수집을 실행합니다. `--mode daily`는 운영용 흐름으로, PostgreSQL `product_discovery_targets`에 이미 저장된 상품 ID의 상세 수집을 먼저 끝내고 남은 API 예산으로 최근 등록 상품 ID를 얕게 보강합니다.

```powershell
python -m domeggook_API
python -m domeggook_API --mode daily
python -m domeggook_API --limit 1 --dry-run
python scripts\run_daily_collector.py --platform domeggook
```

초기 상품 ID 수집은 서버 배포 전에 로컬에서 먼저 실행합니다.

```powershell
python -m domeggook_API.workflows.discover_products
```

현재 설정 기준:

- discovery 대상 market: `dome`, `supply`
- 순위 저장 대상 sort: `ha`, `rd`
- 최근 상품 보강 sort: `da`
- 상세 batch size: `50`
- raw sample limit: 플랫폼별 최대 `100`개
- API 예산: 분당 `120`, 시간당 `9000`, 일당 `14000`

discovery는 `(최하위 카테고리, market, sort)` 조합을 만들고 각 조합의 list page를 끝까지 순회합니다. 발견한 상품 ID와 발견 맥락 필드는 `product_discovery_targets`에 저장하고, `ha`, `rd`처럼 순위 의미가 있는 sort의 순위 필드는 `product_search_ranks`에 저장합니다. 원본 discovery payload는 저장하지 않습니다.

상세 수집은 `product_discovery_targets`에서 active 상품 ID를 읽고 `getItemView`를 batch size 50으로 호출해 상품 master와 변경된 핵심 history를 저장합니다. `invalid_json`이 발생하면 같은 detail batch를 10초, 20초, 30초 간격으로 재시도하고, 그래도 실패할 때만 상태 파일을 남긴 뒤 멈춥니다.

일일 예산에 도달하면 `detail-collection-state.json`을 저장하고 `paused` 상태로 종료합니다. 다음 실행은 같은 상태에서 이어갑니다. 모든 기존 상품 상세 수집이 끝났고 API 예산이 남으면 `sort=da` 최근 등록 상품 ID를 position당 기본 1페이지씩 확인합니다.

최근 상품 누락이 의심될 때만 깊이를 올립니다.

```powershell
python scripts\run_daily_collector.py --platform domeggook --domeggook-recent-pages-per-position 2
```

서버 실행 시간을 강제로 제한해야 할 때만 runtime cap을 사용합니다.

```powershell
python scripts\run_daily_collector.py --platform domeggook --domeggook-max-runtime-hours 3
```

## 쿠팡

쿠팡은 카테고리 전체 순회가 아니라 쿠팡 파트너스 상품 검색 API를 keyword 단위로 조회합니다.

```powershell
python -m coupang_API
python -m coupang_API --dry-run
python scripts\run_daily_collector.py --platform coupang
python scripts\run_daily_collector.py --platform coupang --dry-run
```

`config/keywords.txt`의 keyword를 순서대로 조회하고, keyword별 성공 여부를 `coupang_API/data/state/product_search_checkpoint.json`에 기록합니다. 모든 keyword가 성공하면 checkpoint 파일은 삭제됩니다.

현재 설정 기준:

- requests per minute: `40`
- keyword당 검색 limit: `10`
- image size: `512x512`
- raw sample limit: 플랫폼별 최대 `100`개

쿠팡 파트너스 API는 HTTP 200이어도 JSON 본문의 `rCode`와 `rMessage`로 제한을 반환할 수 있습니다. client는 HTTP status만 보지 않고 응답 본문까지 검사합니다. 제한이 발생해 실패만 남으면 `daily-run-status.json`에 `failed`가 기록되고, 다음 스케줄 실행에서 checkpoint 기준으로 재시도합니다.

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

## 백필 판단 기준

오너클랜 백필은 `category_workers=8`, `page_size=500`, 전체 합산 120~150 RPM부터 시작합니다. 429, GraphQL `Too many requests`, `502/503/504 + Retry-After`가 보이면 즉시 90초 이상 쉬고 RPM을 낮춥니다.

도매꾹/도매매는 full discovery로 상품 ID를 확보한 뒤 detail-first daily 운영으로 전환합니다. fixed category sample workflow는 변화율과 신규상품 감지 테스트용이며, 운영 전체 수집과 섞이지 않도록 `reason`을 분리합니다.

```powershell
python -m domeggook_API.workflows.fixed_categories save-categories --count 50
python -m domeggook_API.workflows.fixed_categories collect --sort rd --per-category-product-limit 200 --max-runtime-hours 3
python -m domeggook_API.workflows.fixed_categories collect --sort da --per-category-product-limit 200 --discovery-only --max-runtime-hours 3
```

## 스케줄러

코드는 중단/재개 규칙을 지원합니다. 서버에서는 cron, systemd timer, Docker scheduler, 호스팅 provider scheduler 중 하나로 플랫폼별 daily command를 매일 실행하면 됩니다.

`scripts/run_collectors.py`는 세 플랫폼을 한 번에 순차 실행하는 편의 스크립트입니다. daily 운영에서는 Ownerclan 8-worker 기본값과 플랫폼별 상태 관리를 명확히 쓰기 위해 `scripts/run_daily_collector.py`를 사용합니다.

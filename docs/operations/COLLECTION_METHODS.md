# 플랫폼별 데이터 수집 방법

이 문서는 도매꾹/도매매, 오너클랜, 쿠팡 수집기가 실제로 어떤 대상을 어떤 속도로 순회하고, 중단/재개를 어떻게 동적으로 처리하는지 정리합니다. 운영 실행 기준은 `scripts/run_daily_collector.py`입니다.

## 요약

| 플랫폼 | 기본 수집 단위 | 순회 방식 | 운영 worker | 운영 속도/예산 | 재개 상태 |
|---|---|---|---:|---|---|
| 오너클랜 | 최하위 카테고리의 `allItems` 페이지 | 최하위 카테고리 전체 순회 후 증분 변경분 수집 | 8 | `interval_seconds=0.4`, 전체 약 150 RPM | `category-collection-progress.json`, `incremental-state.json` |
| 도매꾹/도매매 | 최하위 카테고리 + market + sort + page | discovery로 상품 ID 확보 후 상세 상품 상태 수집 | 1 | 분당 120, 시간당 9000, 일당 14000 호출 예산 | `discovery-state.json`, `detail-collection-state.json`, `recent-discovery-state.json` |
| 쿠팡 | keyword 1개당 Search API 1회 | `keywords.txt`를 순차 조회 | 1 | rolling window 40 RPM | `product_search_checkpoint.json` |

## 오너클랜

### 대상과 순회 방식

오너클랜은 키워드 검색이 아니라 Seller GraphQL API의 카테고리 트리를 기준으로 전체 상품을 백필합니다.

1. `category(key: "00000000") { descendants }`를 cursor pagination으로 가져옵니다.
2. `children`이 없는 항목만 최하위 카테고리로 판단합니다.
3. 최하위 카테고리를 key 기준으로 정렬해 `ownerclan_API/data/state/categories.json`에 캐시합니다.
4. 각 최하위 카테고리에 대해 `allItems(first: 500, category: categoryKey, after: cursor)`를 호출합니다.
5. `pageInfo.hasNextPage=false`이거나 `endCursor`가 없으면 해당 카테고리를 완료 처리합니다.
6. 카테고리 전체 수집이 끝나면 `sync_incremental`을 이어서 실행해 `updatedAt` 기준 변경분을 수집합니다.

`--refresh-categories`를 주면 카테고리 캐시를 새로 만들고, 없으면 기존 캐시를 사용합니다.

### RPM과 worker

운영 wrapper의 기본값은 아래와 같습니다.

```powershell
python scripts\run_daily_collector.py --platform ownerclan
```

- `ownerclan-workers=8`
- `page_size=500`
- `request.interval_seconds=0.4`
- 전체 호출 상한: 약 150 RPM
- request timeout: 15초
- request retry: 2회
- `Retry-After` 반영 최대: 300초

worker는 서로 다른 카테고리를 동시에 맡습니다. 같은 카테고리 안에서는 GraphQL cursor 때문에 페이지 순서를 지켜야 하므로 한 worker가 cursor를 따라 순차 처리합니다.

중요한 점은 8개 worker가 각각 150 RPM을 쓰는 구조가 아니라는 것입니다. `collect_by_categories_parallel()`에서 `shared_rate_limiter = RateLimiter(config.request.interval_seconds)`를 하나 만들고, 모든 worker client가 이 limiter를 공유합니다. 따라서 worker 수는 느린 카테고리, timeout, DB 저장 대기 때문에 생기는 빈 시간을 줄이는 용도이고, 전체 API 호출 간격은 공유 limiter가 직렬화합니다.

### 동적 재개와 실패 처리

병렬 수집은 `ownerclan_API/data/state/category-collection-progress.json`에 아래 정보를 계속 저장합니다.

- `runCollectedAt`: 이번 백필 run의 수집 시각
- `completedCategoryKeys`: 완료된 최하위 카테고리 key 목록
- `inProgress`: 카테고리별 다음 cursor(`after`)

각 페이지는 PostgreSQL 저장과 progress 저장을 한 묶음으로 백그라운드 저장 worker에 넘깁니다. API worker는 이전 저장 작업이 끝났는지 확인한 뒤 다음 페이지 저장을 예약하므로, 저장 완료 전 cursor만 앞서 나가서 유실되는 상황을 피합니다.

재시작 시에는 완료된 카테고리를 건너뛰고, 진행 중이던 카테고리는 저장된 `after` cursor부터 이어갑니다. rate limit 계열 오류는 `rateLimitFailureCount`를 올리고 전체 worker 소비를 멈춥니다. 상위 `ownerclan_API.workflows.main.run()`은 기본 90초 대기 후 같은 progress 파일 기준으로 재시작합니다.

일반 네트워크/서버 실패는 같은 카테고리를 최대 3회까지 내부 재시도합니다. 그 이상 실패하면 progress 파일을 보존하고 상위 실행 루프가 기본 60초 대기 후 재시작합니다. 일반 실패 자동 재시작은 wrapper 기준 최대 50회입니다. 전체 카테고리가 실패 없이 끝났을 때만 `category-collection-progress.json`과 legacy `category-collection-state.json`을 삭제합니다.

## 도매꾹/도매매

### 대상과 순회 방식

도매꾹/도매매는 discovery와 상세 수집을 분리합니다.

1. `getCategoryList`로 카테고리 트리를 가져옵니다.
2. depth 2 이상이고 child가 없는 카테고리만 검색 가능한 최하위 카테고리로 저장합니다.
3. 카테고리 캐시는 `domeggook_API/data/state/categories.json`에 저장하며, 7일 이내이고 cache version이 맞으면 재사용합니다.
4. discovery는 `(최하위 카테고리, market, sort)` 조합을 만들고 각 조합의 list page를 끝까지 순회합니다.
5. market은 `dome`, `supply`를 모두 돕니다.
6. sort는 `popular=ha`, `ranking=rd`, `recent=da`를 설정으로 갖고 있습니다.
7. 발견한 상품 ID는 PostgreSQL `product_discovery_targets`에 저장합니다.
8. `ha`, `rd`처럼 순위 의미가 있는 sort만 `product_search_ranks`에 저장합니다. `da`는 최근 등록/수정일 기준이라 ranking history로 저장하지 않습니다.

상세 수집은 `product_discovery_targets`에서 active 상품 ID를 읽고 `getItemView`를 batch size 100으로 호출해 상품 master와 변경된 핵심 history를 저장합니다.

### 운영 모드

초기 백필은 discovery를 먼저 실행합니다.

```powershell
python -m domeggook_API.workflows.discover_products
```

일일 운영은 detail-first 방식입니다.

```powershell
python scripts\run_daily_collector.py --platform domeggook
```

daily 모드는 저장된 상품 ID 상세 수집을 먼저 끝냅니다. 상세 수집이 실패하거나 일일 API 예산 또는 runtime cap에 걸리면 최근 상품 보강은 건너뜁니다. 상세 수집이 끝나고 예산이 남아 있을 때만 `recent=da` discovery를 각 카테고리/market position당 기본 1페이지만 돌려 새 상품 ID를 보강합니다.

최근 상품 누락이 의심될 때만 아래처럼 깊이를 늘립니다.

```powershell
python scripts\run_daily_collector.py --platform domeggook --domeggook-recent-pages-per-position 2
```

### RPM과 예산

현재 설정 기준은 아래와 같습니다.

- `max_requests_per_minute=120`
- `max_requests_per_hour=9000`
- `max_requests_per_day=14000`
- request timeout: 20초
- request retry: 3회
- 상세 batch size: 100

`DomeggookClient`는 API key별 `RateLimiter`를 만들고, 분/시/일 3개 rolling window를 동시에 적용합니다. API key가 여러 개면 key를 round-robin으로 선택하고 각 key에 별도 limiter가 붙습니다.

운영 run 내부에서는 별도로 `RunBudget`을 둡니다. 기본값은 `max_requests_per_day=14000`이고, `--domeggook-max-api-calls`로 이번 실행의 상한만 덮어쓸 수 있습니다. `RunBudget.can_call()`이 false가 되면 현재 위치를 상태 파일에 저장하고 `dailyRequestLimitReached=1`로 정상 중단합니다.

### 동적 재개와 실패 처리

discovery 상태는 `discovery-state.json` 또는 daily 최근 보강용 `recent-discovery-state.json`에 저장합니다.

- `runCollectedAt`
- `categoryCode`
- `market`
- `reason`
- `sort`
- `nextPage`

각 list page 저장 후 다음 page 또는 다음 position을 기록합니다. runtime cap이나 API 예산에 걸리면 마지막으로 처리하려던 position/page를 저장하고 다음 실행에서 이어갑니다.

상세 수집 상태는 `detail-collection-state.json`에 저장합니다.

- `runCollectedAt`
- `trackedListHash`
- `nextIndex`
- `lastCompletedProductId`
- `rawRemaining`

`trackedListHash`는 DB에서 읽은 상품 ID 목록의 SHA-256입니다. 같은 목록이면 `nextIndex`로 이어가고, 목록이 달라졌으면 `lastCompletedProductId` 다음 위치를 찾아 이어갑니다. 이 방식 때문에 daily 실행 중 discovery target이 보강되어도 상세 수집 재개 위치를 최대한 안정적으로 복원할 수 있습니다.

runtime cap은 `--domeggook-max-runtime-hours`로 지정합니다. deadline에 도달하면 상태 파일을 저장하고 `runtimeLimitReached=1`로 정상 중단합니다.

## 쿠팡

### 대상과 순회 방식

쿠팡은 카테고리 전체 순회가 아니라 쿠팡 파트너스 상품 검색 API를 keyword 단위로 조회합니다.

1. `coupang_API/config/keywords.txt`를 순서대로 읽습니다.
2. 완료 checkpoint에 있는 keyword는 건너뜁니다.
3. keyword 1개마다 Search API를 1회 호출합니다.
4. 현재 요청값은 `limit=10`, `imageSize=512x512`, `srpLinkOnly=false`입니다.
5. 응답의 상품 row를 정규화하고 같은 실행 안에서 `productId` 기준으로 dedupe합니다.
6. keyword 호출이 성공하면 checkpoint에 완료 표시합니다.
7. 모든 keyword가 성공하면 checkpoint 파일을 삭제합니다.

### RPM과 worker

현재 쿠팡 수집기는 단일 worker 순차 실행입니다.

- `requests_per_minute=40`
- keyword당 API 호출: 1회
- keyword당 상품 limit: 10
- raw sample limit: 3

Rate limiter는 60초 rolling window 방식입니다. 즉 40 RPM 설정은 “1.5초마다 균등 호출”이 아니라 “최근 60초 안의 호출 수를 40개 이하로 유지”하는 방식입니다. 그래서 짧은 실행에서는 초반 burst가 가능하지만, 창이 차면 가장 오래된 호출이 만료될 때까지 대기합니다.

### 제한 감지와 재개

쿠팡 파트너스 API는 HTTP 200이어도 JSON 본문의 `rCode`와 `rMessage`로 제한을 반환할 수 있습니다. 그래서 client는 HTTP status만 보지 않고 응답 본문까지 검사합니다.

성공한 keyword는 `coupang_API/data/state/product_search_checkpoint.json`에 기록합니다. 다음 실행은 성공 keyword를 건너뛰고 실패 또는 미처리 keyword부터 이어갑니다. 현재 wrapper는 쿠팡에 대해 자동 장시간 대기/재시작 루프를 두지 않습니다. 제한이 발생해 실패만 남으면 `daily-run-status.json`에 `failed`가 기록되고, 다음 스케줄 실행에서 checkpoint 기준으로 재시도합니다.

로컬 관측상 2026-09-02 테스트에서 120 RPM은 위험했고 HTTP 200 + `rCode=403` 제한이 발생했습니다. 자세한 근거는 [COUPANG_PARTNERS_RATE_LIMIT_REPORT.md](../../tests/probes/COUPANG_PARTNERS_RATE_LIMIT_REPORT.md)를 봅니다.

## 상태 파일과 완료 기준

각 플랫폼 daily wrapper는 별도 상태 파일을 씁니다.

- `ownerclan_API/data/state/daily-run-status.json`
- `domeggook_API/data/state/daily-run-status.json`
- `coupang_API/data/state/daily-run-status.json`

`completed`는 해당 플랫폼의 예정된 흐름이 끝났다는 뜻입니다. `paused`는 도매꾹/도매매처럼 API 예산 또는 runtime cap 때문에 의도적으로 멈췄고 다음 실행에서 이어갈 수 있다는 뜻입니다. `failed`는 사람이 확인해야 하는 실패입니다.

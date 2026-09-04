# Product Data Collector

쿠팡 파트너스, 오너클랜 Seller GraphQL API, 도매꾹/도매매 Open API의 상품 데이터를 수집해 PostgreSQL에 저장하는 프로젝트입니다.

이 README는 저장소의 모든 Markdown 문서 내용을 한곳에서 볼 수 있도록 통합한 운영 문서입니다. 원본 문서는 삭제하지 않고 유지합니다.

## 목차

- [프로젝트 구성](#프로젝트-구성)
- [빠른 시작](#빠른-시작)
- [일일 운영](#일일-운영)
- [플랫폼별 수집 방법](#플랫폼별-수집-방법)
- [상태 파일과 재개 규칙](#상태-파일과-재개-규칙)
- [데이터 저장 흐름](#데이터-저장-흐름)
- [DB 필드 명세](#db-필드-명세)
- [플랫폼별 데이터 매핑](#플랫폼별-데이터-매핑)
- [API 호출 제한 관측](#api-호출-제한-관측)
- [테스트](#테스트)
- [원본 문서 위치](#원본-문서-위치)

## 프로젝트 구성

- `ownerclan_API/`: 오너클랜 상품 discovery, 카테고리 수집, 상세 수집, 증분 수집
- `domeggook_API/`: 도매꾹/도매매 상품 discovery와 상세 수집
- `coupang_API/`: 쿠팡 파트너스 키워드 검색 상품 수집
- `docs/operations/`: 운영 절차, 플랫폼별 수집 흐름, 백필 노트
- `docs/schema/`: PostgreSQL 저장 흐름과 테이블 필드 명세
- `tests/probes/`: API 호출 제한 검증 스크립트와 관측 보고서
- `scripts/run_daily_collector.py`: 플랫폼별 daily 운영 wrapper
- `scripts/run_collectors.py`: 여러 플랫폼을 순차 실행하는 편의 wrapper
- `postgres_storage.py`: 공통 PostgreSQL 스키마 생성, 보강, 저장 로직
- `product_history.py`: 변경 감지 대상 필드 정규화 로직
- `shipping_fees.py`: 배송비 정규화 로직
- `collector_metrics.py`: 수집 결과/상태 메트릭 보조 로직

## 빠른 시작

의존성을 설치합니다.

```powershell
pip install -r requirements.txt
```

`.env`에 PostgreSQL과 API 인증값을 설정합니다.

```dotenv
POSTGRES_ENABLED=true
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=product_data_collector
POSTGRES_USER=collector
POSTGRES_PASSWORD=replace_with_local_password
```

로컬 PostgreSQL은 Docker Compose로 실행할 수 있습니다.

```powershell
docker compose up -d postgres
python scripts\test_postgres_connection.py
```

소량 검증 명령입니다.

```powershell
python -m ownerclan_API --refresh-categories --limit 1 --dry-run
python -m domeggook_API --limit 1 --dry-run
python -m coupang_API --dry-run
```

## 일일 운영

매일 자정 전후에 플랫폼별 수집기를 따로 실행해 PostgreSQL에 상품 snapshot을 저장합니다. 플랫폼을 분리하면 제한, 중단 사유, 상태 파일을 플랫폼별로 명확히 남길 수 있습니다.

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

Docker Compose로 DB와 수집기를 함께 실행할 수도 있습니다.

```powershell
docker compose up data-collector
```

`data-collector` 서비스는 `scripts/run_collectors.py`를 실행하며 현재 오너클랜과 도매꾹/도매매를 순서대로 수집합니다. 쿠팡은 API 제한 특성이 달라 `scripts/run_daily_collector.py --platform coupang`으로 별도 실행합니다.

운영 wrapper에서 사용하는 선택 환경변수입니다.

```dotenv
COLLECTOR_LIMIT=
COLLECTOR_DRY_RUN=false
OWNERCLAN_REFRESH_CATEGORIES=true
SKIP_OWNERCLAN=false
SKIP_DOMEGGOOK=false
```

개별 모듈 실행 명령입니다.

```powershell
python -m ownerclan_API
python -m ownerclan_API --refresh-categories
python -m ownerclan_API --category-workers 8
python -m domeggook_API
python -m domeggook_API --mode daily
python -m coupang_API
```

서버에서는 cron, systemd timer, Docker scheduler, 호스팅 provider scheduler 중 하나로 daily 명령을 매일 실행하면 됩니다.

## 플랫폼별 수집 방법

| 플랫폼 | 기본 수집 단위 | 순회 방식 | 운영 worker | 운영 속도/예산 | 재개 상태 |
| --- | --- | --- | ---: | --- | --- |
| 오너클랜 | 최하위 카테고리의 `allItems` page | 최하위 카테고리 전체 순회 후 증분 변경분 수집 | 8 | `interval_seconds=0.4`, 전체 약 150 RPM | `category-collection-progress.json`, `incremental-state.json` |
| 도매꾹/도매매 | 최하위 카테고리 + market + sort + page | discovery로 상품 ID 확보 후 상세 snapshot 수집 | 1 | 분당 120, 시간당 9000, 일당 14000 호출 예산 | `discovery-state.json`, `detail-collection-state.json`, `recent-discovery-state.json` |
| 쿠팡 | keyword 1개당 Search API 1회 | `keywords.txt`를 순차 조회 | 1 | rolling window 40 RPM | `product_search_checkpoint.json` |

### 오너클랜 수집기

오너클랜 Seller GraphQL API에서 최하위 카테고리별 상품을 순회하고 증분 변경분을 PostgreSQL에 저장합니다.

기본 실행은 카테고리 전체 수집 후 증분 수집을 이어서 실행합니다.

```powershell
python -m ownerclan_API
python -m ownerclan_API --refresh-categories
python -m ownerclan_API --category-workers 8
python -m ownerclan_API --refresh-categories --limit 1 --dry-run
python scripts\run_daily_collector.py --platform ownerclan
```

수집 흐름은 다음과 같습니다.

1. `category(key: "00000000") { descendants }`를 cursor pagination으로 가져옵니다.
2. `children`이 없는 항목만 최하위 카테고리로 판단합니다.
3. 최하위 카테고리를 key 기준으로 정렬해 `ownerclan_API/data/state/categories.json`에 캐시합니다.
4. 각 최하위 카테고리에 대해 `allItems(first: 500, category: categoryKey, after: cursor)`를 호출합니다.
5. `pageInfo.hasNextPage=false`이거나 `endCursor`가 없으면 해당 카테고리를 완료 처리합니다.
6. 상품 데이터를 공통 구조로 정규화합니다.
7. 상품 master, 가격 snapshot, 재고 snapshot, 배송비 snapshot을 PostgreSQL에 저장합니다.
8. 기존 DB 최신값과 현재 정규화 값을 비교해 변경 사항이 있으면 `product_change_history`에 기록합니다.
9. 카테고리 전체 수집이 실패 없이 끝나면 `sync_incremental`을 이어서 실행해 `updatedAt` 기준 변경분을 수집합니다.
10. 카테고리 수집이 실패하면 `sync_incremental`은 실행하지 않고 빈 incremental 결과를 반환합니다.

`--refresh-categories`를 주면 카테고리 캐시를 새로 만들고, 없으면 기존 캐시를 사용합니다.

운영 wrapper 기본값입니다.

- `ownerclan-workers=8`
- `ownerclan-rate-limit-retry-seconds=90`
- `ownerclan-failure-retry-seconds=60`
- `ownerclan-max-failure-restarts=50`
- `page_size=500`
- `interval_seconds=0.4`, 전체 약 150 RPM
- request timeout: 15초
- request retry: 2회
- `Retry-After` 반영 최대: 300초
- raw sample limit: 3

`category_workers`가 2 이상이면 여러 카테고리를 병렬 처리합니다. worker는 서로 다른 카테고리를 동시에 맡고, 같은 카테고리 안에서는 GraphQL cursor 때문에 페이지 순서를 지킵니다. 모든 worker는 하나의 공유 `RateLimiter`를 사용하므로 worker 수를 늘려도 전체 API 호출 간격은 `config/config.yaml`의 `request.interval_seconds` 기준을 공유합니다.

병렬 수집은 `ownerclan_API/data/state/category-collection-progress.json`에 아래 정보를 계속 저장합니다.

- `runCollectedAt`: 이번 백필 run의 수집 시각
- `completedCategoryKeys`: 완료된 최하위 카테고리 key 목록
- `inProgress`: 카테고리별 다음 cursor(`after`)

각 페이지는 PostgreSQL 저장과 progress 저장을 한 묶음으로 백그라운드 저장 worker에 넘깁니다. API worker는 이전 저장 작업이 끝났는지 확인한 뒤 다음 페이지 저장을 예약하므로 저장 완료 전 cursor만 앞서 나가서 유실되는 상황을 피합니다.

재시작 시에는 완료된 카테고리를 건너뛰고, 진행 중이던 카테고리는 저장된 `after` cursor부터 이어갑니다. rate limit 계열 오류는 `rateLimitFailureCount`를 올리고 전체 worker 소비를 멈춥니다. 상위 실행 루프는 기본 90초 대기 후 같은 progress 파일 기준으로 재시작합니다.

일반 네트워크/서버 실패는 같은 카테고리를 최대 3회까지 내부 재시도합니다. 그 이상 실패하면 progress 파일을 보존하고 상위 실행 루프가 기본 60초 대기 후 재시작합니다. 일반 실패 자동 재시작은 wrapper 기준 최대 50회입니다. 전체 카테고리가 실패 없이 끝났을 때만 `category-collection-progress.json`과 legacy `category-collection-state.json`을 삭제합니다.

오너클랜 상태 파일입니다.

- `ownerclan_API/data/state/categories.json`: 최하위 카테고리 캐시
- `ownerclan_API/data/state/category-collection-state.json`: 단일 worker 카테고리 수집 재개 위치
- `ownerclan_API/data/state/category-collection-progress.json`: 병렬 worker 카테고리 수집 재개 위치
- `ownerclan_API/data/state/detail-collection-state.json`: 키워드 discovery 대상 상세 수집을 직접 실행할 때의 재개 위치
- `ownerclan_API/data/state/incremental-state.json`: 증분 수집의 마지막 완전 성공 시각

`ownerclan_API.workflows.discover_products`는 키워드 기반 상품 key를 PostgreSQL `product_discovery_targets`에 저장하는 보조 workflow입니다. 기본 `python -m ownerclan_API` 경로에는 포함되지 않습니다.

### 도매꾹/도매매 수집기

도매꾹/도매매 Open API에서 상품 ID를 발견하고 상세 상품 snapshot을 PostgreSQL에 저장합니다.

```powershell
python -m domeggook_API
python -m domeggook_API --mode daily
python -m domeggook_API --limit 1 --dry-run
python scripts\run_daily_collector.py --platform domeggook
```

`python -m domeggook_API`의 기본 `full` 모드는 discovery를 먼저 실행한 뒤 상세 수집을 실행합니다. `--mode daily`는 운영용 흐름으로, PostgreSQL `product_discovery_targets`에 이미 저장된 상품 ID의 상세 수집을 먼저 끝내고 남은 API 예산으로 최근 등록 상품 ID를 얕게 보강합니다.

초기 상품 ID 수집은 서버 배포 전에 로컬에서 먼저 실행합니다.

```powershell
python -m domeggook_API.workflows.discover_products
```

full 수집 흐름입니다.

1. `getCategoryList`로 카테고리 트리를 조회합니다.
2. depth 2 이상이고 child가 없는 카테고리만 검색 가능한 최하위 카테고리로 저장합니다.
3. 카테고리 캐시는 `domeggook_API/data/state/categories.json`에 저장하며, 7일 이내이고 cache version이 맞으면 재사용합니다.
4. discovery는 `(최하위 카테고리, market, sort)` 조합을 만들고 각 조합의 list page를 끝까지 순회합니다.
5. market은 `dome`, `supply`를 모두 돕니다.
6. sort는 `popular=ha`, `ranking=rd`, `recent=da`를 설정으로 갖고 있습니다.
7. 발견한 상품 ID는 PostgreSQL `product_discovery_targets`에 저장합니다.
8. `ha`, `rd`처럼 순위 의미가 있는 sort만 `product_search_ranks`에 저장합니다.
9. `da`는 최근 등록/수정일 기준이라 ranking history로 저장하지 않습니다.
10. 상세 수집은 `product_discovery_targets`에서 active 상품 ID를 읽고 `getItemView`를 batch size 100으로 호출해 상품 snapshot을 저장합니다.

daily 수집 흐름입니다.

1. 저장된 `product_discovery_targets`의 active 상품 ID 상세 수집을 먼저 실행합니다.
2. 상세 수집이 실패하거나 일일 API 예산 또는 runtime cap에 걸리면 최근 상품 보강은 건너뜁니다.
3. 상세 수집이 끝나고 예산이 남으면 `recent=da` discovery를 각 카테고리/market position당 기본 1페이지만 돌려 새 상품 ID를 보강합니다.

최근 상품 누락이 의심될 때만 깊이를 올립니다.

```powershell
python scripts\run_daily_collector.py --platform domeggook --domeggook-recent-pages-per-position 2
```

서버 실행 시간을 강제로 제한해야 할 때만 runtime cap을 사용합니다.

```powershell
python scripts\run_daily_collector.py --platform domeggook --domeggook-max-runtime-hours 3
```

현재 설정 기준입니다.

- discovery 대상 market: `dome`, `supply`
- 순위 저장 대상 sort: `ha`, `rd`
- 최근 상품 보강 sort: `da`
- 상세 batch size: 100
- raw sample limit: 3
- `max_requests_per_minute=120`
- `max_requests_per_hour=9000`
- `max_requests_per_day=14000`
- request timeout: 20초
- request retry: 3회

`DomeggookClient`는 API key별 `RateLimiter`를 만들고, 분/시/일 3개 rolling window를 동시에 적용합니다. API key가 여러 개면 key를 round-robin으로 선택하고 각 key에 별도 limiter가 붙습니다.

운영 run 내부에서는 별도로 `RunBudget`을 둡니다. 기본값은 `max_requests_per_day=14000`이고, `--domeggook-max-api-calls`로 이번 실행의 상한만 덮어쓸 수 있습니다. `RunBudget.can_call()`이 false가 되면 현재 위치를 상태 파일에 저장하고 `dailyRequestLimitReached=1`로 정상 중단합니다.

도매꾹/도매매 상태 파일입니다.

- `domeggook_API/data/state/categories.json`: 최하위 카테고리 캐시
- `domeggook_API/data/state/discovery-state.json`: full discovery 재개 위치
- `domeggook_API/data/state/detail-collection-state.json`: 상세 수집 재개 위치
- `domeggook_API/data/state/recent-discovery-state.json`: daily 모드의 최근 상품 보강 재개 위치

상세 수집 대상 상품 ID는 JSON 파일이 아니라 PostgreSQL `product_discovery_targets`에서 읽습니다. 상태 파일은 상품 데이터 저장소가 아니라 재시작용 checkpoint입니다.

### 쿠팡 수집기

쿠팡 파트너스 상품 검색 API 결과를 수집해 PostgreSQL에 저장합니다.

```powershell
python -m coupang_API
python -m coupang_API --dry-run
python scripts\run_daily_collector.py --platform coupang
python scripts\run_daily_collector.py --platform coupang --dry-run
```

쿠팡은 카테고리 전체 순회가 아니라 쿠팡 파트너스 상품 검색 API를 keyword 단위로 조회합니다.

1. `coupang_API/config/keywords.txt`를 순서대로 읽습니다.
2. 완료 checkpoint에 있는 keyword는 건너뜁니다.
3. keyword 1개마다 Search API를 1회 호출합니다.
4. 현재 요청값은 `limit=10`, `imageSize=512x512`, `srpLinkOnly=false`입니다.
5. 응답의 상품 row를 정규화하고 같은 실행 안에서 `productId` 기준으로 dedupe합니다.
6. raw sample은 설정된 제한 개수만 `product_raw_samples`에 저장합니다.
7. 상품 master, 가격 snapshot, 배송 snapshot을 PostgreSQL에 저장합니다.
8. keyword 호출이 성공하면 checkpoint에 완료 표시합니다.
9. 모든 keyword가 성공하면 checkpoint 파일을 삭제합니다.
10. 이미 완료된 keyword만 남아 있는 재실행에서도 같은 조건이 만족되므로 checkpoint 파일을 삭제합니다.

현재 설정 기준입니다.

- requests per minute: 40
- keyword당 검색 limit: 10
- image size: `512x512`
- raw sample limit: 3
- 단일 worker 순차 실행

Rate limiter는 60초 rolling window 방식입니다. 즉 40 RPM 설정은 1.5초마다 균등 호출하는 방식이 아니라 최근 60초 안의 호출 수를 40개 이하로 유지하는 방식입니다. 그래서 짧은 실행에서는 초반 burst가 가능하지만, 창이 차면 가장 오래된 호출이 만료될 때까지 대기합니다.

쿠팡 파트너스 API는 HTTP 200이어도 JSON 본문의 `rCode`와 `rMessage`로 제한을 반환할 수 있습니다. client는 HTTP status만 보지 않고 응답 본문까지 검사합니다. keyword가 하나라도 실패하면 실행 결과를 실패 exit code로 반환합니다.

`--dry-run`은 checkpoint를 읽어서 완료 keyword를 건너뛰지만 checkpoint 파일을 생성, 갱신, 삭제하지 않습니다. API 호출과 파싱까지 수행하지만 raw sample, 상품 snapshot도 저장하지 않습니다.

쿠팡 상태 파일입니다.

- `coupang_API/data/state/product_search_checkpoint.json`: 완료 keyword checkpoint

## 상태 파일과 재개 규칙

각 daily command는 사람이 읽을 수 있는 상태 파일을 씁니다.

- `ownerclan_API/data/state/daily-run-status.json`
- `domeggook_API/data/state/daily-run-status.json`
- `coupang_API/data/state/daily-run-status.json`

상태값입니다.

- `completed`: 해당 실행에서 플랫폼 full run이 끝남
- `paused`: 의도적으로 중단됨. 보통 도매꾹/도매매 API 예산 또는 runtime limit 도달
- `failed`: 확인이 필요한 실패 발생

주요 reason 값입니다.

- `all_categories_finished`: 오너클랜 카테고리/증분 수집 완료
- `runtime_limit_reached`: 도매꾹/도매매 runtime limit 도달
- `daily_request_limit_reached`: 도매꾹/도매매 API 예산 도달
- `all_domeggook_details_finished`: 도매꾹/도매매 기존 상세 수집 완료
- `all_domeggook_details_finished_and_recent_products_checked`: 기존 상세 수집 완료 후 최근 상품 보강까지 완료
- `all_coupang_keywords_finished`: 쿠팡 keyword 수집 완료
- `rate_limit_retry_exhausted`: 오너클랜 rate limit 재시도 처리 범위를 벗어남
- `failure`: 일반 실패

공통 원칙은 PostgreSQL 저장이 성공한 뒤 checkpoint를 갱신하는 것입니다. 정상 완료된 재개 상태 파일은 삭제되고, 남아 있는 상태 파일은 다음 실행에서 저장 완료 지점 이후부터 재개하는 데 사용됩니다.

## 데이터 저장 흐름

현재 운영 저장소는 PostgreSQL입니다. 스키마 생성과 기존 DB 보강은 `postgres_storage.py`의 `init_schema()`에서 수행합니다.

공통 저장 흐름입니다.

1. 플랫폼별 parser/normalizer가 API 응답을 공통 상품 구조로 정규화합니다.
2. `save_product_snapshots_if_enabled()`가 상품 master, 가격, 재고, 배송비, 최신 비교 필드, 변경 이력을 저장합니다.
3. `save_product_raw_samples_if_enabled()`가 제한된 raw 샘플만 `product_raw_samples`에 저장합니다.
4. `save_search_ranks_if_enabled()`가 순위 의미가 있는 discovery 결과만 `product_search_ranks`에 저장합니다.
5. `save_discovered_product_ids_if_enabled()`가 상세 수집 대상 상품 ID를 `product_discovery_targets`에 저장합니다.

최신 API 응답 전체 JSON이나 비교용 JSON은 `products`에 저장하지 않습니다. 변경 감지는 `products`의 scalar 컬럼과 최신 가격/재고/배송 snapshot row를 기준으로 처리합니다.

수집 시 현재 정규화 값과 기존 DB 최신값을 비교합니다. 값이 바뀌면 `product_change_history`에 `changed_fields`만 남깁니다.

가격, 재고, 배송비 snapshot은 변경 여부와 무관하게 각 snapshot 테이블에 수집 시점별로 저장합니다. `product_change_history`는 주요 필드가 바뀐 시점을 빠르게 찾기 위한 보조 이력입니다.

API 원본 전체 보관은 하지 않습니다. 디버깅용으로 각 실행에서 제한된 개수만 `product_raw_samples`에 저장합니다.

## DB 필드 명세

### 주요 테이블

- `products`: 플랫폼별 상품 master와 최신 조회용 scalar 값
- `product_prices`: 수집 시점별 가격 snapshot
- `product_inventory`: 수집 시점별 재고 snapshot
- `product_shipping_fees`: 수집 시점별 배송비 snapshot
- `product_change_history`: `products` scalar 값과 최신 snapshot row 비교 결과
- `product_raw_samples`: 디버깅용 제한 raw sample
- `product_search_ranks`: 순위 의미가 있는 검색/discovery 이력
- `product_discovery_targets`: 상세 수집 대상으로 사용할 상품 ID 목록

### `products`

상품 master와 최신 조회용 scalar 값을 저장합니다. 최신 API 응답 전체나 비교용 JSON payload는 저장하지 않습니다.

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | PK |
| `platform` | `TEXT` | No | 수집 플랫폼. 예: `coupang`, `ownerclan`, `domeggook` |
| `external_product_id` | `TEXT` | No | 플랫폼 원본 상품 ID |
| `product_name` | `TEXT` | Yes | 최신 상품명 |
| `product_url` | `TEXT` | Yes | 최신 상품 URL |
| `image_url` | `TEXT` | Yes | 최신 대표 이미지 URL |
| `backup_image_url` | `TEXT` | Yes | 최신 예비 이미지 URL |
| `status` | `TEXT` | Yes | 최신 판매 상태 |
| `seller_external_id` | `TEXT` | Yes | 판매자 ID |
| `seller_nickname` | `TEXT` | Yes | 판매자 닉네임 |
| `seller_type` | `TEXT` | Yes | 판매자 유형 |
| `seller_grade` | `TEXT` | Yes | 판매자 등급 |
| `seller_excellent_seller` | `BOOLEAN` | Yes | 우수판매자 여부 |
| `seller_average_satisfaction` | `TEXT` | Yes | 판매자 평균 만족도 |
| `seller_review_count` | `NUMERIC(18, 2)` | Yes | 판매자 구매후기 건수 |
| `first_seen_at` | `TIMESTAMPTZ` | No | 최초 관측 시각 |
| `last_collected_at` | `TIMESTAMPTZ` | No | 마지막 수집 시각 |

Unique: `(platform, external_product_id)`

### `product_prices`

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `product_id` | `BIGINT` | No | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | No | 수집 시각 |
| `market` | `TEXT` | No | 가격 market. 예: `ownerclan`, `dome`, `supply`, `retail`, `resale` |
| `price_type` | `TEXT` | No | `primary`, `current_supply`, `fixed`, `minimum_retail`, `recommended_retail`, `minimum`, `recommended` |
| `amount` | `NUMERIC(18, 2)` | Yes | 숫자로 변환 가능한 가격 |
| `currency` | `CHAR(3)` | No | 기본 `KRW` |
| `payload` | `JSONB` | No | 가격 section 원본 보조 정보 |

Unique: `(product_id, collected_at, market, price_type)`

### `product_inventory`

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `product_id` | `BIGINT` | No | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | No | 수집 시각 |
| `stock_quantity` | `NUMERIC(18, 2)` | Yes | 숫자로 변환 가능한 재고 |
| `payload` | `JSONB` | No | inventory section 보조 정보 |

Unique: `(product_id, collected_at)`

### `product_shipping_fees`

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `product_id` | `BIGINT` | No | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | No | 수집 시각 |
| `market` | `TEXT` | No | 배송비 market. 예: `coupang`, `ownerclan`, `dome`, `supply` |
| `fee` | `NUMERIC(18, 2)` | Yes | 계산 가능한 기본 배송비 |
| `shipping_type` | `TEXT` | Yes | `fixed`, `quantity_proportional`, `quantity_tiered`, `free`, `unknown` |
| `is_free_shipping` | `BOOLEAN` | Yes | 무료배송 여부 |
| `payload` | `JSONB` | No | 배송비 원본 보조 정보와 파싱 규칙 |

Unique: `(product_id, collected_at, market)`

### `product_raw_samples`

디버깅용 API 원본 샘플을 제한적으로 저장합니다.

Unique: `(platform, collected_at, external_product_id)`

### `product_change_history`

`products` scalar 컬럼과 최신 가격/재고/배송 snapshot row를 비교해서 값이 달라진 시점만 저장합니다.

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | PK |
| `product_id` | `BIGINT` | No | `products.id` FK |
| `changed_at` | `TIMESTAMPTZ` | No | 변경이 관측된 수집 시각 |
| `change_type` | `TEXT` | No | `initial`, `update` |
| `changed_fields` | `TEXT[]` | No | 값이 달라진 필드 경로 목록 |

Index: `(product_id, changed_at)`

### `product_search_ranks`

순위 의미가 있는 discovery/search 결과만 저장합니다.

Unique: `(platform, collected_at, keyword, category_code, market, sort, external_product_id, rank)`

### `product_discovery_targets`

상세 수집 대상으로 사용할 상품 ID 목록을 저장합니다.

Unique: `(platform, external_product_id)`

## 플랫폼별 데이터 매핑

### 오너클랜 데이터 매핑

오너클랜 Seller GraphQL API 응답은 `ownerclan_API.services.normalization.normalize_item()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다.

상품 기본값입니다.

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `ownerclan` |
| `products.external_product_id` | `productId` 또는 `productKey` |
| `products.product_name` | 정규화된 상품명 |
| `products.product_url` | 정규화된 상품 URL |
| `products.image_url` | `images[0]` 또는 첫 번째 이미지 필드 |
| `products.backup_image_url` | `images[1]` 또는 두 번째 이미지 필드 |
| `products.status` | 정규화된 상태 값 |

가격, 재고, 배송 매핑입니다.

| PostgreSQL | source |
| --- | --- |
| `product_prices.market` | `ownerclan` |
| `product_prices.price_type` | `current_supply`, `fixed` |
| `product_prices.amount` | `prices.currentSupplyPrice`, `prices.fixedPrice` |
| `product_inventory.stock_quantity` | 옵션 수량 합계. 원본 수량은 inventory 보조 payload에 보존 |
| `product_shipping_fees.market` | `ownerclan` |
| `product_shipping_fees.fee` | `shippingFee`가 단일 숫자로 해석되는 경우 |
| `product_shipping_fees.shipping_type` | 계산 가능한 배송비 유형이면 정규화, 아니면 `unknown` |

오너클랜은 `product_search_ranks`에 저장하지 않습니다. 현재 수집 경로의 Seller API 응답은 순위 분석에 쓸 수 있는 랭킹 의미를 제공하지 않습니다.

### 도매꾹/도매매 데이터 매핑

도매꾹/도매매 Open API 응답은 `domeggook_API.services.parsing.parse_detail_product()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다.

상품 기본값입니다.

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `domeggook` |
| `products.external_product_id` | `basis.no`, `no`, `itemNo` |
| `products.product_name` | `basis.title` |
| `products.status` | `basis.status` |
| `products.image_url` | `thumb.original` 또는 첫 번째 이미지 URL |
| `products.backup_image_url` | 두 번째 이미지 URL |

판매자 매핑입니다.

| PostgreSQL | source |
| --- | --- |
| `products.seller_external_id` | `seller.id` |
| `products.seller_nickname` | `seller.nick` |
| `products.seller_type` | `seller.type` |
| `products.seller_grade` | `seller.rank` |
| `products.seller_excellent_seller` | `seller.good` |
| `products.seller_average_satisfaction` | `seller.score.avg` |
| `products.seller_review_count` | `seller.score.cnt` |

가격, 재고, 배송 매핑입니다.

| PostgreSQL | source |
| --- | --- |
| `product_prices.market='dome', price_type='current_supply'` | `price.dome` |
| `product_prices.market='supply', price_type='current_supply'` | `price.supply` |
| `product_prices.market='retail', price_type='minimum_retail'` | `price.labeledPrice.low` 또는 기존 `minimumRetailPrice` alias |
| `product_prices.market='retail', price_type='recommended_retail'` | `price.labeledPrice.recommend` 또는 기존 `recommendedRetailPrice` alias |
| `product_prices.market='resale', price_type='minimum'` | `price.resale.minimum`, 문서 오탈자 alias `price.resale.minumum` |
| `product_prices.market='resale', price_type='recommended'` | `price.resale.Recommand` |
| `product_inventory.stock_quantity` | `qty.inventory` |
| `product_shipping_fees.market='dome'` | `deli.dome.fee`, `deli.dome.tbl`, `deli.dome.type` |
| `product_shipping_fees.market='supply'` | `deli.supply.fee`, `deli.supply.tbl`, `deli.supply.type` |

도매꾹과 도매매 배송비는 `dome`, `supply` row로 분리합니다. 도매매 배송비가 비어 있어도 도매꾹 배송비로 `supply` row를 임의 생성하지 않습니다.

### 쿠팡 데이터 매핑

쿠팡 파트너스 상품 검색 API 응답은 `coupang_API.services.models.parse_product_records()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다.

상품 기본값입니다.

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `coupang` |
| `products.external_product_id` | `productId` |
| `products.product_name` | `productName` |
| `products.product_url` | `productUrl` |
| `products.image_url` | `productImage` |

가격, 재고, 배송 매핑입니다.

| PostgreSQL | source |
| --- | --- |
| `product_prices.market` | `coupang` |
| `product_prices.price_type` | `primary` |
| `product_prices.amount` | `productPrice` |
| `product_inventory.stock_quantity` | 검색 API에 재고가 없으므로 row를 저장하지 않음 |
| `product_shipping_fees.market` | `coupang` |
| `product_shipping_fees.is_free_shipping` | `isFreeShipping` 값이 있을 때 저장 |

예전 `data/raw/coupang_*_raw_{keyword}.json` 파일은 더 이상 생성하지 않습니다. raw 샘플은 `product_raw_samples`에 저장하며, 저장 호출당 최대 3개 상품까지만 보존합니다.

모든 플랫폼의 변경 감지는 동일합니다. 최신 API 응답 전체 JSON은 `products`에 저장하지 않고, `products` scalar 컬럼과 최신 가격/재고/배송 snapshot row를 기준으로 처리합니다. 값이 바뀌면 `product_change_history.changed_fields`에 변경된 경로만 남깁니다.

## API 호출 제한 관측

### 오너클랜 백필 노트

작성일: 2026-09-03

오너클랜 Seller GraphQL API에서 전체 상품을 카테고리 기준으로 백필합니다. 로컬 검증에서는 PostgreSQL 저장까지 확인했고, 서버 배포 시에는 전체 상품 백필 가능 여부와 호출 한도 안정성이 핵심입니다.

마지막 확인 시점 기준 DB 저장 현황입니다.

- `products` 오너클랜 총계: 579,219개
- 첫 대형 단일 수집 저장 상품: 276,048개
- 첫 대형 단일 수집 `allItems` 호출 시도: 689회
- 성공 호출: 657회
- ReadTimeout: 30회
- 429: 0회

`page_size=500` 기준 호출 수 산정입니다.

- 1,000만 상품 / 500개 = 최소 20,000 successful page calls
- timeout, retry, 카테고리 마지막 페이지, 빈 페이지를 감안하면 운영상 21,000~25,000 API attempts 예상
- `page_size=1000` 기준 최소 호출 수는 10,000회지만, 로컬 테스트에서 1000개 payload가 느린 응답과 ReadTimeout을 유발

현재 백필 설정입니다.

```yaml
incremental:
  page_size: 500

request:
  interval_seconds: 0.4
  timeout_seconds: 15
  max_retries: 2
  retry_after_max_seconds: 300
```

권장 실행입니다.

```powershell
python -m ownerclan_API --category-workers 8 --failure-retry-seconds 60 --max-failure-restarts 50
```

4 worker 실행 중 최근 15분 샘플입니다.

- 저장 상품: 148,011개
- 처리 속도: 약 9,867개/min
- 시간당 환산: 약 592,000개/hour
- 1,000만개 단순 투영: 약 16.9시간
- 429: 0
- 최근 API success: 525
- 최근 timeout: 24

이 페이스가 유지되면 하루 안 백필 가능하지만, 서버/gateway 상태, timeout, 카테고리 마지막 페이지 비율에 따라 17~24시간 범위로 보는 것이 현실적입니다.

운영 판단입니다.

- 처음 권장값: `category_workers=8`, `page_size=500`, 전체 합산 목표 RPM 120~150
- 429, `Too many requests`, `502 + Retry-After`가 보이면 즉시 90초 이상 쉬고 RPM을 낮춤
- 서버 자원이 충분하고 429/Retry-After가 없으면 worker 수를 8까지 사용 가능
- 호출 한도보다 Ownerclan 응답 지연과 PostgreSQL write throughput이 먼저 병목이 될 수 있음
- `page_size=100`은 호출 수가 5배 증가하므로 기본값으로 쓰지 않음
- `page_size=500`에서 payload timeout이 반복될 때만 `300` 또는 `250`으로 낮춰 비교 테스트

2026-09-03 변경 사항입니다.

- 모든 병렬 worker가 하나의 공유 `RateLimiter`를 사용하도록 변경
- worker 수를 늘려도 전체 API 호출은 공유 limiter가 직렬화
- `interval_seconds=0.4` 기준 총합 최대 150 RPM을 넘지 않음
- rate limit 계열 실패는 `failureCount`와 `rateLimitFailureCount`를 올리고 전체 worker 소비를 멈춤
- 일반 네트워크 실패는 같은 카테고리를 최대 3회까지 내부 재시도
- 모든 카테고리가 최종 성공한 경우에만 progress/state 파일 정리

### 오너클랜 API 호출 제한 테스트

테스트 조건입니다.

- 테스트일: 2026-08-30
- 환경: production
- 대상: Seller GraphQL API
- 요청: `allItems(first: 1)`
- 저장: 없음
- 스크립트: `tests/probes/ownerclan_rate_probe.py`

분당 호출 테스트 결과입니다.

| 목표 RPM | 관측 RPM | 결과 |
| ---: | ---: | --- |
| 60 | 60.84 | 61/61 성공, rate limit 없음 |
| 120 | 120.78 | 121/121 성공, rate limit 없음 |
| 180 | 180.58 | 181/181 성공, rate limit 없음 |
| 210 | 203.63 | 204/204 성공, rate limit 없음 |
| 240 | 32.99 | rate limit 없음, `ReadTimeout` 2회 발생 |

1시간 지속 테스트 결과입니다.

| 목표 RPM | 지속 시간 | 시도 | 성공 | 오류 | 결과 |
| ---: | ---: | ---: | ---: | ---: | --- |
| 180 | 3600초 | 10571 | 10520 | 51 | rate limit 없음, 502/ConnectionError 발생 |

판단입니다.

- 분당 200회 안팎까지는 429 또는 GraphQL `Too many requests`가 확인되지 않음
- 180 RPM 1시간 지속 테스트에서도 rate limit은 확인되지 않음
- 240 RPM에서는 rate limit보다 응답 지연/타임아웃이 먼저 발생
- 이후 더 높은 속도에서 timeout과 gateway backoff가 먼저 관측됨
- 현재 운영 수집 설정은 전역 limiter 기준 약 150 RPM
- 현재 권장값: `request.interval_seconds: 0.4`

재테스트 명령입니다.

```powershell
python tests\probes\ownerclan_rate_probe.py --rpm 150 --duration 60
```

### 쿠팡 파트너스 API 호출 제한 관측

작성 기준: 2026-09-02 KST

2026-08-26에는 쿠팡 파트너스 Search API로 100개 키워드를 모두 성공 조회했고, 총 994개 상품 row를 만들었습니다. 이때 실제 평균 호출 속도는 약 0.805 req/sec, 48.32 RPM이었습니다.

2026-09-02 제한 테스트에서는 Search API를 약 2.0 req/sec, 120 RPM 속도로 호출했고, 52번째 호출에서 HTTP 200 + `rCode=403`이 발생했습니다. 응답 메시지는 검색 API의 시간당 사용 횟수 초과였고, 재시도 가능 시각으로 2026-09-03 오후 5시 46분 28초 이후를 반환했습니다.

이후 2026-09-02 오후 9시 7분 16초에 Best Category API를 1회 확인했을 때도 HTTP 200 + `rCode=403`과 같은 시간당 제한 메시지가 반환됐습니다. 따라서 Search API와 Best Category API는 독립 쿼터가 아니라 같은 상품 검색 계열 쿼터를 공유하는 것으로 강하게 보입니다.

근거 파일입니다.

| 구분 | 파일 | 의미 |
| --- | --- | --- |
| 과거 정상 수집 상품 파일 | `coupang_API/data/processed/coupang_2026_0826_2101_products.jsonl` | 2026-08-26 실행 결과 상품 row 994개 |
| 과거 정상 수집 요약 | `coupang_API/data/summaries/coupang_2026_0826_2101_summary.json` | 100개 키워드 성공, 실패 0개 |
| Search 제한 테스트 로그 | `tests/probes/logs/coupang_rate_probe_20260902_174602.jsonl` | 601회 호출, 52번째부터 제한 관측 |
| Best Category 제한 확인 로그 | `tests/probes/logs/coupang_rate_probe_best-category_20260902_210715.jsonl` | 제한 상태에서 1회 호출, 즉시 `rCode=403` |

2026-08-26 정상 수집 요약입니다.

| 항목 | 값 |
| --- | ---: |
| 실행 시작 UTC | `2026-08-26T12:01:24.820631Z` |
| 실행 종료 UTC | `2026-08-26T12:03:28.982103Z` |
| 실행 시작 KST | 2026-08-26 21:01:24 |
| 실행 종료 KST | 2026-08-26 21:03:28 |
| 총 실행 시간 | 124.161초 |
| 총 키워드 수 | 100 |
| 처리 키워드 수 | 100 |
| 성공 키워드 수 | 100 |
| 실패 키워드 수 | 0 |
| 수집 상품 row 수 | 994 |
| 중복 상품 row 수 | 0 |
| Search API 호출 수 추정 | 100회 |
| 호출당 평균 상품 수 | 9.94개 |
| 실제 평균 분당 호출량 | 48.32 RPM |

2026-09-02 Search 제한 테스트 요약입니다.

| 항목 | 값 |
| --- | ---: |
| 테스트 시작 KST | 2026-09-02 17:46:03 |
| 테스트 종료 KST | 2026-09-02 17:51:02 |
| 총 호출 수 | 601회 |
| 성공 수 | 204회 |
| 실패 수 | 397회 |
| HTTP 상태코드 분포 | `200`: 601회 |
| rCode 분포 | `0`: 204회, `403`: 397회 |
| 전체 테스트 실제 평균 분당 호출량 | 120.2 RPM |
| 최초 제한 attempt | 52번째 |
| 최초 제한 시각 KST | 2026-09-02 17:46:28 |
| 시작 후 최초 제한 경과 | 25.515초 |
| 제한 발생 전 성공 수 | 51회 |
| 최초 제한 HTTP 상태코드 | 200 |
| 최초 제한 rCode | `403` |
| Retry-After 헤더 | 없음 |

Best Category 제한 확인 결과입니다.

| 항목 | 값 |
| --- | --- |
| API | Best Category API |
| URI | `/v2/providers/affiliate_open_api/apis/openapi/products/bestcategories/1001?limit=100` |
| 호출 시각 KST | 2026-09-02 21:07:16 |
| 호출 수 | 1회 |
| HTTP 상태코드 | 200 |
| rCode | `403` |
| 재시도 가능 시각 | 2026-09-03 17:47:37 이후 |
| 초과 카운트 | 현재 2회 초과 |

운영 관점 권장입니다.

- Search API와 Best Category API를 같은 쿼터로 묶어서 계산
- HTTP 상태코드와 JSON `rCode/rMessage`를 함께 검사
- `rCode=403` 또는 `rCode=429`는 즉시 중단
- 시간당 사용 횟수 초과 메시지는 즉시 중단하고 응답의 재시도 가능 시각까지 대기
- 제한 상태 재확인은 반복하지 않고 다른 API도 최대 1회만 확인
- 재개 전 최소 대기는 쿠팡 응답의 재시도 가능 시각 이후

보수적 임시 속도입니다.

| 구분 | 값 |
| --- | ---: |
| 임시 운영 상한 | 6 calls/hour 이하 |
| 초당 환산 | 0.00167 req/sec 이하 |
| 분당 환산 | 0.1 RPM 이하 |
| 호출 간격 | 최소 10분 이상 |

이 값은 공식 한도가 아닙니다. 현재 제한 상태에서 추가 리스크를 피하기 위한 임시 안전값입니다.

확정된 사실과 추정입니다.

- 2026-08-26에는 Search API 100회 호출이 전부 성공
- 2026-08-26 결과 파일의 994줄은 API 994회 호출이 아니라 100개 키워드 응답의 상품 row
- 2026-09-02 Search 테스트는 약 2.0 req/sec, 120 RPM으로 호출
- 2026-09-02 Search 테스트는 52번째 호출에서 HTTP 200 + `rCode=403` 제한 발생
- Best Category API도 Search 제한 상태에서 1회 호출 시 HTTP 200 + `rCode=403` 반환
- Search API와 Best Category API는 같은 상품 검색 계열 쿼터를 공유하는 것으로 보임
- 120 RPM은 현재 계정 상태에서 위험
- 제한 발생 시 거의 24시간 쿨다운처럼 동작

아직 정확히 확인할 수 없는 항목입니다.

- 정확한 초당 안정 호출량
- 정확한 분당 안정 호출량
- 정확한 1시간 한도
- 정확한 하루 한도
- Best Category 단독 한도
- 쿼터 공유의 공식 확정

## 테스트

전체 테스트를 실행합니다.

```powershell
pytest
```

## 원본 문서 위치

README에 모든 내용을 통합했지만, 세부 원본 문서는 아래 위치에 유지합니다.

- [docs/operations/DAILY_COLLECTION_OPERATIONS.md](docs/operations/DAILY_COLLECTION_OPERATIONS.md)
- [docs/operations/COLLECTION_METHODS.md](docs/operations/COLLECTION_METHODS.md)
- [docs/operations/PLATFORM_COLLECTION_FLOW_SUMMARY.md](docs/operations/PLATFORM_COLLECTION_FLOW_SUMMARY.md)
- [docs/operations/OWNERCLAN_BACKFILL_NOTES.md](docs/operations/OWNERCLAN_BACKFILL_NOTES.md)
- [docs/schema/DATA_STORAGE_SCHEMA.md](docs/schema/DATA_STORAGE_SCHEMA.md)
- [docs/schema/DB_FIELD_SPEC.md](docs/schema/DB_FIELD_SPEC.md)
- [ownerclan_API/README.md](ownerclan_API/README.md)
- [ownerclan_API/DATA_SCHEMA.md](ownerclan_API/DATA_SCHEMA.md)
- [domeggook_API/README.md](domeggook_API/README.md)
- [domeggook_API/DATA_SCHEMA.md](domeggook_API/DATA_SCHEMA.md)
- [coupang_API/README.md](coupang_API/README.md)
- [coupang_API/DATA_SCHEMA.md](coupang_API/DATA_SCHEMA.md)
- [tests/probes/OWNERCLAN_RATE_LIMIT_PROBE.md](tests/probes/OWNERCLAN_RATE_LIMIT_PROBE.md)
- [tests/probes/COUPANG_PARTNERS_RATE_LIMIT_REPORT.md](tests/probes/COUPANG_PARTNERS_RATE_LIMIT_REPORT.md)

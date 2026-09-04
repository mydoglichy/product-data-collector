# 플랫폼별 데이터 수집 흐름 요약

이 문서는 쿠팡, 오너클랜, 도매꾹/도매매 수집기가 현재 코드 기준으로 어떤 순서로 데이터를 수집하고 저장하는지 빠르게 검증하기 위한 요약입니다. 더 자세한 운영 기준은 [COLLECTION_METHODS.md](COLLECTION_METHODS.md)를 봅니다.

## 쿠팡

- 입력 대상: `coupang_API/config/keywords.txt`의 keyword 목록
- 실행 명령:
  - `python -m coupang_API`
  - `python -m coupang_API --dry-run`
  - `python scripts/run_daily_collector.py --platform coupang`
  - `python scripts/run_daily_collector.py --platform coupang --dry-run`

### 흐름

1. `product_search_checkpoint.json`에 완료 기록이 있는 keyword는 건너뜁니다.
2. 남은 keyword를 순서대로 하나씩 처리합니다.
3. 현재 구현은 keyword 1개마다 쿠팡 파트너스 Search API 요청을 1회 만듭니다.
4. 요청 parameter는 `keyword`, `limit=10`, `imageSize`, `srpLinkOnly=false`, 선택 `subId`입니다.
5. 응답 상품 row를 공통 product record로 정규화합니다.
6. 같은 실행 안에서 `productId` 기준으로 중복 상품을 제거합니다.
7. raw sample은 설정된 제한 개수만 `product_raw_samples`에 저장합니다.
8. 상품 master, 가격 snapshot, 배송 snapshot을 PostgreSQL에 저장합니다.
9. 성공한 keyword를 checkpoint에 기록합니다.
10. `keywords.txt`의 모든 keyword가 checkpoint 완료 상태가 되고 이번 실행 실패가 없으면 checkpoint 파일을 삭제합니다.
11. 이미 완료된 keyword만 남아 있는 재실행에서도 같은 조건이 만족되므로 checkpoint 파일을 삭제합니다.

### 제한과 실패 처리

- 현재 설정은 rolling window 기준 40 RPM입니다.
- HTTP status가 200이어도 JSON 본문의 `rCode`가 `0`이 아니면 실패로 처리합니다.
- `--dry-run`은 checkpoint를 읽어서 완료 keyword를 건너뛰지만 checkpoint 파일을 생성, 갱신, 삭제하지 않습니다.
- `--dry-run`은 API 호출과 파싱까지 수행하지만 raw sample, 상품 snapshot도 저장하지 않습니다.
- keyword가 하나라도 실패하면 실행 결과를 실패 exit code로 반환합니다.

## 오너클랜

- 입력 대상: 오너클랜 Seller GraphQL API의 카테고리 트리
- 실행 명령:
  - `python -m ownerclan_API`
  - `python -m ownerclan_API --refresh-categories`
  - `python -m ownerclan_API --refresh-categories --limit 1 --dry-run`
  - `python scripts/run_daily_collector.py --platform ownerclan`

### 흐름

1. `category(key: "00000000") { descendants }`로 전체 카테고리를 조회합니다.
2. `children`이 없는 항목을 최하위 카테고리로 판단합니다.
3. 최하위 카테고리 목록을 key 기준으로 정렬해 `ownerclan_API/data/state/categories.json`에 캐시합니다.
4. 각 최하위 카테고리에서 `allItems(first=500, category: categoryKey, after: cursor)`를 호출합니다.
5. GraphQL cursor를 따라 해당 카테고리의 마지막 page까지 순차 조회합니다.
6. 상품 데이터를 공통 구조로 정규화합니다.
7. 상품 master, 가격 snapshot, 재고 snapshot, 배송비 snapshot을 PostgreSQL에 저장합니다.
8. 기존 DB 최신값과 현재 정규화 값을 비교해 변경 사항이 있으면 `product_change_history`에 기록합니다.
9. 전체 카테고리 수집이 실패 없이 완료되면 같은 실행 안에서 `sync_incremental` 단계가 이어서 실행됩니다.
10. `sync_incremental`은 `updatedAt` 기준 최근 변경 상품을 추가로 수집합니다.
11. 카테고리 수집이 실패하면 `sync_incremental`은 실행하지 않고 빈 incremental 결과를 반환합니다.

### 제한과 재개

- daily wrapper 기본 worker 수는 8입니다.
- 병렬 worker들은 하나의 공유 `RateLimiter`를 사용합니다.
- `request.interval_seconds=0.4` 기준 전체 호출 상한은 약 150 RPM입니다.
- 병렬 수집 진행 상태는 `category-collection-progress.json`에 저장합니다.
- 증분 수집 진행 상태는 `incremental-state.json`에 저장합니다.
- rate limit 계열 실패는 상태 파일을 보존하고 지정된 대기 시간 뒤 재시작합니다.
- 일반 실패도 상태 파일을 보존하고 설정된 횟수 안에서 재시작합니다.
- 카테고리 수집이 정상 완료되면 category progress 상태 파일을 삭제합니다.

## 도매꾹/도매매

- 입력 대상: 도매꾹/도매매 Open API 카테고리 트리와 PostgreSQL의 discovery target
- 실행 명령:
  - `python -m domeggook_API`
  - `python -m domeggook_API --mode daily`
  - `python -m domeggook_API --limit 1 --dry-run`
  - `python scripts/run_daily_collector.py --platform domeggook`

### Full 흐름

1. `getCategoryList`로 카테고리 트리를 조회합니다.
2. depth 2 이상이고 child가 없는 카테고리를 검색 가능한 최하위 카테고리로 판단합니다.
3. 카테고리 목록을 `domeggook_API/data/state/categories.json`에 캐시합니다.
4. discovery에서 `(최하위 카테고리, market, sort)` 조합을 만듭니다.
5. market은 `dome`, `supply`를 사용합니다.
6. sort는 `ha`, `rd`, `da`를 사용합니다.
7. 각 조합의 list page를 끝까지 순회하며 상품 ID를 발견합니다.
8. 발견한 상품 ID를 PostgreSQL `product_discovery_targets`에 저장합니다.
9. 순위 의미가 있는 `ha`, `rd` 결과만 `product_search_ranks`에 저장합니다.
10. `da`는 최근 등록/수정 기준이므로 ranking history로 저장하지 않습니다.
11. 상세 수집은 `product_discovery_targets`에서 active 상품 ID를 읽습니다.
12. `getItemView`를 batch size 100으로 호출해 상품 snapshot을 저장합니다.

### Daily 흐름

1. 저장된 `product_discovery_targets`의 active 상품 ID 상세 수집을 먼저 실행합니다.
2. 상세 수집이 끝나고 API 예산이 남으면 최근 상품 보강 discovery를 실행합니다.
3. 최근 상품 보강은 `recent=da`를 사용합니다.
4. 기본값은 각 카테고리/market position당 1 page입니다.
5. 상세 수집 실패, runtime cap 도달, 일일 API 예산 도달 시 최근 상품 보강은 건너뜁니다.

### 제한과 재개

- 현재 설정은 분당 120, 시간당 9000, 일당 14000 호출 예산입니다.
- API key가 여러 개면 key를 round-robin으로 선택하고 key별 limiter를 적용합니다.
- discovery 상태는 `discovery-state.json`에 저장합니다.
- daily 최근 보강 상태는 `recent-discovery-state.json`에 저장합니다.
- 상세 수집 상태는 `detail-collection-state.json`에 저장합니다.
- runtime cap이나 API 예산에 도달하면 실패가 아니라 `paused`로 기록하고 다음 실행에서 이어갑니다.

## Docker Compose 실행 기준

`docker compose up data-collector`는 `scripts/run_collectors.py`를 실행합니다. 현재 이 경로는 오너클랜과 도매꾹/도매매를 순서대로 수집하며, 쿠팡은 포함하지 않습니다. 쿠팡은 API 제한 특성이 달라 `scripts/run_daily_collector.py --platform coupang`으로 별도 실행합니다.

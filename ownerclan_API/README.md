# 오너클랜 수집기

오너클랜 Seller GraphQL API에서 최하위 카테고리별로 상품을 순회하고 증분 수집 결과를 PostgreSQL에 저장한다.

기본 실행은 저장된 최하위 카테고리 캐시를 사용한다. 캐시가 없거나 `--refresh-categories`를 주면 `category(key: "00000000").descendants`를 조회해 `children`이 없는 카테고리만 `data/state/categories.json`에 저장한다. 이후 각 최하위 카테고리마다 `allItems(category: ..., first: 1000, after: ...)`를 끝까지 페이지네이션한다.

## 저장 방식

수집기는 더 이상 product snapshot, raw sample, search rank, latest cache, product history, summary, collection run JSON 파일을 만들지 않는다.

저장 테이블:

- `products`: 상품 master와 최신 정규화 payload
- `product_prices`: 공급가/고정가 snapshot
- `product_inventory`: 옵션 수량 합산 재고 snapshot
- `product_shipping_fees`: 배송비 snapshot
- `product_change_history`: 변경 감지 이력
- `product_raw_samples`: raw 샘플, 저장 호출당 최대 3개 상품

오너클랜은 `product_search_ranks`에 저장하지 않는다. Seller API에서 인기순, 판매량순, 랭킹 순위 의미의 데이터를 제공하지 않으므로 검색 결과의 임시 순번을 순위 데이터로 보존하지 않는다.

## 실행 상태 파일

- `data/state/categories.json`: 최하위 카테고리 캐시
- PostgreSQL `product_discovery_targets`: 키워드 기반 상세 수집 대상 상품 key
- `data/state/incremental-state.json`: 증분 수집 기준 시각

`config/keywords.txt` 기반 discovery 모듈은 남아 있지만 기본 실행 경로가 아니다.

## 실행

```powershell
python -m ownerclan_API
python -m ownerclan_API --refresh-categories
python -m ownerclan_API.workflows.collect_by_categories --refresh-categories
python -m ownerclan_API.workflows.sync_incremental
```

소량 검증:

```powershell
python -m ownerclan_API --refresh-categories --limit 1 --dry-run
```

## 재개 상태 파일

수집기는 중복 호출을 허용하고 데이터 손실을 줄이는 방식으로 동작한다. 페이지나 배치 데이터를 PostgreSQL에 저장한 뒤에만 다음 시작 위치를 상태 파일에 기록한다. 같은 `runCollectedAt`으로 재개하므로 중복 호출이 발생해도 DB unique/upsert 조건으로 같은 수집 시점의 중복 row는 추가되지 않는다.

- `data/state/category-collection-state.json`: 카테고리 전체 순회 재개 지점. `categoryKey`와 GraphQL `after` cursor를 저장한다.
- `data/state/detail-collection-state.json`: 상세 수집 재개 지점. 정렬된 상품번호 목록의 `trackedListHash`, `nextIndex`, `lastCompletedProductId`를 저장한다.
- `data/state/incremental-state.json`: 증분 수집의 마지막 완전 성공 시각을 저장한다.

전체 수집이 정상 완료되면 `category-collection-state.json`과 `detail-collection-state.json`은 삭제된다. 실패나 프로세스 중단으로 남아 있으면 다음 실행에서 해당 위치부터 재개한다.

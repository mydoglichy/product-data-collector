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
- `data/state/tracked_products.json`: 상세 수집 대상 상품
- `data/state/incremental-state.json`: 증분 수집 기준 시각

`keywords.txt` 기반 discovery 모듈은 남아 있지만 기본 실행 경로가 아니다.

## 실행

```powershell
python -m ownerclan_API.main
python -m ownerclan_API.main --refresh-categories
python -m ownerclan_API.collect_by_categories --refresh-categories
python -m ownerclan_API.sync_incremental
```

소량 검증:

```powershell
python -m ownerclan_API.main --refresh-categories --limit 1 --dry-run
```

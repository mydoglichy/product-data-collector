# 오너클랜 데이터 스키마

오너클랜 Seller GraphQL 응답은 `normalize_item()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장한다.

## PostgreSQL 매핑

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `ownerclan` |
| `products.external_product_id` | `productId` 또는 `productKey` |
| `products.current_payload` | 최신 정규화 상품 payload |
| `products.comparable_payload` | `prices`, `inventory`, `shipping`, `options`, `status`, `sourceStatus` |
| `product_prices.market` | `ownerclan` |
| `product_prices.amount` | `prices.currentSupplyPrice`, `prices.fixedPrice` |
| `product_inventory.stock_quantity` | `inventory.stockQuantity` |
| `product_shipping_fees.market` | `ownerclan` |
| `product_shipping_fees.fee` | `shipping.fee` |
| `product_shipping_fees.shipping_type` | 정규화된 배송비 타입 |
| `product_raw_samples.payload` | raw 디버깅 샘플 |

오너클랜은 `product_search_ranks`에 저장하지 않는다. Seller API에서 인기순, 판매량순, 랭킹 순위 의미의 상품 순위 데이터를 제공하지 않으므로 검색 결과의 순번을 랭킹 데이터로 취급하지 않는다.

## 수집 범위

기본 수집은 최하위 카테고리 기준 전체 순회다.

1. `category(key: "00000000").descendants`로 전체 카테고리를 가져온다.
2. `children`이 없는 카테고리를 최하위 카테고리로 판단해 `data/state/categories.json`에 캐시한다.
3. 캐시된 최하위 카테고리마다 `allItems(category: ..., first: 1000, after: ...)`를 페이지네이션한다.
4. 상품 `key` 기준으로 중복 제거한 뒤 `normalize_item()` 결과를 PostgreSQL에 저장한다.

## 재고

옵션별 `quantity`가 있으면 `inventory.stockQuantity`는 `sum(options[].quantity)`로 저장한다. API 원본 수량은 `inventory.apiStockQuantity`에 보존한다.

## raw 샘플

예전 `data/raw/ownerclan_*_raw.json` 파일은 더 이상 생성하지 않는다. raw 샘플은 `product_raw_samples`에 저장하고, 저장 호출당 최대 3개 상품으로 제한한다.

## 파일 기반 상태

- `data/state/categories.json`
- `data/state/tracked_products.json`
- `data/state/incremental-state.json`

이 파일들은 실행 입력/재시작 상태이며 상품 결과 저장소가 아니다.

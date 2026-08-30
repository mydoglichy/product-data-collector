# 데이터 저장 스키마

현재 운영 수집 결과는 PostgreSQL에 저장한다. 예전 JSON/JSONL 산출물은 더 이상 상품 데이터의 기준 저장소가 아니며, 수집기는 product snapshot, raw sample, search rank, summary, latest cache, product history, collection run JSON/JSONL 파일을 생성하지 않는다.

스키마 생성과 보강은 [postgres_storage.py](postgres_storage.py)의 `init_schema()`에서 수행한다.

이 문서는 저장 구조 개요다. 모든 테이블의 전체 컬럼, 타입, null 여부, 기본값, 제약 조건, 인덱스는 [DB_FIELD_SPEC.md](DB_FIELD_SPEC.md)를 기준으로 확인한다.

## 공통 저장 흐름

1. 각 API 응답을 플랫폼별 parser/normalizer에서 공통 상품 payload로 정규화한다.
2. `postgres_storage.save_product_snapshots_if_enabled()`가 상품, 가격, 재고, 배송비, 변경 이력을 저장한다.
3. raw 샘플이 있는 경우 `save_product_raw_samples_if_enabled()`가 `product_raw_samples`에 저장한다.
4. 순위 의미가 있는 discovery/search 결과만 `save_search_ranks_if_enabled()`가 `product_search_ranks`에 저장한다.

`POSTGRES_ENABLED`가 꺼져 있으면 DB 저장 함수는 저장하지 않고 `0`을 반환한다. 파일 출력으로 fallback하지 않는다.

## `products`

플랫폼별 상품 master와 최신 정규화 payload를 저장한다.

- unique key: `(platform, external_product_id)`
- `product_name`, `product_url`, `image_url`: 조회 편의를 위한 최신 대표값
- `current_payload`: raw, 추적 query, 이미지 query 등 volatile 값을 제거한 최신 payload
- `comparable_payload`: 변경 감지에 쓰는 section만 남긴 payload
- `comparable_fingerprint`: `comparable_payload`의 SHA-256 fingerprint
- `first_seen_at`: 최초 관측 시각
- `last_collected_at`: 마지막 수집 시각

## `product_prices`

수집 시점별 가격 snapshot이다.

- unique key: `(product_id, collected_at, market, price_type)`
- `market`: `coupang`, `ownerclan`, `dome`, `supply`, `retail` 등
- `price_type`: `primary`, `current_supply`, `fixed`, `minimum_retail`, `recommended_retail`
- `amount`: 숫자로 변환 가능한 가격
- `currency`: 현재 기본값 `KRW`
- `payload`: 가격 section 전체
- 조건부 가격 문자열은 숫자 컬럼에 강제로 넣지 않고 `payload`에 보존한다.

도매꾹/도매매 가격 저장:

- `prices.domeCurrentSupplyPrice` -> `market='dome'`, `price_type='current_supply'`
- `prices.supplyCurrentSupplyPrice` -> `market='supply'`, `price_type='current_supply'`
- `prices.minimumRetailPrice` -> `market='retail'`, `price_type='minimum_retail'`
- `prices.recommendedRetailPrice` -> `market='retail'`, `price_type='recommended_retail'`

## `product_inventory`

수집 시점별 재고 snapshot이다.

- unique key: `(product_id, collected_at)`
- `stock_quantity`: `inventory.stockQuantity`
- `payload`: inventory section 전체

현재 도매꾹/도매매 상세 API는 재고를 `qty.inventory` 단일값으로 제공한다. 가격/배송비처럼 `dome`과 `supply` 재고가 따로 내려오지 않으므로, 현재 구조에서는 상품 단위 단일 재고 row가 맞다.

## `product_shipping_fees`

수집 시점별 배송비 snapshot이다.

- unique key: `(product_id, collected_at, market)`
- `market`: `coupang`, `ownerclan`, `dome`, `supply`
- `fee`: 기본 수량 1 기준으로 계산 가능한 배송비
- `shipping_type`: `fixed`, `quantity_proportional`, `quantity_tiered`, `free`, `unknown`
- `is_free_shipping`: source payload의 무료배송 여부
- `payload`: 배송 section과 파서 결과. 배송비 부담 방식과 도서산간 추가배송비도 이 payload에 보존한다.

도매꾹/도매매 배송비는 `market='dome'`, `market='supply'` row로 분리한다.

배송비 부담 방식은 현재 별도 컬럼이 아니라 `payload.shipping_payment`에 저장한다.

- `S`, `무료배송` -> `free`
- `P`, `선결제` -> `prepaid`
- `B`, `착불` -> `collect`
- `C`, `구매자 선택` -> `buyer_choice`
- 알 수 없는 값 -> `unknown`

착불이어도 `fee` 계산은 유지하고, 부담 방식만 `collect`로 분리한다. 도서산간 추가배송비는 기본 배송비에 합산하지 않는다.

## `product_change_history`

`comparable_payload` fingerprint가 달라질 때 append-only로 저장하는 변경 이력이다.

- 최초 저장: `change_type='initial'`
- 이후 변경: `change_type='update'`
- `before_fingerprint`, `after_fingerprint`: 변경 전후 fingerprint
- `before_payload`, `after_payload`: 변경 전후 comparable payload

## `product_raw_samples`

디버깅용 raw 응답 샘플을 저장한다.

- unique key: `(platform, collected_at, external_product_id)`
- `payload`: parser/normalizer가 남긴 raw 샘플
- 저장 호출당 최대 3개 상품만 저장한다.

이 테이블은 전체 원본 아카이브가 아니라 장애 분석과 parser 검증을 위한 제한 샘플이다.

## `product_search_ranks`

discovery/search에서 발견한 상품 순위 이력이다.

- unique key: `(platform, collected_at, market, sort, external_product_id, rank)`
- 도매꾹/도매매: keyword, category, market, sort, reason, product id, rank 저장
- 오너클랜: 저장하지 않는다. Seller GraphQL API에서 인기순, 판매량순, 랭킹 순위 의미의 상품 순위 데이터를 기준으로 제공하지 않기 때문이다.

## 파일 기반 상태

아래는 아직 DB로 옮기지 않은 실행 입력/상태 파일이다.

- `domeggook_API/data/state/categories.json`: 도매꾹 카테고리 캐시
- `domeggook_API/data/state/tracked_products.json`: 도매꾹 상세 수집 대상
- `ownerclan_API/data/state/categories.json`: 오너클랜 최하위 카테고리 캐시
- `ownerclan_API/data/state/tracked_products.json`: 오너클랜 상세 수집 대상
- `ownerclan_API/data/state/incremental-state.json`: 오너클랜 증분 수집 기준 시각
- `coupang_API/data/state/product_search_checkpoint.json`: 쿠팡 keyword checkpoint

이 파일들은 상품 수집 결과 저장소가 아니다.

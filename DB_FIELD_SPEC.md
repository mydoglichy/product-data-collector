# DB 필드 전체 명세

이 문서는 PostgreSQL에 생성되는 모든 테이블과 컬럼의 전체 명세다. 기준 구현은 [postgres_storage.py](postgres_storage.py)의 `init_schema()`이다.

## 공통 규칙

- 시간 컬럼 타입은 모두 `TIMESTAMPTZ`이다.
- JSON payload 컬럼 타입은 모두 `JSONB`이다.
- `product_id` FK는 모두 `products(id)`를 참조하며 `ON DELETE CASCADE`가 적용된다.
- 스키마 생성 시 기존 테이블 보강을 위해 일부 `ALTER TABLE`, constraint 보강, backfill SQL도 실행된다.

## `products`

플랫폼별 상품 master와 최신 정규화 payload를 저장한다.

| 컬럼 | 타입 | Null | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | sequence | PK |
| `platform` | `TEXT` | No | 없음 | 수집 플랫폼. 예: `coupang`, `ownerclan`, `domeggook` |
| `external_product_id` | `TEXT` | No | 없음 | 플랫폼 원본 상품 ID |
| `product_name` | `TEXT` | Yes | 없음 | 최신 상품명. `productName`, `name`, `title` 중 첫 유효값 |
| `product_url` | `TEXT` | Yes | 없음 | 최신 상품 URL. `productUrl`, `affiliateUrl`, `url` 중 첫 유효값 |
| `image_url` | `TEXT` | Yes | 없음 | 최신 대표 이미지 URL. `imageUrl`, `productImage` 중 첫 유효값 |
| `current_payload` | `JSONB` | No | `'{}'::jsonb` | raw, 추적 query, 이미지 query 등 volatile 값을 제거한 최신 정규화 payload |
| `comparable_payload` | `JSONB` | No | `'{}'::jsonb` | 변경 감지 대상 section만 남긴 payload |
| `comparable_fingerprint` | `CHAR(64)` | No | 없음 | `comparable_payload`의 SHA-256 fingerprint |
| `first_seen_at` | `TIMESTAMPTZ` | No | 없음 | 최초 관측 시각 |
| `last_collected_at` | `TIMESTAMPTZ` | No | 없음 | 마지막 수집 시각 |
| `created_at` | `TIMESTAMPTZ` | No | `now()` | DB row 생성 시각 |
| `updated_at` | `TIMESTAMPTZ` | No | `now()` | DB row 갱신 시각 |

제약 조건:

- Primary key: `id`
- Unique: `(platform, external_product_id)`

인덱스:

- `idx_products_platform_external_id` on `(platform, external_product_id)`
- `idx_products_last_collected_at` on `(last_collected_at)`

## `product_prices`

수집 시점별 가격 snapshot을 저장한다.

| 컬럼 | 타입 | Null | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | sequence | PK |
| `product_id` | `BIGINT` | No | 없음 | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | No | 없음 | 수집 시각 |
| `market` | `TEXT` | No | `'default'` | 가격 market. 예: `coupang`, `ownerclan`, `dome`, `supply`, `retail` |
| `price_type` | `TEXT` | No | `'primary'` | 가격 종류. 예: `primary`, `current_supply`, `fixed`, `minimum_retail`, `recommended_retail` |
| `amount` | `NUMERIC(18, 2)` | Yes | 없음 | 숫자로 변환 가능한 가격. 조건부 가격 문자열은 `NULL` |
| `currency` | `CHAR(3)` | No | `'KRW'` | 통화 코드 |
| `payload` | `JSONB` | No | `'{}'::jsonb` | 가격 section 전체 |
| `created_at` | `TIMESTAMPTZ` | No | `now()` | DB row 생성 시각 |

제약 조건:

- Primary key: `id`
- Foreign key: `product_id REFERENCES products(id) ON DELETE CASCADE`
- Unique: `(product_id, collected_at, market, price_type)`

인덱스:

- `idx_product_prices_product_collected_at` on `(product_id, collected_at)`

저장 매핑:

- `prices.domeCurrentSupplyPrice` -> `market='dome'`, `price_type='current_supply'`
- `prices.supplyCurrentSupplyPrice` -> `market='supply'`, `price_type='current_supply'`
- `prices.minimumRetailPrice` -> `market='retail'`, `price_type='minimum_retail'`
- `prices.recommendedRetailPrice` -> `market='retail'`, `price_type='recommended_retail'`
- `prices.currentSupplyPrice` -> `market=<platform>`, `price_type='current_supply'`
- `prices.fixedPrice` -> `market=<platform>`, `price_type='fixed'`
- 위 값이 없으면 primary 가격 후보를 `market=<platform>`, `price_type='primary'`로 저장한다.

## `product_inventory`

수집 시점별 재고 snapshot을 저장한다.

| 컬럼 | 타입 | Null | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | sequence | PK |
| `product_id` | `BIGINT` | No | 없음 | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | No | 없음 | 수집 시각 |
| `stock_quantity` | `NUMERIC(18, 2)` | Yes | 없음 | 숫자로 변환 가능한 재고. 주로 `inventory.stockQuantity` |
| `payload` | `JSONB` | No | `'{}'::jsonb` | inventory section 전체 |
| `created_at` | `TIMESTAMPTZ` | No | `now()` | DB row 생성 시각 |

제약 조건:

- Primary key: `id`
- Foreign key: `product_id REFERENCES products(id) ON DELETE CASCADE`
- Unique: `(product_id, collected_at)`

인덱스:

- `idx_product_inventory_product_collected_at` on `(product_id, collected_at)`

## `product_shipping_fees`

수집 시점별 배송비 snapshot을 저장한다.

| 컬럼 | 타입 | Null | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | sequence | PK |
| `product_id` | `BIGINT` | No | 없음 | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | No | 없음 | 수집 시각 |
| `market` | `TEXT` | No | `'default'` | 배송비 market. 예: `coupang`, `ownerclan`, `dome`, `supply` |
| `fee` | `NUMERIC(18, 2)` | Yes | 없음 | 기본 수량 1 기준으로 계산 가능한 배송비 |
| `shipping_type` | `TEXT` | Yes | 없음 | 배송비 타입. 예: `fixed`, `quantity_proportional`, `quantity_tiered`, `free`, `unknown` |
| `is_free_shipping` | `BOOLEAN` | Yes | 없음 | source payload의 무료배송 여부 |
| `payload` | `JSONB` | No | `'{}'::jsonb` | 배송 section과 파서 결과. `shipping_payment`, `remote_area_fee` 등 보조값 포함 |
| `created_at` | `TIMESTAMPTZ` | No | `now()` | DB row 생성 시각 |

제약 조건:

- Primary key: `id`
- Foreign key: `product_id REFERENCES products(id) ON DELETE CASCADE`
- Unique: `(product_id, collected_at, market)`

인덱스:

- `idx_product_shipping_fees_product_collected_at` on `(product_id, collected_at)`

저장 매핑:

- 도매꾹/도매매 `domeFee`, `domeFeeType` -> `market='dome'`
- 도매꾹/도매매 `supplyFee`, `supplyFeeType` -> `market='supply'`
- 그 외 배송비 -> `market=<platform>`
- 배송비 부담 방식은 별도 컬럼이 아니라 `payload.shipping_payment`에 저장한다.
- 도서산간 추가배송비는 `payload.remote_area_fee`에 보존하고 `fee`에는 합산하지 않는다.

## `product_raw_samples`

디버깅용 raw 응답 샘플을 저장한다.

| 컬럼 | 타입 | Null | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | sequence | PK |
| `platform` | `TEXT` | No | 없음 | 수집 플랫폼 |
| `external_product_id` | `TEXT` | No | 없음 | 플랫폼 원본 상품 ID |
| `collected_at` | `TIMESTAMPTZ` | No | 없음 | 수집 시각 |
| `payload` | `JSONB` | No | `'{}'::jsonb` | parser/normalizer가 남긴 raw 샘플 |
| `created_at` | `TIMESTAMPTZ` | No | `now()` | DB row 생성 시각 |

제약 조건:

- Primary key: `id`
- Unique: `(platform, collected_at, external_product_id)`

인덱스:

- `idx_product_raw_samples_platform_collected_at` on `(platform, collected_at)`

저장 제한:

- `save_product_raw_samples_if_enabled()` 호출당 최대 3개 상품만 저장한다.

## `product_search_ranks`

discovery/search에서 순위 의미가 있는 상품 발견 이력을 저장한다.

| 컬럼 | 타입 | Null | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | sequence | PK |
| `platform` | `TEXT` | No | 없음 | 수집 플랫폼 |
| `collected_at` | `TIMESTAMPTZ` | No | 없음 | 수집 시각 |
| `keyword` | `TEXT` | Yes | 없음 | 검색 키워드 |
| `category_code` | `TEXT` | Yes | 없음 | 카테고리 코드 |
| `category_name` | `TEXT` | Yes | 없음 | 카테고리명 |
| `category_path` | `JSONB` | No | `'[]'::jsonb` | 카테고리 경로 배열 |
| `market` | `TEXT` | No | `'default'` | 검색 market. 예: `dome`, `supply`, `default` |
| `sort` | `TEXT` | No | `''` | 정렬 기준. `sort` 또는 `sortBy` 입력값 |
| `reason` | `TEXT` | Yes | 없음 | 발견 또는 저장 이유 |
| `external_product_id` | `TEXT` | No | 없음 | 플랫폼 원본 상품 ID |
| `rank` | `INTEGER` | No | 없음 | 검색 결과 순위. 입력값이 없으면 현재 저장 함수에서 `0` |
| `payload` | `JSONB` | No | `'{}'::jsonb` | 순위 저장에 사용한 record 전체 |
| `created_at` | `TIMESTAMPTZ` | No | `now()` | DB row 생성 시각 |

제약 조건:

- Primary key: `id`
- Unique: `(platform, collected_at, market, sort, external_product_id, rank)`

인덱스:

- `idx_product_search_ranks_platform_collected_at` on `(platform, collected_at)`

플랫폼별 정책:

- 도매꾹/도매매 discovery/search 결과는 순위 의미가 있는 경우 저장한다.
- 오너클랜은 Seller GraphQL API가 인기순, 판매량순, 랭킹 순위 의미의 상품 순위 데이터를 기준으로 제공하지 않아 저장하지 않는다.

## `product_change_history`

`products.comparable_fingerprint`가 달라질 때 append-only로 변경 이력을 저장한다.

| 컬럼 | 타입 | Null | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | sequence | PK |
| `product_id` | `BIGINT` | No | 없음 | `products.id` FK |
| `changed_at` | `TIMESTAMPTZ` | No | 없음 | 변경 감지 기준 수집 시각 |
| `change_type` | `TEXT` | No | 없음 | `initial` 또는 `update` |
| `before_fingerprint` | `CHAR(64)` | Yes | 없음 | 변경 전 fingerprint. 최초 저장 시 `NULL` |
| `after_fingerprint` | `CHAR(64)` | No | 없음 | 변경 후 fingerprint |
| `before_payload` | `JSONB` | Yes | 없음 | 변경 전 comparable payload. 최초 저장 시 `NULL` |
| `after_payload` | `JSONB` | No | 없음 | 변경 후 comparable payload |
| `created_at` | `TIMESTAMPTZ` | No | `now()` | DB row 생성 시각 |

제약 조건:

- Primary key: `id`
- Foreign key: `product_id REFERENCES products(id) ON DELETE CASCADE`

인덱스:

- `idx_product_change_history_product_changed_at` on `(product_id, changed_at)`

## 스키마 보강 및 backfill

`init_schema()`는 기존 DB와의 호환을 위해 아래 보강도 수행한다.

- `product_prices.market` 컬럼이 없으면 추가한다.
- `product_shipping_fees.market` 컬럼이 없으면 추가한다.
- 예전 unique constraint인 `product_prices_product_id_collected_at_price_type_key`를 제거한다.
- 예전 unique constraint인 `product_shipping_fees_product_id_collected_at_key`를 제거한다.
- `product_prices_product_collected_market_type_key` constraint가 없으면 추가한다.
- `product_shipping_fees_product_collected_market_key` constraint가 없으면 추가한다.
- 기존 `market='default'` 가격 row에서 도매꾹/도매매 및 오너클랜 가격 row를 market/type별로 backfill한다.
- 기존 `market='default'` 배송비 row에서 도매꾹/도매매 및 플랫폼별 배송비 row를 backfill한다.

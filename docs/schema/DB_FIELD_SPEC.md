# DB 필드 명세

스키마 생성과 기존 DB 보강은 [postgres_storage.py](../../postgres_storage.py)의 `init_schema()`가 담당합니다.

## `products`

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

## `product_prices`

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

## `product_inventory`

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `product_id` | `BIGINT` | No | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | No | 수집 시각 |
| `stock_quantity` | `NUMERIC(18, 2)` | Yes | 숫자로 변환 가능한 재고 |
| `payload` | `JSONB` | No | inventory section 보조 정보 |

Unique: `(product_id, collected_at)`

## `product_shipping_fees`

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

## `product_raw_samples`

디버깅용 API 원본 샘플을 제한적으로 저장합니다. Unique: `(platform, collected_at, external_product_id)`.

## `product_change_history`

`products` scalar 컬럼과 최신 가격/재고/배송 snapshot row를 비교해서 값이 달라진 시점만 저장합니다.

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | PK |
| `product_id` | `BIGINT` | No | `products.id` FK |
| `changed_at` | `TIMESTAMPTZ` | No | 변경이 관측된 수집 시각 |
| `change_type` | `TEXT` | No | `initial`, `update` |
| `changed_fields` | `TEXT[]` | No | 값이 달라진 필드 경로 목록 |

Index: `(product_id, changed_at)`

## `product_search_ranks`

순위 의미가 있는 discovery/search 결과만 저장합니다.

Unique: `(platform, collected_at, keyword, category_code, market, sort, external_product_id, rank)`.

## `product_discovery_targets`

상세 수집 대상으로 사용할 상품 ID 목록을 저장합니다.

Unique: `(platform, external_product_id)`.

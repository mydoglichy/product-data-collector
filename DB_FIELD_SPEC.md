# DB 필드 명세

스키마 생성과 기존 DB 보강은 [postgres_storage.py](postgres_storage.py)의 `init_schema()`가 담당한다.

## `products`

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | PK |
| `platform` | `TEXT` | No | 수집 플랫폼. 예: `coupang`, `ownerclan`, `domeggook` |
| `external_product_id` | `TEXT` | No | 플랫폼 원본 상품 ID |
| `product_name` | `TEXT` | Yes | 최신 상품명 |
| `product_url` | `TEXT` | Yes | 최신 상품 URL |
| `image_url` | `TEXT` | Yes | 최신 대표 이미지 URL |
| `current_payload` | `JSONB` | No | raw/추적 query 등 volatile 값을 제거한 최신 정규화 payload |
| `comparable_payload` | `JSONB` | No | 변경 감지 대상 payload |
| `comparable_fingerprint` | `CHAR(64)` | No | `comparable_payload` SHA-256 |
| `first_seen_at` | `TIMESTAMPTZ` | No | 최초 관측 시각 |
| `last_collected_at` | `TIMESTAMPTZ` | No | 마지막 수집 시각 |

Unique: `(platform, external_product_id)`

## `product_prices`

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `product_id` | `BIGINT` | No | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | No | 수집 시각 |
| `market` | `TEXT` | No | 가격 market. 예: `ownerclan`, `dome`, `supply`, `retail` |
| `price_type` | `TEXT` | No | `primary`, `current_supply`, `fixed`, `minimum_retail`, `recommended_retail` |
| `amount` | `NUMERIC(18, 2)` | Yes | 숫자로 변환 가능한 가격. 조건식/비정형 값은 `NULL` |
| `currency` | `CHAR(3)` | No | 기본 `KRW` |
| `payload` | `JSONB` | No | 가격 section 전체 |

Unique: `(product_id, collected_at, market, price_type)`

## `product_inventory`

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `product_id` | `BIGINT` | No | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | No | 수집 시각 |
| `stock_quantity` | `NUMERIC(18, 2)` | Yes | 숫자로 변환 가능한 재고 |
| `payload` | `JSONB` | No | inventory section 전체 |

Unique: `(product_id, collected_at)`

## `product_shipping_fees`

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `product_id` | `BIGINT` | No | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | No | 수집 시각 |
| `market` | `TEXT` | No | 배송비 market. 예: `coupang`, `ownerclan`, `dome`, `supply` |
| `fee` | `NUMERIC(18, 2)` | Yes | API/정규화 payload에서 단일 숫자로 확인되는 기본 배송비 원본값. 수량별 조건식은 계산하지 않고 `NULL` |
| `shipping_type` | `TEXT` | Yes | `fixed`, `quantity_proportional`, `quantity_tiered`, `free`, `unknown` |
| `is_free_shipping` | `BOOLEAN` | Yes | 확인 가능한 무료배송 여부 |
| `payload` | `JSONB` | No | 원본 배송비 값, 원본 타입, 부담 방식, 지역 추가배송비, 파싱 규칙 |

Unique: `(product_id, collected_at, market)`

저장 규칙:

- 도매꾹 `deli.dome.fee/tbl/type`은 `market='dome'` row에 저장한다.
- 도매매 `deli.supply.fee/tbl/type`은 `market='supply'` row에 저장한다.
- 도매매 배송비가 없으면 도매꾹 배송비로 임의 fallback row를 만들지 않는다.
- 오너클랜 `shippingFee/shippingType`은 `market='ownerclan'` row에 저장한다.
- `payload.shipping_fee_raw`와 `payload.shipping_fee_type_raw`는 API 원본 값을 보존한다.
- `payload.shipping_rules`는 `N+fee|...` 조건식을 파싱 가능한 구조로 저장한다.
- `payload.requires_quantity_calculation=True`인 row는 플랫폼 서버가 판매수량 기준으로 계산해야 한다.
- `payload.shipping_payment`는 `free`, `prepaid`, `collect`, `buyer_choice`, `unknown` 중 하나이다.
- `payload.remote_area_fee.jeju/islands`는 지역 추가배송비이며 `fee`에는 합산하지 않는다.

## `product_raw_samples`

raw 디버깅 샘플을 저장한다. Unique: `(platform, collected_at, external_product_id)`.

## `product_search_ranks`

순위 의미가 있는 discovery/search 결과를 저장한다. Unique: `(platform, collected_at, market, sort, external_product_id, rank)`.

## 스키마 보강

현재 `init_schema()`는 기존 DB 호환을 위해 `product_prices.market`, `product_shipping_fees.market`, market 포함 unique constraint, 기존 default row backfill을 처리한다. 이번 배송비 정책 변경은 payload 의미 보강으로 충분하므로 새 컬럼은 추가하지 않는다.

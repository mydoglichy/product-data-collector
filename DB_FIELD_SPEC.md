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
| `backup_image_url` | `TEXT` | Yes | 최신 예비 이미지 URL |
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
| `amount` | `NUMERIC(18, 2)` | Yes | 숫자로 변환 가능한 가격. 쉼표, 공백, `원`, `$` 표기는 제거해 저장하며 조건식/비정형 값은 `NULL` |
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

저장 규칙:

- `stock_quantity`와 payload에 의미 있는 원본 값이 모두 없으면 row를 저장하지 않는다.
- `stock_quantity=0`은 실제 재고 0으로 보고 저장한다.

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

- 배송비, 배송비 타입, 무료배송 여부, payload 원본 값이 모두 없으면 row를 저장하지 않는다.
- `fee=0`과 `is_free_shipping=False`는 의미 있는 값으로 보고 저장한다.
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

순위 의미가 있는 discovery/search 결과만 저장한다.

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `platform` | `TEXT` | No | 수집 플랫폼. 도매꾹/도매매는 `domeggook` |
| `collected_at` | `TIMESTAMPTZ` | No | 리스트 수집 시각 |
| `keyword` | `TEXT` | No | 검색어 또는 discovery 카테고리명. 없으면 빈 문자열 |
| `category_code` | `TEXT` | No | 카테고리 코드. 없으면 빈 문자열 |
| `category_name` | `TEXT` | Yes | 카테고리명 |
| `category_path` | `JSONB` | No | 카테고리 경로 |
| `market` | `TEXT` | No | `dome`, `supply` 등 API market |
| `sort` | `TEXT` | No | API 실제 정렬 코드. 응답 `header.sort`가 있으면 요청값보다 우선 저장 |
| `reason` | `TEXT` | Yes | 사람이 읽는 수집 이유/라벨 |
| `external_product_id` | `TEXT` | No | 외부 상품번호 |
| `rank` | `INTEGER` | No | 전체 결과 기준 순위 |
| `payload` | `JSONB` | No | 저장 record 원본 |

도매꾹/도매매 discovery는 자식 카테고리가 없는 최하위 카테고리만 대상으로 삼고, 각 카테고리/마켓/정렬 조합의 모든 리스트 페이지를 순회한다. 도매꾹/도매매 `da`는 공식 의미가 상품정보 등록/수정일 최근순인 최근등록순이므로 랭킹 데이터로 저장하지 않는다. `ha`(인기상품순), `rd`(도매꾹랭킹순)처럼 실제 순위 분석에 사용하는 정렬만 저장한다. `aa`, `ad`, `sd`, `qa`, `qd`, `se`는 현재 프로젝트에서는 가격, 신규판매자, 판매단위, 정확도 기준의 단순 정렬로 보고 순위 이력 저장 대상에서 제외한다.

`rank`는 페이지 내 순번이 아니라 전체 결과 기준 순위이며 `(currentPage - 1) * itemsPerPage + 페이지 내 순번`으로 계산한다. rank가 없는 데이터에는 `0`을 사용하지 않고 저장하지 않는다.

Unique: `(platform, collected_at, keyword, category_code, market, sort, external_product_id, rank)`. 순위 이력은 상품번호 단독 unique가 아니며, 같은 상품도 다른 수집 시각, keyword, category, market, sort 조건에서 각각 보존된다.

## 스키마 보강

현재 `init_schema()`는 기존 DB 호환을 위해 `product_prices.market`, `product_shipping_fees.market`, market 포함 unique constraint, 기존 default row backfill을 처리한다.

`product_search_ranks`는 도매꾹/도매매 비랭킹 sort(`da`, `aa`, `ad`, `sd`, `qa`, `qd`, `se`)와 `rank <= 0`인 기존 row를 제거하고, unique 기준을 `(platform, collected_at, keyword, category_code, market, sort, external_product_id, rank)`로 보강한다.

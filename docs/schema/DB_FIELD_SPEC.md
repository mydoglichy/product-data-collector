# DB 필드 명세

스키마 생성과 기존 DB 보강은 [postgres_storage.py](../../postgres_storage.py)의 `init_schema()`가 담당합니다.

## `products`

상품 master와 식별 정보의 최신값만 저장합니다.

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | PK |
| `platform` | `TEXT` | No | 수집 플랫폼: `coupang`, `ownerclan`, `domeggook` |
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
| `seller_excellent_seller` | `BOOLEAN` | Yes | 우수 판매자 여부 |
| `seller_average_satisfaction` | `TEXT` | Yes | 판매자 평균 만족도 |
| `seller_review_count` | `NUMERIC(18, 2)` | Yes | 판매자 리뷰 수 |
| `first_seen_at` | `TIMESTAMPTZ` | No | 최초 관측 시각 |
| `last_collected_at` | `TIMESTAMPTZ` | No | 마지막 수집 시각 |

Unique: `(platform, external_product_id)`

## `product_history`

가격, 재고, 배송, 판매 상태 등 추세 분석 대상 값이 최초 수집되었거나 실제 변경된 시점만 저장합니다.

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | PK |
| `product_id` | `BIGINT` | No | `products.id` FK |
| `observed_at` | `TIMESTAMPTZ` | No | 변경이 관측된 수집 시각 |
| `change_type` | `TEXT` | No | `initial`, `update` |
| `changed_fields` | `TEXT[]` | No | 변경된 핵심 필드 경로 |
| `prices` | `JSONB` | No | 변경 후 가격 전체 상태. 가격 종류별 row와 원본 보조 payload 포함 |
| `inventory` | `JSONB` | No | 변경 후 재고 전체 상태. 재고 수량, MOQ/주문 단위, 옵션 상태 포함 |
| `shipping` | `JSONB` | No | 변경 후 배송 전체 상태. 배송비, 배송 유형, 무료배송 여부, 조건식 원문 포함 |
| `status` | `TEXT` | Yes | 변경 후 판매 상태 |

Indexes:

- `(product_id, observed_at)`
- `GIN(changed_fields)`

## 삭제된 snapshot 테이블

다음 테이블은 더 이상 생성하거나 유지하지 않습니다. `init_schema()`는 기존 DB에 이 테이블이 있으면 drop합니다.

- `product_prices`
- `product_inventory`
- `product_shipping_fees`

가격, 재고, 배송 이력의 저장 위치는 `product_history`입니다. 기존 snapshot row만으로는 새 `product_history` row가 요구하는 변경 후 전체 핵심 상태를 안전하게 복원할 수 없으므로, 임의 마이그레이션은 수행하지 않습니다.

## 변화율 probe 결과

2026-09-06에 오너클랜 최하위 카테고리 처음 100개, 카테고리별 상위 최대 100개를 저장 없이 비교했습니다. 약 3일 전 legacy snapshot 대비 기존 상품 3,992개 중 핵심 값이 바뀐 상품은 31개였습니다. 기존 상품 기준 변경률은 0.78%입니다.

## 유지 테이블

`product_raw_samples`는 디버깅용 제한 raw sample을 저장합니다. Unique: `(platform, collected_at, external_product_id)`.

`product_search_ranks`는 순위 의미가 있는 discovery/search 결과를 저장합니다. Unique: `(platform, collected_at, keyword, category_code, market, sort, external_product_id, rank)`.

`product_discovery_targets`는 상세 수집 대상으로 사용할 상품 ID 목록을 저장합니다. Unique: `(platform, external_product_id)`.

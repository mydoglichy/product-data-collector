# DB 스키마

스키마 생성과 기존 DB 보강은 [postgres_storage.py](../../product_data_collector/persistence/postgres_storage.py)의 `init_schema()`가 담당합니다. 현재 운영 DB의 public schema 기준 테이블은 다음 6개입니다.

- `products`: 상품 master 최신값
- `product_history`: 가격, 재고, 배송, 판매 상태 변경 이력
- `product_raw_samples`: 제한된 raw API sample
- `product_search_ranks`: 검색/discovery 순위 결과
- `product_discovery_targets`: 상세 수집 대상 상품 ID
- `schema_migrations`: DB 구조 변경 적용 기록

## 저장 흐름

1. 플랫폼별 parser/normalizer가 API 응답을 공통 상품 구조로 정규화합니다.
2. `save_product_snapshots_if_enabled()`가 정규화된 상품을 batch로 모읍니다.
3. batch의 기존 `products` row와 최신 `product_history` row를 한 번에 조회합니다.
4. 상품 master 정보와 플랫폼별 보조/리스크 정보는 `products`에 bulk upsert합니다.
5. 가격, 재고, 배송, 상태, MOQ/옵션 등 추세 대상 값이 최초 수집되었거나 실제로 변경된 상품만 `product_history`에 bulk insert합니다.
6. `save_product_raw_samples_if_enabled()`는 제한된 raw sample만 `product_raw_samples`에 저장합니다.
7. `save_search_ranks_if_enabled()`는 순위 의미가 있는 discovery/search 결과의 정규화된 순위 필드만 `product_search_ranks`에 저장합니다.
8. `save_discovered_product_ids_if_enabled()`는 상세 수집 대상 상품 ID와 발견 맥락 필드만 `product_discovery_targets`에 저장합니다.

기본 상품 저장 batch size는 `1000`입니다. `.env`의 `POSTGRES_PRODUCT_BATCH_SIZE`로 조정할 수 있습니다. 각 batch는 별도 트랜잭션으로 처리하고, 실패 시 해당 batch를 한 번 재시도합니다. 재시도 후에도 실패하면 해당 batch만 rollback하고 다음 batch 처리를 계속합니다.

## 변경 감지

`products`에는 상품명, URL, 이미지, 판매자 정보 같은 master 최신값과 `source_specific` 플랫폼별 보조 정보를 저장합니다. 이 값만 바뀐 경우에는 `product_history` row를 만들지 않습니다.

`source_specific`은 공통 컬럼으로 펼치기 애매한 공급사별 최신 보조 정보 저장 위치입니다. 도매꾹/도매매는 인증정보, 상품정보고시, 반품정책, 인기/최저가 비교, 판매자 휴가, 세금계산서 리스크 보조값을 저장하고, 오너클랜은 인증정보/상품정보고시/반품배송비, 오픈마켓 판매 가능 여부, 유통금지 속성 등을 저장합니다.

`product_history`는 최신 history row의 핵심 상태와 현재 정규화 상태를 비교합니다. 가격만 바뀌어도 해당 시점의 가격, 재고, 배송 전체 상태를 함께 저장합니다. 값이 모두 동일하면 새 history row를 저장하지 않습니다.

변경 비교는 숫자 문자열과 숫자를 같은 값으로 보도록 canonicalize하지만, 배송비 조건식 원문 등 저장 payload는 그대로 보존합니다.

## `products`

상품 master와 식별 정보의 최신값만 저장합니다.

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | PK |
| `platform` | `TEXT` | No | 수집 플랫폼. 예: `coupang`, `ownerclan`, `domeggook` |
| `external_product_id` | `TEXT` | No | 플랫폼 원본 상품 ID |
| `product_name` | `TEXT` | Yes | 최신 상품명 |
| `product_url` | `TEXT` | Yes | 최신 상품 URL. 원본 URL 필드가 없으면 플랫폼 상품 ID로 정규화 URL 생성 |
| `image_url` | `TEXT` | Yes | 최신 대표 이미지 URL |
| `backup_image_url` | `TEXT` | Yes | 최신 예비 이미지 URL |
| `source_specific` | `JSONB` | No | 플랫폼별 최신 보조/리스크/고시/정책 정보. 기본값 `{}` |
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

Indexes:

- `(platform, external_product_id)`
- `(last_collected_at)`

## `product_history`

가격, 재고, 배송, 판매 상태 등 추세 분석 대상 값이 최초 수집되었거나 실제 변경된 시점만 저장합니다.

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | PK |
| `product_id` | `BIGINT` | No | `products.id` FK. `products` 삭제 시 함께 삭제 |
| `observed_at` | `TIMESTAMPTZ` | No | 변경이 관측된 수집 시각 |
| `change_type` | `TEXT` | No | `initial`, `update` |
| `changed_fields` | `TEXT[]` | No | 변경된 핵심 필드 경로 |
| `prices` | `JSONB` | No | 변경 후 가격 전체 상태. 가격 종류별 row와 원본 보조 payload 포함 |
| `inventory` | `JSONB` | No | 변경 후 재고 전체 상태. 재고 수량, MOQ/주문 단위, 옵션 상태 포함 |
| `shipping` | `JSONB` | No | 변경 후 배송 전체 상태. 배송비, 배송 유형, 무료배송 여부, 조건식 원문 포함 |
| `status` | `TEXT` | Yes | 변경 후 판매 상태 |
| `created_at` | `TIMESTAMPTZ` | No | history row 생성 시각. 기본값 `now()` |

Indexes:

- `(product_id, observed_at)`
- `GIN(changed_fields)`

## `product_raw_samples`

디버깅용 제한 raw sample을 저장합니다. 전체 API 응답을 장기 보관하기 위한 주 저장소가 아니라, 문제 분석에 필요한 일부 원본 payload 보관용입니다. 플랫폼별 보관 수는 최대 100개이며 새 sample 저장 후 초과분은 최신 `collected_at` 기준으로 삭제합니다.

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | PK |
| `platform` | `TEXT` | No | 수집 플랫폼 |
| `external_product_id` | `TEXT` | No | 플랫폼 원본 상품 ID |
| `collected_at` | `TIMESTAMPTZ` | No | sample 수집 시각 |
| `payload` | `JSONB` | No | 제한 저장된 원본 payload. 기본값 `{}` |
| `created_at` | `TIMESTAMPTZ` | No | row 생성 시각. 기본값 `now()` |

Unique: `(platform, collected_at, external_product_id)`

Indexes:

- `(platform, collected_at)`

## `product_search_ranks`

순위 의미가 있는 discovery/search 결과를 저장합니다. 검색어, 카테고리, 마켓, 정렬 조건별 특정 수집 시각의 상품 순위를 남깁니다. 원본 discovery/search record payload는 저장하지 않고 순위 분석에 필요한 필드만 컬럼으로 보관합니다.

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | PK |
| `platform` | `TEXT` | No | 수집 플랫폼 |
| `collected_at` | `TIMESTAMPTZ` | No | 검색/discovery 수집 시각 |
| `keyword` | `TEXT` | No | 검색어. 없으면 빈 문자열 |
| `category_code` | `TEXT` | No | 카테고리 코드. 없으면 빈 문자열 |
| `category_name` | `TEXT` | Yes | 카테고리명 |
| `category_path` | `JSONB` | No | 카테고리 경로 배열. 기본값 `[]` |
| `market` | `TEXT` | No | 마켓 구분. 기본값 `default` |
| `sort` | `TEXT` | No | 정렬 조건. 없으면 빈 문자열 |
| `reason` | `TEXT` | Yes | 수집/발견 사유 |
| `external_product_id` | `TEXT` | No | 플랫폼 원본 상품 ID |
| `rank` | `INTEGER` | No | 검색/discovery 결과 순위 |
| `created_at` | `TIMESTAMPTZ` | No | row 생성 시각. 기본값 `now()` |

Unique: `(platform, collected_at, keyword, category_code, market, sort, external_product_id, rank)`

Indexes:

- `(platform, collected_at)`

## `product_discovery_targets`

상세 수집 대상으로 사용할 상품 ID 목록을 저장합니다. discovery 단계에서 찾은 상품을 상세 수집 workflow가 다시 조회할 수 있게 남깁니다. 원본 discovery record payload는 저장하지 않고 대상 식별과 발견 맥락에 필요한 필드만 컬럼으로 보관합니다.

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `id` | `BIGSERIAL` | No | PK |
| `platform` | `TEXT` | No | 수집 플랫폼 |
| `external_product_id` | `TEXT` | No | 플랫폼 원본 상품 ID |
| `active` | `BOOLEAN` | No | 상세 수집 대상 활성 여부. 기본값 `true` |
| `first_discovered_at` | `TIMESTAMPTZ` | No | 최초 발견 시각 |
| `last_discovered_at` | `TIMESTAMPTZ` | No | 마지막 발견 시각 |
| `keyword` | `TEXT` | Yes | 발견에 사용된 검색어 |
| `category_code` | `TEXT` | Yes | 발견 카테고리 코드 |
| `category_name` | `TEXT` | Yes | 발견 카테고리명 |
| `market` | `TEXT` | Yes | 발견 마켓 구분 |
| `reason` | `TEXT` | Yes | 발견/수집 사유 |
| `created_at` | `TIMESTAMPTZ` | No | row 생성 시각. 기본값 `now()` |
| `updated_at` | `TIMESTAMPTZ` | No | 마지막 갱신 시각. 기본값 `now()` |

Unique: `(platform, external_product_id)`

Indexes:

- `(platform, active, first_discovered_at)`

## `schema_migrations`

DB 구조 변경 작업이 이미 적용됐는지 기록하는 관리용 테이블입니다. 상품 데이터 저장용 테이블이 아니라, 같은 구조 변경을 중복 실행하지 않기 위한 이력표입니다.

| 컬럼 | 타입 | Null | 설명 |
| --- | --- | --- | --- |
| `name` | `TEXT` | No | 적용한 마이그레이션 이름. PK |
| `applied_at` | `TIMESTAMPTZ` | No | 적용 시각. 기본값 `now()` |

## 삭제된 snapshot 테이블

다음 테이블은 더 이상 생성하거나 유지하지 않습니다. `init_schema()`는 기존 DB에 이 테이블이 있으면 drop합니다.

- `product_prices`
- `product_inventory`
- `product_shipping_fees`

가격, 재고, 배송 이력의 저장 위치는 `product_history.prices`, `product_history.inventory`, `product_history.shipping` JSONB입니다. 기존 snapshot row만으로는 새 `product_history` row가 요구하는 변경 후 전체 핵심 상태를 안전하게 복원할 수 없으므로, 임의 마이그레이션은 수행하지 않습니다.

# 데이터 저장 스키마

이 문서는 현재 코드 기준으로 쿠팡, 오너클랜, 도매꾹/도매매 수집 데이터가 파일과 PostgreSQL에 어떻게 저장되는지 정리한다. PostgreSQL 저장은 `.env`의 `POSTGRES_ENABLED`가 `1`, `true`, `yes`, `y`, `on` 중 하나일 때만 실행된다.

## 공통 저장 흐름

| 구분 | 파일 저장 | PostgreSQL 저장 |
| --- | --- | --- |
| 쿠팡 | 검색 결과 JSONL, raw 샘플, summary, latest/history, collection run | 검색 결과 상품 snapshot을 공통 테이블에 upsert |
| 오너클랜 | 추적 상품, 상품 snapshot, 검색 순위, raw 샘플, latest/history, failures, collection run, incremental state | 상품 상세 snapshot을 공통 테이블에 upsert |
| 도매꾹/도매매 | 카테고리 캐시, 추적 상품, 상품 snapshot, 검색 순위, raw 샘플, latest/history, failures, collection run | 상품 상세 snapshot을 공통 테이블에 upsert |

현재 PostgreSQL에 적재되는 것은 상품 master, 가격 snapshot, 재고 snapshot, 배송비 snapshot, 변경 이력이다. 검색 순위(`*_search-ranks.json`), raw 샘플, 실패 요약, 실행 로그, checkpoint/state 파일은 파일로만 저장한다.

## PostgreSQL 공통 테이블

PostgreSQL 스키마는 [postgres_storage.py](postgres_storage.py)의 `init_schema()`에서 생성한다. 플랫폼별 원천 필드는 공통 row로 변환되어 아래 테이블에 저장된다.

### `products`

상품별 최신 상태를 저장하는 master 테이블이다. `(platform, external_product_id)`가 unique key다.

| 필드 | 타입 | 내용 |
| --- | --- | --- |
| `id` | `BIGSERIAL` | 내부 상품 ID |
| `platform` | `TEXT` | `coupang`, `ownerclan`, `domeggook` |
| `external_product_id` | `TEXT` | 외부 상품 ID. `externalProductId`, `productId`, `productKey` 순서로 선택 |
| `product_name` | `TEXT` | `productName`, `name`, `title` 중 첫 값 |
| `product_url` | `TEXT` | `productUrl`, `affiliateUrl`, `url` 중 첫 값 |
| `image_url` | `TEXT` | `imageUrl`, `productImage` 중 첫 값 |
| `current_payload` | `JSONB` | raw 제거 및 URL 정규화 후 최신 상품 payload |
| `comparable_payload` | `JSONB` | 변경 감지 대상 필드만 정규화한 payload |
| `comparable_fingerprint` | `CHAR(64)` | `comparable_payload`의 SHA-256 fingerprint |
| `first_seen_at` | `TIMESTAMPTZ` | 최초 관측 시각 |
| `last_collected_at` | `TIMESTAMPTZ` | 마지막 수집 시각 |
| `created_at` | `TIMESTAMPTZ` | DB row 생성 시각 |
| `updated_at` | `TIMESTAMPTZ` | DB row 갱신 시각 |

### `product_prices`

상품별 수집 시점 가격 snapshot이다. `(product_id, collected_at, market, price_type)`가 unique key다.

| 필드 | 타입 | 내용 |
| --- | --- | --- |
| `id` | `BIGSERIAL` | 내부 ID |
| `product_id` | `BIGINT` | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | 수집 시각 |
| `market` | `TEXT` | `default`, `coupang`, `ownerclan`, `dome`, `supply`, `retail` 등 |
| `price_type` | `TEXT` | `primary`, `current_supply`, `fixed`, `minimum_retail`, `recommended_retail` |
| `amount` | `NUMERIC(18,2)` | 숫자로 변환 가능한 가격. 조건부/구간 가격 문자열은 `NULL` |
| `currency` | `CHAR(3)` | 기본 `KRW` |
| `payload` | `JSONB` | 가격 section 전체 |
| `created_at` | `TIMESTAMPTZ` | DB row 생성 시각 |

가격 추출 우선순위는 `productPrice`, `salePrice`, `price`, `supplyPrice`이며, 없으면 가격 payload 안의 첫 숫자형 값을 사용한다. 도매꾹/도매매는 `dome`, `supply`, `retail` market row로 분리한다.

### `product_inventory`

상품별 수집 시점 재고 snapshot이다. `(product_id, collected_at)`가 unique key다.

| 필드 | 타입 | 내용 |
| --- | --- | --- |
| `id` | `BIGSERIAL` | 내부 ID |
| `product_id` | `BIGINT` | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | 수집 시각 |
| `stock_quantity` | `NUMERIC(18,2)` | `inventory.stockQuantity` |
| `payload` | `JSONB` | 재고 section 전체 |
| `created_at` | `TIMESTAMPTZ` | DB row 생성 시각 |

### `product_shipping_fees`

상품별 수집 시점 배송비 snapshot이다. `(product_id, collected_at, market)`가 unique key다.

| 필드 | 타입 | 내용 |
| --- | --- | --- |
| `id` | `BIGSERIAL` | 내부 ID |
| `product_id` | `BIGINT` | `products.id` FK |
| `collected_at` | `TIMESTAMPTZ` | 수집 시각 |
| `market` | `TEXT` | `default`, `coupang`, `ownerclan`, `dome`, `supply` |
| `fee` | `NUMERIC(18,2)` | 계산 가능한 예상 배송비. 기본 수량은 1 |
| `shipping_type` | `TEXT` | 정규화된 배송비 타입. `fixed`, `quantity_proportional`, `quantity_tiered`, `free`, `unknown` |
| `is_free_shipping` | `BOOLEAN` | 원천/정규화 payload의 `isFreeShipping` |
| `payload` | `JSONB` | 배송 section 전체. 원본 fee/type/payment 필드 보존 |
| `created_at` | `TIMESTAMPTZ` | DB row 생성 시각 |

배송비 계산 금액(`fee`)과 배송비 부담 방식(`shipping_payment`)은 분리한다. 현재 DB 컬럼에는 부담 방식 전용 컬럼이 없으므로 `payload.shipping_payment` 또는 `shipping_rows[]`의 정규화 결과로 보존한다.

### `product_change_history`

상품의 비교 fingerprint가 바뀐 경우에만 insert되는 변경 이력 테이블이다.

| 필드 | 타입 | 내용 |
| --- | --- | --- |
| `id` | `BIGSERIAL` | 내부 ID |
| `product_id` | `BIGINT` | `products.id` FK |
| `changed_at` | `TIMESTAMPTZ` | 변경 감지 시각 |
| `change_type` | `TEXT` | 최초 저장은 `initial`, 이후 변경은 `update` |
| `before_fingerprint` | `CHAR(64)` | 이전 fingerprint |
| `after_fingerprint` | `CHAR(64)` | 신규 fingerprint |
| `before_payload` | `JSONB` | 이전 비교 payload |
| `after_payload` | `JSONB` | 신규 비교 payload |
| `created_at` | `TIMESTAMPTZ` | DB row 생성 시각 |

## 변경 감지 기준

`latest-products.json`, `*_product-history.json`, `products.comparable_payload`, `product_change_history`는 [product_history.py](product_history.py)의 공통 비교 로직을 사용한다.

비교 대상 section은 다음과 같다.

| section | 내용 |
| --- | --- |
| `prices` | 가격 관련 값 |
| `inventory` | 재고, MOQ, 주문 단위 |
| `shipping` | 배송비, 배송 타입, 배송비 부담, 무료배송 여부 |
| `options` | 옵션/SKU별 가격과 수량 |
| `status` | 정규화된 판매 상태 |
| `sourceStatus` | 원천 API 판매 상태 |
| `markets` | 도매꾹/도매매 판매 채널 상태 |

비교에서 제외되는 volatile 필드는 `collectedAt`, `raw`, `rank`, `keyword`, `keywords`, `productName`, `productUrl`, `affiliateUrl`, `productImage`, `imageUrl`, `images`, 등록/수정/판매 시작/종료 시각, `firstSeenAt`, `lastSeenAt`, `lastCheckedAt`, `fingerprint`다.

누락 필드는 `{"__value__": "__MISSING__"}`로 canonicalize한다. 숫자 문자열은 가능한 경우 숫자로 정규화한다.

## 배송비 파싱 규칙

공용 배송비 파서는 [shipping_fees.py](shipping_fees.py)의 `parse_shipping_fee()`다. 도매꾹과 도매매 모두 같은 함수를 사용하며 `domeFee/domeFeeType`, `supplyFee/supplyFeeType`을 각각 처리한다.

### 결과 구조

정규화 결과는 다음 필드를 가진다.

| 필드 | 내용 |
| --- | --- |
| `shipping_type` | `fixed`, `quantity_proportional`, `quantity_tiered`, `free`, `unknown` |
| `shipping_payment` | `prepaid`, `collect`, `buyer_choice`, `free`, `unknown` |
| `shipping_fee` | 계산된 예상 배송비. DB `product_shipping_fees.fee`에 저장 |
| `shipping_fee_raw` | 원본 배송비 값 |
| `shipping_fee_type_raw` | 원본 배송비 타입 |
| `quantity_unit` | 수량별비례 최초 묶음 수량 |
| `first_fee` | 수량별비례 최초 배송비 |
| `additional_quantity_unit` | 수량별비례 추가 묶음 수량 |
| `additional_fee` | 수량별비례 추가 배송비 |
| `shipping_rules` | 수량별비례/수량별차등 원본 규칙 배열 |

### 고정배송비

`domeFee: 3000`, `domeFeeType: "고정배송비"`이면 수량과 관계없이 `3000`으로 계산한다.

### 수량별비례

형식은 `기준수량+첫배송비|기준수량+추가배송비`다.

예: `100+3000|100+3000`

| 수량 | 배송비 |
| --- | --- |
| 1-100 | 3000 |
| 101-200 | 6000 |
| 201-300 | 9000 |

계산식:

```text
first_fee + max(0, ceil(quantity / additional_quantity) - 1) * additional_fee
```

중요 사항:

- 두 번째 규칙이 첫 번째와 같아도 중복 제거하지 않는다.
- 첫 번째 항목은 최초 묶음의 수량과 배송비다.
- 두 번째 항목은 추가 묶음의 수량과 추가 배송비다.
- `100+3000|100+3000`도 유효한 수량별비례 규칙이다.

### 수량별차등

형식은 `최소수량+배송비|최소수량+배송비`다.

예: `1+3500|20+5500`

| 수량 | 배송비 |
| --- | --- |
| 1-19 | 3500 |
| 20 이상 | 5500 |

규칙은 최소수량 기준 오름차순 정렬 후, 요청 수량 이하인 규칙 중 가장 큰 최소수량의 배송비를 적용한다.

### 배송비 부담자

도매꾹/도매매 API의 `deli.who` 또는 정규화된 `shipping.feePayer`를 함께 처리한다.

| 원본 값 | 정규화 값 | 의미 |
| --- | --- | --- |
| `S`, `무료배송` | `free` | 배송비 0원 |
| `P`, `선결제` | `prepaid` | 구매자가 배송비 선결제 |
| `B`, `착불` | `collect` | 수령 시 배송비 지불 |
| `C`, `구매자 선택` | `buyer_choice` | 선결제/착불 선택 가능 |

착불이어도 예상 배송비 금액은 계산한다. `deli.add`와 도서산간 추가배송비는 일반 배송비 계산과 별개로 취급한다.

## 쿠팡 데이터 구조

### 파일

| 파일 | 내용 |
| --- | --- |
| `coupang_API/data/processed/coupang_YYYY_MMDD_HHMM_products.jsonl` | 키워드 검색 결과. 상품 1개가 JSONL 한 줄 |
| `coupang_API/data/raw/coupang_YYYY_MMDD_HHMM_raw_{keyword}.json` | 키워드별 API 원본 응답 샘플 |
| `coupang_API/data/summaries/coupang_YYYY_MMDD_HHMM_summary.json` | 실행 요약 |
| `coupang_API/data/state/product_search_checkpoint.json` | 키워드 처리 재시작 checkpoint |
| `coupang_API/data/state/latest-products.json` | 상품별 최신 정규화 상태 |
| `coupang_API/data/history/coupang_YYYY_MMDD_HHMM_product-history.json` | 변경된 상품 이력 |
| `coupang_API/data/state/collection-runs.json` | 실행 이력 |

### `*_products.jsonl` 필드

| 필드 | 내용 |
| --- | --- |
| `productId` | 쿠팡 상품 ID |
| `itemId` | `productUrl` query string의 `itemId` |
| `vendorItemId` | `productUrl` query string의 `vendorItemId` |
| `productName` | 상품명 |
| `productPrice` | 상품 가격. 숫자 문자열이면 숫자로 변환 |
| `productUrl` | 상품 URL |
| `keyword` | 검색 키워드. API 응답에 없으면 요청 키워드 |
| `rank` | 검색 결과 순위. 응답에 없으면 응답 배열 순서 |
| `isRocket` | 로켓배송 여부 |
| `isFreeShipping` | 무료배송 여부 |
| `collectedAt` | 상품 record 수집 시각 |

쿠팡은 수집 실행 중 `productId` 기준으로 `collected_products`를 만들기 때문에 latest/history/PostgreSQL 저장은 같은 실행 내 상품 ID별 마지막 record를 기준으로 한다. JSONL 파일 자체는 완전히 동일한 JSON record만 중복 제거한다.

### PostgreSQL 매핑

| PostgreSQL 필드 | 쿠팡 원천 |
| --- | --- |
| `products.platform` | `coupang` |
| `products.external_product_id` | `productId` |
| `products.product_name` | `productName` |
| `products.product_url` | `productUrl` |
| `products.image_url` | 현재 정규화 record에 없음 |
| `products.current_payload` | JSONL record에서 `raw` 제거 및 URL 정규화 |
| `products.comparable_payload.prices.productPrice` | `productPrice` |
| `products.comparable_payload.shipping.isFreeShipping` | `isFreeShipping` |
| `product_prices.market` | `coupang` |
| `product_prices.price_type` | `primary` |
| `product_prices.amount` | `productPrice` |
| `product_inventory.stock_quantity` | 없음, 보통 `NULL` |
| `product_shipping_fees.market` | `coupang` |
| `product_shipping_fees.fee` | 배송비 금액 없음. 무료배송 여부만 있으면 `NULL` |
| `product_shipping_fees.is_free_shipping` | `isFreeShipping` |

## 오너클랜 데이터 구조

### 파일

| 파일 | 내용 |
| --- | --- |
| `ownerclan_API/data/state/tracked_products.json` | 추적 대상 상품 master |
| `ownerclan_API/data/processed/ownerclan_YYYY_MMDD_HHMM_product-snapshots.json` | 상품 상세 snapshot |
| `ownerclan_API/data/processed/ownerclan_YYYY_MMDD_HHMM_search-ranks.json` | 키워드 검색 순위 이력 |
| `ownerclan_API/data/raw/ownerclan_YYYY_MMDD_HHMM_raw.json` | raw 샘플. 최대 3개 제한 |
| `ownerclan_API/data/state/latest-products.json` | 상품별 최신 정규화 상태 |
| `ownerclan_API/data/history/ownerclan_YYYY_MMDD_HHMM_product-history.json` | 변경된 상품 이력 |
| `ownerclan_API/data/summaries/ownerclan_YYYY_MMDD_HHMM_failures.json` | 실패 내역 |
| `ownerclan_API/data/state/incremental-state.json` | 증분 수집 기준 시각 |
| `ownerclan_API/data/state/collection-runs.json` | 실행 이력 |

### `tracked_products.json` 필드

| 필드 | 내용 |
| --- | --- |
| `productId` | 상품 key와 동일하게 저장 |
| `productKey` | 오너클랜 상품 key |
| `keywords` | 발견된 검색 키워드 누적 배열 |
| `reasons` | 발견 사유/정렬 조건. 예: `default`, `registerDateDesc` |
| `firstSeenAt` | 최초 발견 시각 |
| `lastSeenAt` | 마지막 발견 시각 |
| `active` | 상세 수집 대상 여부 |

### `*_product-snapshots.json`의 `products[]` 필드

| 필드 | 내용 |
| --- | --- |
| `source` | `ownerclan` |
| `productId` | 상품 key |
| `productKey` | 상품 key |
| `collectedAt` | 상세 수집 시각 |
| `status` | 정규화 상태. 예: `available`, `soldout`, `discontinued`, `unavailable` |
| `sourceStatus` | 원천 API 상태 |
| `productName` | 상품명 |
| `registeredAt` | 등록 시각 |
| `updatedAt` | 수정 시각 |
| `prices.currentSupplyPrice` | 현재 공급가 |
| `prices.fixedPrice` | 고정가 |
| `inventory.stockQuantity` | 옵션 수량 합계 |
| `inventory.stockQuantitySource` | 현재 `sum(options[].quantity)` |
| `inventory.apiStockQuantity` | API 원본 수량 |
| `options[]` | SKU/옵션 목록 |
| `shipping.fee` | 배송비 |
| `shipping.type` | 배송 타입 |
| `category.code` | 카테고리 코드 |
| `category.name` | 카테고리명 |
| `category.fullName` | 전체 카테고리명 |
| `manufacturer` | 제조사/production |
| `origin` | 원산지 |
| `model` | 모델명 |
| `sourceSpecific` | 오너클랜 고유 부가 필드 |

`options[]`는 `skuKey`, `skuType`, `optionAttributes[]`, `price`, `quantity`를 저장한다. `sourceSpecific`에는 `id`, `pricePolicy`, `taxFree`, `adultOnly`, `returnable`, `guaranteedShippingPeriod`, `openmarketSellable`, `boxQuantity`, `attributes`, `closingTime`, `vendorKey`, `certificateInformation`, `grade`, `gradeDetail`을 저장한다.

상품 상세 HTML, 이미지, 검색 키워드, metadata 일부, 반품 조건 원문은 snapshot 본문에서 제거하거나 raw 샘플 파일에만 제한적으로 보관한다.

### `*_search-ranks.json`의 `ranks[]` 필드

| 필드 | 내용 |
| --- | --- |
| `collectedAt` | 검색 수집 시각 |
| `keyword` | 검색 키워드 |
| `sortBy` | `default`, `registerDateDesc` 등 |
| `productId` | 상품 key |
| `productKey` | 상품 key |
| `rank` | 검색 순위 |

### PostgreSQL 매핑

| PostgreSQL 필드 | 오너클랜 원천 |
| --- | --- |
| `products.platform` | `ownerclan` |
| `products.external_product_id` | `productId` 또는 `productKey` |
| `products.product_name` | `productName` |
| `products.product_url` | 현재 정규화 record에 없음 |
| `products.image_url` | 현재 정규화 record에 없음 |
| `products.current_payload` | snapshot 상품 payload |
| `products.comparable_payload` | `prices`, `inventory`, `shipping`, `options`, `status`, `sourceStatus`, `markets` |
| `product_prices.market` | `ownerclan` |
| `product_prices.price_type` | `current_supply`, `fixed` |
| `product_prices.amount` | `prices.currentSupplyPrice`, `prices.fixedPrice` |
| `product_prices.payload` | `prices` 전체 |
| `product_inventory.stock_quantity` | `inventory.stockQuantity` |
| `product_inventory.payload` | `inventory` 전체 |
| `product_shipping_fees.market` | `ownerclan` |
| `product_shipping_fees.fee` | `shipping.fee` |
| `product_shipping_fees.shipping_type` | `shipping.type` 또는 `shipping.feeType` |
| `product_shipping_fees.payload` | `shipping` 전체 |

## 도매꾹/도매매 데이터 구조

도매꾹과 도매매는 같은 도매꾹 API 응답에서 채널별 필드로 들어온다. PostgreSQL 가격과 배송비는 `market = dome`, `market = supply`로 분리한다.

### 파일

| 파일 | 내용 |
| --- | --- |
| `domeggook_API/data/state/categories.json` | 도매꾹 카테고리 캐시 |
| `domeggook_API/data/state/tracked_products.json` | 추적 대상 상품 master |
| `domeggook_API/data/processed/domeggook_YYYY_MMDD_HHMM_product-snapshots.json` | 상품 상세 snapshot |
| `domeggook_API/data/processed/domeggook_YYYY_MMDD_HHMM_search-ranks.json` | 카테고리/마켓/정렬별 검색 순위 이력 |
| `domeggook_API/data/raw/domeggook_YYYY_MMDD_HHMM_raw.json` | raw 샘플. 최대 3개 제한 |
| `domeggook_API/data/state/latest-products.json` | 상품별 최신 정규화 상태 |
| `domeggook_API/data/history/domeggook_YYYY_MMDD_HHMM_product-history.json` | 변경된 상품 이력 |
| `domeggook_API/data/summaries/domeggook_YYYY_MMDD_HHMM_failures.json` | 실패 내역 |
| `domeggook_API/data/state/collection-runs.json` | 실행 이력 |

### `categories.json` 필드

| 필드 | 내용 |
| --- | --- |
| `generatedAt` | 카테고리 캐시 생성 시각 |
| `source` | `domeggook` |
| `categories[].code` | 카테고리 코드 |
| `categories[].name` | 카테고리명 |
| `categories[].depth` | 카테고리 depth |
| `categories[].path` | 상위 경로명 배열 |
| `categories[].intCode` | 숫자형 코드 |
| `categories[].locked` | 잠금 상태 |

### `tracked_products.json` 필드

| 필드 | 내용 |
| --- | --- |
| `productId` | 도매꾹/도매매 상품번호 |
| `keywords` | 발견 기준 카테고리명 누적 배열 |
| `markets` | `dome`, `supply` 누적 배열 |
| `reasons` | 정렬 사유. 예: `popular`, `recent` |
| `firstSeenAt` | 최초 발견 시각 |
| `lastSeenAt` | 마지막 발견 시각 |
| `active` | 상세 수집 대상 여부 |

### `*_product-snapshots.json`의 `products[]` 필드

| 필드 | 내용 |
| --- | --- |
| `productId` | 상품번호 |
| `collectedAt` | 상세 수집 시각 |
| `status` | 판매 상태 |
| `productName` | 상품명 |
| `registeredAt` | 등록 시각 |
| `saleStartedAt` | 판매 시작 시각 |
| `saleEndedAt` | 판매 종료 시각 |
| `prices.domeCurrentSupplyPrice` | 도매꾹 현재 공급가 |
| `prices.domeOriginalSupplyPrice` | 도매꾹 원 공급가 |
| `prices.supplyCurrentSupplyPrice` | 도매매 현재 공급가 |
| `prices.supplyOriginalSupplyPrice` | 도매매 원 공급가 |
| `prices.minimumRetailPrice` | 최소 판매가 |
| `prices.recommendedRetailPrice` | 권장 판매가 |
| `inventory.stockQuantity` | 재고 |
| `inventory.domeMoq` | 도매꾹 최소 주문 수량 |
| `inventory.domeMaxOrderQuantity` | 도매꾹 최대 주문 수량 |
| `inventory.domeOrderUnit` | 도매꾹 주문 단위 |
| `inventory.supplyOrderUnit` | 도매매 주문 단위 |
| `shipping.method` | 배송 방식 |
| `shipping.feePayer` | 배송비 부담/과금 타입. `deli.who`, `deli.pay` 등에서 추출 |
| `shipping.domeFee` | 도매꾹 배송비. 숫자 문자열은 숫자로 변환하되 수량 규칙 문자열은 보존 |
| `shipping.domeFeeRaw` | 도매꾹 배송비 원본값 |
| `shipping.domeFeeType` | 도매꾹 배송비 타입 |
| `shipping.supplyFee` | 도매매 배송비. 숫자 문자열은 숫자로 변환하되 수량 규칙 문자열은 보존 |
| `shipping.supplyFeeRaw` | 도매매 배송비 원본값 |
| `shipping.supplyFeeType` | 도매매 배송비 타입 |
| `shipping.preparationPeriod` | 배송 준비 기간 |
| `shipping.averageShippingDays` | 평균 배송 일수 |
| `shipping.fastShipping` | 빠른 배송 여부 |
| `shipping.overseasDirectShipping` | 해외 직배송 여부 |
| `markets.domeOnSale` | 도매꾹 판매 여부 |
| `markets.supplyOnSale` | 도매매 판매 여부 |
| `seller` | 판매자 ID, 닉네임, 타입, 등급, 우수판매자 여부, 만족도, 리뷰 수 |
| `category.code` | 카테고리 코드 |
| `category.name` | 카테고리명 |

`raw`는 별도 raw 샘플 파일에만 제한적으로 저장한다. 상세 설명, 이미지, 키워드 같은 큰 원문 필드는 raw 샘플에서도 제거 또는 축약한다.

### `*_search-ranks.json`의 `ranks[]` 필드

| 필드 | 내용 |
| --- | --- |
| `collectedAt` | 검색 수집 시각 |
| `keyword` | 카테고리명 |
| `categoryCode` | 카테고리 코드 |
| `categoryName` | 카테고리명 |
| `categoryPath` | 카테고리 경로 배열 |
| `market` | `dome` 또는 `supply` |
| `sort` | API 정렬 코드 |
| `reason` | 설정상의 정렬 의미. 예: `popular`, `recent` |
| `productId` | 상품번호 |
| `rank` | 검색 순위 |

### PostgreSQL 매핑

| PostgreSQL 필드 | 도매꾹/도매매 원천 |
| --- | --- |
| `products.platform` | `domeggook` |
| `products.external_product_id` | `productId` |
| `products.product_name` | `productName` |
| `products.product_url` | 현재 정규화 record에 없음 |
| `products.image_url` | 현재 정규화 record에 없음 |
| `products.current_payload` | snapshot 상품 payload |
| `products.comparable_payload` | `prices`, `inventory`, `shipping`, `options`, `status`, `sourceStatus`, `markets` |
| `product_prices.market = dome` | 도매꾹 가격 row |
| `product_prices.market = supply` | 도매매 가격 row |
| `product_prices.market = retail` | 최소/권장 판매가 row |
| `product_prices.price_type` | `current_supply`, `minimum_retail`, `recommended_retail` |
| `product_prices.amount` | `prices.domeCurrentSupplyPrice`, `prices.supplyCurrentSupplyPrice`, `prices.minimumRetailPrice`, `prices.recommendedRetailPrice` |
| `product_prices.payload` | `prices` 전체 |
| `product_inventory.stock_quantity` | `inventory.stockQuantity` |
| `product_inventory.payload` | `inventory` 전체 |
| `product_shipping_fees.market = dome` | 도매꾹 배송비 row |
| `product_shipping_fees.market = supply` | 도매매 배송비 row |
| `product_shipping_fees.fee` | `shipping.domeFee` 또는 `shipping.supplyFee`를 공용 배송비 파서로 계산한 값 |
| `product_shipping_fees.shipping_type` | 공용 배송비 파서의 정규화 타입 |
| `product_shipping_fees.payload` | `shipping` 전체. `domeFeeRaw`, `supplyFeeRaw`, `feePayer` 포함 |

## 실행 이력 파일

세 플랫폼 모두 `data/state/collection-runs.json`에 실행 단위 기록을 누적한다.

| 필드 | 내용 |
| --- | --- |
| `platform` | 플랫폼 |
| `startedAt` | 실행 시작 시각 |
| `endedAt` | 실행 종료 시각 |
| `success` | 실패가 없으면 `true` |
| `queriedProductCount` | 조회 대상 상품/키워드 수 |
| `newProductCount` | 신규 상품 수 |
| `changedProductCount` | 변경 감지 상품 수 |
| `unchangedProductCount` | 변경 없는 상품 수 |
| `failedProductCount` | 실패 수 |
| `extra` | 플랫폼별 추가 정보. 쿠팡은 성공/실패 키워드, 오너클랜은 fallback batch 정보 등을 저장할 수 있음 |

## 운영상 명시 사항

- PostgreSQL 저장은 파일 저장 이후 부가 단계이며, 비활성화되어도 파일 수집은 계속 동작한다.
- raw 샘플은 디버깅용이다. 운영 DB에 적재하지 않으며 저장 개수도 제한한다.
- 검색 순위 이력은 현재 파일로만 보관한다. 향후 노출 순위 분석을 DB에서 해야 하면 별도 rank 테이블을 추가해야 한다.
- 조건부 가격 문자열과 수량 규칙 문자열은 숫자 컬럼에 강제로 넣지 않는다. 원본은 JSON payload에 보존하고, 계산 가능한 값만 `amount` 또는 `fee`에 저장한다.
- 배송비 부담 방식과 배송비 금액은 별개다. 착불(`collect`)도 예상 배송비는 계산할 수 있다.
- 도서산간 추가배송비(`deli.add` 등)는 일반 배송비 계산과 혼동하지 않는다.
- URL은 `current_payload` 저장 전에 추적 query를 제거하고, 이미지 URL은 query 전체를 제거한다.
- 수집 시각은 ISO 문자열로 파일에 저장하고, PostgreSQL에는 UTC `TIMESTAMPTZ`로 변환한다.

# 데이터 저장 스키마

현재 운영 저장소는 PostgreSQL이다. 스키마 생성과 보강은 [postgres_storage.py](postgres_storage.py)의 `init_schema()`에서 수행한다.

## 공통 저장 흐름

1. 각 API 응답을 플랫폼별 parser/normalizer에서 공통 상품 payload로 정규화한다.
2. `postgres_storage.save_product_snapshots_if_enabled()`가 상품, 가격, 재고, 배송비, 변경 이력을 저장한다.
3. raw 샘플은 `save_product_raw_samples_if_enabled()`가 `product_raw_samples`에 저장한다.
4. 순위 의미가 있는 discovery/search 결과만 `save_search_ranks_if_enabled()`가 `product_search_ranks`에 저장한다.

## `products` 이미지 URL

- `image_url`: 정규화 payload의 `imageUrl`에서 가져온 대표 이미지 URL
- `backup_image_url`: 정규화 payload의 `backupImageUrl`에서 가져온 예비 이미지 URL
- 오너클랜과 도매꾹/도매매는 API가 여러 이미지 후보를 주더라도 대표 1개와 예비 1개만 정규화 payload와 DB 컬럼에 저장한다.
- 이미지 URL은 가격/재고/배송비 변경 감지 대상이 아니므로 `comparable_payload`에는 포함하지 않는다.

## `product_change_history`

- `products`는 상품별 최신 상태만 유지하고, `product_change_history`는 `comparable_payload`의 fingerprint가 바뀐 수집 시점을 기록한다.
- 신규 상품은 변경 전 fingerprint/payload 없이 최초 상태를 저장한다.
- 기존 상품은 `before_fingerprint`, `after_fingerprint`, `before_payload`, `after_payload`를 함께 저장해 상품 기본 정보 변경 이력을 추적한다.
- 가격, 재고, 배송비의 시점별 변화는 각각 `product_prices`, `product_inventory`, `product_shipping_fees` snapshot 테이블에서 관리한다.

## `product_search_ranks`

- 도매꾹/도매매 `da`는 공식 의미가 상품정보 등록/수정일 최근순인 최근등록순이므로 랭킹 데이터로 저장하지 않는다.
- 도매꾹/도매매 discovery는 자식 카테고리가 없는 최하위 카테고리만 대상으로 삼고, 각 카테고리/마켓/정렬 조합의 모든 리스트 페이지를 순회한다.
- `ha`(인기상품순), `rd`(도매꾹랭킹순)처럼 실제 순위 분석에 사용하는 정렬만 저장한다.
- `aa`, `ad`, `sd`, `qa`, `qd`, `se`는 현재 프로젝트에서는 순위 이력 저장 대상이 아니다.
- `rank`는 전체 결과 기준 순위다. 여러 페이지 수집 시 `(currentPage - 1) * itemsPerPage + 페이지 내 순번`으로 계산한다.
- rank가 없는 데이터는 저장하지 않으며 `rank=0`으로 대체하지 않는다.
- 순위 이력 unique 기준은 상품번호 단독이 아니다. `(platform, collected_at, keyword, category_code, market, sort, external_product_id, rank)`로 같은 상품도 수집 시각, keyword, category, market, sort가 다르면 별도 이력으로 보존한다.

## `product_inventory`

수집 시점별 재고 snapshot이다.

- `stock_quantity`와 inventory payload에 의미 있는 원본 값이 모두 없으면 row를 저장하지 않는다.
- `stock_quantity=0`은 실제 재고 0으로 보고 저장한다.

## `product_shipping_fees`

수집 시점별 배송비 snapshot이다.

- unique key: `(product_id, collected_at, market)`
- `market`: `coupang`, `ownerclan`, `dome`, `supply`
- `fee`: API/정규화 payload에서 단일 숫자로 확인되는 기본 배송비 원본값. 수량별비례, 수량별차등처럼 판매수량이 있어야 최종 배송비를 계산할 수 있는 경우 `NULL`
- `shipping_type`: 정규화된 배송비 타입. `fixed`, `quantity_proportional`, `quantity_tiered`, `free`, `unknown`
- `is_free_shipping`: source payload 또는 정규화 단계에서 확인 가능한 무료배송 여부. 확인할 수 없으면 `NULL`
- `payload`: 배송 section 원본 값과 파싱 가능한 구조화 결과

배송비, 배송비 타입, 무료배송 여부, payload 원본 값이 모두 없으면 row를 저장하지 않는다. `fee=0`과 `is_free_shipping=False`는 의미 있는 값으로 보고 저장한다.

수집기와 DB 저장 단계는 실제 판매수량 기준 배송비, 개당 배송비, MOQ 배분, 마진을 계산하지 않는다. 플랫폼 서버가 판매수량, MOQ, 판매 채널 정책을 알고 계산한다.

### 도매꾹/도매매

도매꾹/도매매 배송비는 row를 분리한다.

- `deli.dome.type`, `deli.dome.fee`, `deli.dome.tbl` -> `market='dome'`
- `deli.supply.type`, `deli.supply.fee`, `deli.supply.tbl` -> `market='supply'`
- `deli.pay`는 도매꾹 기본 부담 방식으로 보존한다.
- `deli.supply.pay`가 있으면 도매매 부담 방식은 이 값을 우선 보존한다.
- `deli.feeExtra.jeju`, `deli.feeExtra.islands`는 `payload.remote_area_fee` 및 정규화 shipping payload에 저장하며 `fee`에 합산하지 않는다.

수량별 조건식은 원문(`shipping_fee_raw`)과 구조화 규칙(`shipping_rules`)을 함께 저장한다. 도매매 배송비가 없으면 도매꾹 배송비로 임의 생성하지 않는다.

### 오너클랜

오너클랜 GraphQL 수집 필드는 현재 `shippingFee`, `shippingType`이다.

- `shippingFee` -> `shipping.fee`, `shipping.feeRaw`, `payload.source_fields.shippingFee`
- `shippingType` -> `shipping.type`, `shipping.typeRaw`, `payload.source_fields.shippingType`
- DB row는 `market='ownerclan'`

`shippingType='inAdvance'` 같은 부담 방식 성격의 값은 `payload.shipping_payment='prepaid'`로 정규화해 보존하고, `shipping_type`은 계산 가능한 배송비 타입으로 확정할 수 없으면 `unknown`으로 둔다. 무료배송은 `shippingType`이 free 계열이거나 `shippingFee`가 0인 경우에만 `is_free_shipping=True`로 보존한다.

## 스키마 변경

현재 `init_schema()`는 `product_search_ranks`에서 도매꾹/도매매 비랭킹 sort(`da`, `aa`, `ad`, `sd`, `qa`, `qd`, `se`)와 `rank <= 0`인 기존 row를 제거하고, unique 기준을 `(platform, collected_at, keyword, category_code, market, sort, external_product_id, rank)`로 보강한다.

이번 배송비 정책 변경은 기존 `product_shipping_fees.payload` JSONB에 원본과 구조화 정보를 보강하는 방식으로 처리한다. 새 DB 컬럼은 추가하지 않는다.

## 재개 수집 상태

오너클랜과 도매꾹/도매매 수집기는 저장 성공 이후에만 체크포인트를 갱신한다. 같은 `runCollectedAt`으로 재개하므로 중복 호출이 생겨도 DB unique/upsert 조건으로 같은 수집 시점의 중복 row는 추가되지 않는다.

- 오너클랜 카테고리 수집: `ownerclan_API/data/state/category-collection-state.json`
- 오너클랜 상세 수집: `ownerclan_API/data/state/detail-collection-state.json`
- 도매꾹/도매매 discovery: `domeggook_API/data/state/discovery-state.json`
- 도매꾹/도매매 상세 수집: `domeggook_API/data/state/detail-collection-state.json`

정상 완료된 재개 상태 파일은 삭제된다. 상태 파일이 남아 있으면 다음 실행에서 저장 완료 지점 다음부터 재개한다.

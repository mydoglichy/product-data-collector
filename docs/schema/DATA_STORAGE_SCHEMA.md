# 데이터 저장 흐름

현재 운영 저장소는 PostgreSQL입니다. 스키마 생성과 보강은 [postgres_storage.py](../../postgres_storage.py)의 `init_schema()`에서 수행하고, 컬럼 단위 명세는 [DB_FIELD_SPEC.md](DB_FIELD_SPEC.md)를 기준으로 관리합니다.

## 공통 흐름

1. 플랫폼별 parser/normalizer가 API 응답을 공통 상품 payload로 정규화합니다.
2. `save_product_snapshots_if_enabled()`가 `products`, 가격, 재고, 배송비, 변경 이력을 저장합니다.
3. `save_product_raw_samples_if_enabled()`가 raw 샘플을 `product_raw_samples`에 저장합니다.
4. `save_search_ranks_if_enabled()`가 순위 의미가 있는 discovery 결과만 `product_search_ranks`에 저장합니다.
5. `save_discovered_product_ids_if_enabled()`가 상세 수집 대상 상품 ID를 `product_discovery_targets`에 저장합니다.

## 변경 감지

`products`는 상품별 최신 상태만 유지합니다. `product_change_history`는 `comparable_payload`의 fingerprint가 바뀐 수집 시점에만 추가됩니다.

가격, 재고, 배송비는 변경 감지 이력에 넣지 않고 각각 snapshot 테이블에 저장합니다. 이미지 URL도 가격/재고/배송비 변경 감지 대상이 아니므로 `comparable_payload`에는 포함하지 않습니다.

## 저장 제외 기준

- 재고: `stock_quantity`와 inventory payload의 의미 있는 원본 값이 모두 없으면 저장하지 않습니다.
- 배송비: 배송비, 배송비 타입, 무료배송 여부, payload 원본 값이 모두 없으면 저장하지 않습니다.
- 순위: rank가 없거나 0 이하이면 저장하지 않습니다.
- 도매꾹/도매매 순위: `ha`, `rd`만 저장하고 `da`, `aa`, `ad`, `sd`, `qa`, `qd`, `se`는 저장하지 않습니다.

`stock_quantity=0`, `fee=0`, `is_free_shipping=False`는 의미 있는 값으로 보고 저장합니다.

## 배송비 정책

수집기와 DB 저장 단계는 실제 판매수량 기준 배송비, 개당 배송비, MOQ 배분, 마진을 계산하지 않습니다. API 원본과 정규화 가능한 조건을 저장하고, 판매수량과 채널 정책이 필요한 계산은 플랫폼 서버에서 처리합니다.

도매꾹/도매매는 `dome`, `supply` 배송비 row를 분리합니다. 수량별 조건표는 `payload.shipping_fee_raw`, `payload.shipping_rules`, `payload.requires_quantity_calculation`에 보존합니다. 도매매 배송비가 없으면 도매꾹 배송비로 임의의 `supply` row를 만들지 않습니다.

오너클랜은 `shippingFee`, `shippingType`을 수집합니다. `shippingType='inAdvance'`처럼 결제 방식에 가까운 값은 `payload.shipping_payment`에 보존하고, 계산 가능한 배송비 타입으로 확정할 수 없으면 `shipping_type='unknown'`으로 둡니다.

## 재개 상태

오너클랜과 도매꾹/도매매 수집기는 PostgreSQL 저장이 성공한 뒤에만 checkpoint를 갱신합니다. 같은 `runCollectedAt`으로 재개하므로 중복 호출이 생겨도 DB unique/upsert 조건으로 같은 수집 시점의 중복 row는 추가되지 않습니다.

- 오너클랜 단일 worker 카테고리 수집: `ownerclan_API/data/state/category-collection-state.json`
- 오너클랜 병렬 worker 카테고리 수집: `ownerclan_API/data/state/category-collection-progress.json`
- 오너클랜 보조 상세 수집: `ownerclan_API/data/state/detail-collection-state.json`
- 오너클랜 증분 수집: `ownerclan_API/data/state/incremental-state.json`
- 도매꾹/도매매 full discovery: `domeggook_API/data/state/discovery-state.json`
- 도매꾹/도매매 상세 수집: `domeggook_API/data/state/detail-collection-state.json`
- 도매꾹/도매매 daily recent discovery: `domeggook_API/data/state/recent-discovery-state.json`
- 쿠팡 keyword 검색: `coupang_API/data/state/product_search_checkpoint.json`

정상 완료된 재개 상태 파일은 삭제됩니다. 상태 파일이 남아 있으면 다음 실행에서 저장 완료 지점 다음부터 재개합니다.

## 플랫폼별 문서

플랫폼 고유 원본 필드 매핑은 각 패키지의 문서에만 둡니다.

- [도매꾹/도매매 DATA_SCHEMA.md](../../domeggook_API/DATA_SCHEMA.md)
- [오너클랜 DATA_SCHEMA.md](../../ownerclan_API/DATA_SCHEMA.md)
- [쿠팡 DATA_SCHEMA.md](../../coupang_API/DATA_SCHEMA.md)

# 데이터 저장 흐름

현재 운영 저장소는 PostgreSQL입니다. 스키마 생성과 기존 DB 보강은 [postgres_storage.py](../../postgres_storage.py)의 `init_schema()`에서 수행합니다. 수집 실행 중에는 같은 DB에 대해 `init_schema()`를 한 번만 확인하고, 이후 저장 호출은 반복 스키마 확인 없이 진행합니다.

## 공통 흐름

1. 플랫폼별 parser/normalizer가 API 응답을 공통 상품 구조로 정규화합니다.
2. `save_product_snapshots_if_enabled()`가 정규화된 상품을 batch로 모읍니다.
3. batch의 기존 `products` row와 최신 `product_history` row를 한 번에 조회합니다.
4. 상품 master 정보와 플랫폼별 보조/리스크 정보는 `products`에 bulk upsert합니다.
5. 가격, 재고, 배송, 상태, MOQ/옵션 등 추세 대상 값이 최초 수집되었거나 실제로 변경된 상품만 `product_history`에 bulk insert합니다.
6. `save_product_raw_samples_if_enabled()`는 제한된 raw sample만 `product_raw_samples`에 저장합니다. 플랫폼별 보관 수는 최대 3개이며, 새 sample 저장 후 초과분은 최신 `collected_at` 기준으로 정리합니다.
7. `save_search_ranks_if_enabled()`는 순위 의미가 있는 discovery 결과만 `product_search_ranks`에 저장합니다.
8. `save_discovered_product_ids_if_enabled()`는 상세 수집 대상 상품 ID를 `product_discovery_targets`에 저장합니다.

## 변경 감지

`products`에는 상품명, URL, 이미지, 판매자 정보 같은 master 최신값과 `source_specific` 플랫폼별 보조 정보를 저장합니다. 이 값만 바뀐 경우에는 `product_history` row를 만들지 않습니다.

`source_specific`은 공통 컬럼으로 펼치기 애매한 공급사별 최신 보조 정보 저장 위치입니다. 도매꾹/도매매는 인증정보, 상품정보고시, 반품정책, 인기/최저가 비교, 판매자 휴가, 세금계산서 리스크 보조값을 저장하고, 오너클랜은 `metadata`의 인증정보/상품정보고시/반품배송비와 `openmarketSellable`, `attributes` 등을 저장합니다.

`product_history`는 최신 history row의 핵심 상태와 현재 정규화 상태를 비교합니다. 가격만 바뀌어도 해당 시점의 가격, 재고, 배송 전체 상태를 함께 저장합니다. 값이 모두 동일하면 새 history row를 저장하지 않습니다.

변경 비교는 숫자 문자열과 숫자를 같은 값으로 보도록 canonicalize하지만, 배송비 조건식 원문 등 저장 payload는 그대로 보존합니다.

## 삭제된 snapshot 테이블

`product_prices`, `product_inventory`, `product_shipping_fees`는 더 이상 생성하거나 유지하지 않습니다. `init_schema()`는 기존 DB에 이 테이블이 있으면 drop합니다. 기존 snapshot 데이터에서 새 `product_history`의 전체 핵심 상태를 안전하게 복원할 수 없으므로 임의 마이그레이션은 수행하지 않습니다.

가격, 재고, 배송 이력의 신규 저장 위치는 `product_history.prices`, `product_history.inventory`, `product_history.shipping` JSONB입니다.

## 변화율 probe 결과

경과 약 3일 기준 기존 상품 변경률은 0.78%였습니다.

## Batch 처리

기본 상품 저장 batch size는 `1000`입니다. `.env`의 `POSTGRES_PRODUCT_BATCH_SIZE`로 조정할 수 있습니다. 각 batch는 별도 트랜잭션으로 처리하고, 실패 시 해당 batch를 한 번 재시도합니다. 재시도 후에도 실패하면 해당 batch만 rollback하고 다음 batch 처리를 계속합니다.

오너클랜 카테고리 수집처럼 페이지 단위로 자주 저장하는 workflow는 실행 중 PostgreSQL 연결을 재사용합니다. 저장할 상품이 없는 페이지는 DB 연결을 열지 않습니다.

현재는 staging 테이블을 적용하지 않습니다. API 수집 결과를 메모리 batch로 처리해도 DB 왕복과 transaction 크기를 제한할 수 있기 때문입니다. batch 크기로도 메모리 압박, 네트워크 재시도 비용, 동일 상품 중복 유입, 수집 중단 후 재개 비용이 커지면 임시 staging 테이블 또는 임시 파일 기반 적재를 추가합니다.

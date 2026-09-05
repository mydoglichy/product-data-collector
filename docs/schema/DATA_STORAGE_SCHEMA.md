# 데이터 저장 흐름

현재 운영 저장소는 PostgreSQL입니다. 스키마 생성과 기존 DB 보강은 [postgres_storage.py](../../postgres_storage.py)의 `init_schema()`에서 수행합니다.

## 공통 흐름

1. 플랫폼별 parser/normalizer가 API 응답을 공통 상품 구조로 정규화합니다.
2. `save_product_snapshots_if_enabled()`가 정규화된 상품을 batch로 모읍니다.
3. batch의 기존 `products` row와 최신 `product_history` row를 한 번에 조회합니다.
4. 상품 master 정보는 `products`에 bulk upsert합니다.
5. 가격, 재고, 배송, 상태, MOQ/옵션 등 추세 대상 값이 최초 수집되었거나 실제로 변경된 상품만 `product_history`에 bulk insert합니다.
6. `save_product_raw_samples_if_enabled()`는 제한된 raw sample만 `product_raw_samples`에 저장합니다.
7. `save_search_ranks_if_enabled()`는 순위 의미가 있는 discovery 결과만 `product_search_ranks`에 저장합니다.
8. `save_discovered_product_ids_if_enabled()`는 상세 수집 대상 상품 ID를 `product_discovery_targets`에 저장합니다.

## 변경 감지

`products`에는 상품명, URL, 이미지, 판매자 정보 같은 master 최신값만 저장합니다. 이 값만 바뀐 경우에는 `product_history` row를 만들지 않습니다.

`product_history`는 최신 history row의 핵심 상태와 현재 정규화 상태를 비교합니다. 가격만 바뀌어도 해당 시점의 가격, 재고, 배송 전체 상태를 함께 저장합니다. 값이 모두 동일하면 새 history row를 저장하지 않습니다.

변경 비교는 숫자 문자열과 숫자를 같은 값으로 보도록 canonicalize하지만, 배송비 조건식 원문 등 저장 payload는 그대로 보존합니다.

## 삭제된 snapshot 테이블

`product_prices`, `product_inventory`, `product_shipping_fees`는 더 이상 생성하거나 유지하지 않습니다. `init_schema()`는 기존 DB에 이 테이블이 있으면 drop합니다. 기존 snapshot 데이터에서 새 `product_history`의 전체 핵심 상태를 안전하게 복원할 수 없으므로 임의 마이그레이션은 수행하지 않습니다.

가격, 재고, 배송 이력의 신규 저장 위치는 `product_history.prices`, `product_history.inventory`, `product_history.shipping` JSONB입니다.

## 변화율 probe 결과

2026-09-06에 오너클랜 최하위 카테고리 처음 100개, 카테고리별 상위 최대 100개를 저장 없이 비교했습니다. 약 3일 전 legacy snapshot 대비 기존 상품 3,992개 중 핵심 값이 바뀐 상품은 31개로, 기존 상품 기준 변경률은 0.78%였습니다. 신규 상품 714개까지 포함하면 history 저장 예상은 745개/4,706개, 15.83%입니다.

## Batch 처리

기본 상품 저장 batch size는 `1000`입니다. `.env`의 `POSTGRES_PRODUCT_BATCH_SIZE`로 조정할 수 있습니다. 각 batch는 별도 트랜잭션으로 처리하고, 실패 시 해당 batch를 한 번 재시도합니다. 재시도 후에도 실패하면 해당 batch만 rollback하고 다음 batch 처리를 계속합니다.

현재는 staging 테이블을 적용하지 않습니다. API 수집 결과를 메모리 batch로 처리해도 DB 왕복과 transaction 크기를 제한할 수 있기 때문입니다. batch 크기로도 메모리 압박, 네트워크 재시도 비용, 동일 상품 중복 유입, 수집 중단 후 재개 비용이 커지면 임시 staging 테이블 또는 임시 파일 기반 적재를 추가합니다.

# 데이터 저장 흐름

현재 운영 저장소는 PostgreSQL입니다. 스키마 생성과 보강은 [postgres_storage.py](../../postgres_storage.py)의 `init_schema()`에서 수행하고, 컬럼 단위 명세는 [DB_FIELD_SPEC.md](DB_FIELD_SPEC.md)를 기준으로 관리합니다.

## 공통 흐름

1. 플랫폼별 parser/normalizer가 API 응답을 공통 상품 구조로 정규화합니다.
2. `save_product_snapshots_if_enabled()`가 상품 master, 가격, 재고, 배송비, 최신 비교 필드, 변경 이력을 저장합니다.
3. `save_product_raw_samples_if_enabled()`가 제한된 raw 샘플만 `product_raw_samples`에 저장합니다.
4. `save_search_ranks_if_enabled()`가 순위 의미가 있는 discovery 결과만 `product_search_ranks`에 저장합니다.
5. `save_discovered_product_ids_if_enabled()`가 상세 수집 대상 상품 ID를 `product_discovery_targets`에 저장합니다.

## 변경 감지

최신 API 응답 전체 JSON을 `products`에 저장하지 않습니다. 변경 감지는 `products`의 scalar 컬럼과 최신 가격/재고/배송 snapshot row를 DB에서 읽어 처리합니다.

수집 시 현재 정규화 값과 기존 DB 최신값을 비교합니다. 값이 바뀌면 `product_change_history`에 `changed_fields`만 남깁니다.

가격, 재고, 배송비 snapshot은 변경 여부와 무관하게 각 snapshot 테이블에 수집 시점별로 저장합니다. `product_change_history`는 “주요 필드가 바뀐 시점”을 빠르게 찾기 위한 보조 이력입니다.

## Raw 샘플

API 원본 전체 보관은 하지 않습니다. 디버깅용으로 각 실행에서 제한된 개수만 `product_raw_samples`에 저장합니다.

## 재개 상태

수집기는 PostgreSQL 저장이 성공한 뒤 checkpoint를 갱신합니다. 정상 완료된 재개 상태 파일은 삭제되고, 남아 있는 상태 파일은 다음 실행에서 저장 완료 지점 이후부터 재개하는 데 사용됩니다.

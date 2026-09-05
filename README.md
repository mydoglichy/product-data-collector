# Product Data Collector

쿠팡 파트너스, 오너클랜 Seller GraphQL API, 도매꾹/도매매 Open API의 상품 데이터를 수집해 PostgreSQL에 저장하는 프로젝트입니다.

## 프로젝트 구성

- `ownerclan_API/`: 오너클랜 상품 discovery, 카테고리 수집, 상세 수집, 증분 수집
- `domeggook_API/`: 도매꾹/도매매 상품 discovery와 상세 수집
- `coupang_API/`: 쿠팡 파트너스 키워드 검색 상품 수집
- `postgres_storage.py`: 공통 PostgreSQL 스키마 생성, 보강, 저장 로직
- `product_history.py`: 변경 감지 대상 필드 정규화 로직
- `shipping_fees.py`: 배송비 정규화 로직
- `docs/schema/`: PostgreSQL 저장 흐름과 필드 명세
- `docs/operations/`: 운영 절차, 수집 방식, API 제한 관측 문서
- `tests/`: 단위 테스트와 API 제한 probe

## 빠른 시작

```powershell
pip install -r requirements.txt
docker compose up -d postgres
python scripts\test_postgres_connection.py
```

`.env`에는 PostgreSQL과 API 인증값을 설정합니다.

```dotenv
POSTGRES_ENABLED=true
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=product_data_collector
POSTGRES_USER=collector
POSTGRES_PASSWORD=replace_with_local_password
POSTGRES_PRODUCT_BATCH_SIZE=1000
```

## 실행

```powershell
python scripts\run_daily_collector.py --platform ownerclan
python scripts\run_daily_collector.py --platform domeggook
python scripts\run_daily_collector.py --platform coupang
```

개별 실행:

```powershell
python -m ownerclan_API
python -m ownerclan_API --refresh-categories
python -m ownerclan_API --category-workers 8
python -m domeggook_API
python -m domeggook_API --mode daily
python -m coupang_API
```

dry-run 예시:

```powershell
python -m ownerclan_API --refresh-categories --limit 1 --dry-run
python -m domeggook_API --limit 1 --dry-run
python -m coupang_API --dry-run
```

## 저장 구조

`products`에는 상품 master와 식별 정보의 최신값만 저장합니다.

- `id`
- `platform`
- `external_product_id`
- `product_name`
- `product_url`
- `image_url`
- `backup_image_url`
- `status`
- `seller_external_id`
- `seller_nickname`
- `seller_type`
- `seller_grade`
- `seller_excellent_seller`
- `seller_average_satisfaction`
- `seller_review_count`
- `first_seen_at`
- `last_collected_at`

`product_history`에는 가격, 재고, 배송, 상태, MOQ/옵션 등 추세 분석 대상 값이 최초 수집되었거나 실제 변경된 경우에만 row를 저장합니다.

- `id`
- `product_id`
- `observed_at`
- `change_type`: `initial`, `update`
- `changed_fields`
- `prices JSONB`
- `inventory JSONB`
- `shipping JSONB`
- `status`

가격만 바뀌어도 해당 시점의 가격, 재고, 배송 전체 핵심 상태를 함께 저장합니다. 상품명, URL, 이미지, 판매자 닉네임, 판매자 등급, 리뷰 수 같은 master/부가 정보만 바뀐 경우에는 history를 만들지 않습니다.

삭제된 snapshot 테이블:

- 가격 snapshot 테이블
- 재고 snapshot 테이블
- 배송비 snapshot 테이블

이 테이블들은 더 이상 생성하거나 유지하지 않습니다. 기존 snapshot 데이터에서 새 `product_history` 구조의 전체 핵심 상태를 안전하게 복원할 수 없으므로 임의 마이그레이션은 하지 않습니다.

유지 테이블:

- `product_raw_samples`
- `product_search_ranks`
- `product_discovery_targets`

## Batch 저장

상품 저장은 batch 단위로 처리합니다.

1. API 응답을 플랫폼별 규칙으로 정규화합니다.
2. 정규화 상품을 batch로 모읍니다.
3. batch 상품의 기존 `products` row와 최신 `product_history` row를 일괄 조회합니다.
4. 애플리케이션에서 핵심 상태 변경 여부를 비교합니다.
5. `products`를 bulk upsert합니다.
6. 변경된 상품만 `product_history`에 bulk insert합니다.

기본 batch size는 `1000`이며 `.env`의 `POSTGRES_PRODUCT_BATCH_SIZE`로 조정합니다. 각 batch는 별도 transaction으로 처리하고, 실패한 batch는 한 번 재시도합니다. 재시도 후에도 실패하면 해당 batch만 rollback하고 다음 batch를 계속 처리합니다.

현재는 staging 테이블을 적용하지 않습니다. 메모리 batch만으로 DB 왕복과 transaction 크기를 제한할 수 있기 때문입니다. 메모리 압박, 재처리 비용, 동일 상품 중복 유입, 수집 중단 후 정밀 재개 요구가 커지면 임시 staging 테이블 또는 임시 파일 기반 적재를 추가합니다.

## 조회 기준

`product_history(product_id, observed_at)` 인덱스로 특정 상품의 가격/재고 추세와 최신 핵심 상태를 조회합니다. `changed_fields`에는 GIN 인덱스를 두어 가격 변경, 재고 변경, 배송 변경 같은 필터링을 지원합니다.

## 플랫폼별 매핑

상세 매핑은 각 문서를 봅니다.

- [오너클랜 데이터 매핑](ownerclan_API/DATA_SCHEMA.md)
- [도매꾹/도매매 데이터 매핑](domeggook_API/DATA_SCHEMA.md)
- [쿠팡 데이터 매핑](coupang_API/DATA_SCHEMA.md)
- [DB 필드 명세](docs/schema/DB_FIELD_SPEC.md)
- [데이터 저장 흐름](docs/schema/DATA_STORAGE_SCHEMA.md)

## 오너클랜 변화율 probe

2026-09-06에 오너클랜 최하위 카테고리 처음 100개, 카테고리별 상위 최대 100개를 저장 없이 비교했습니다.

- 기존 DB 기준 시점: 2026-09-03 04:34 KST 전후
- probe 시점: 2026-09-06 01:55 KST 전후
- 경과: 약 3일
- 처리 카테고리: 100개
- 빈 카테고리: 26개
- 가져온 unique 상품: 4,706개
- 기존 DB에 있던 상품: 3,992개
- 신규 상품: 714개
- 기존 상품 중 가격, 재고, 배송 등 핵심 값이 바뀐 상품: 31개
- 기존 상품 기준 변경률: 0.78%
- 신규 상품까지 포함한 history 저장 예상: 745개, 15.83%

probe는 DB에 저장하지 않고 읽기/비교만 수행했습니다. probe용 임시 스크립트와 결과 파일은 삭제했습니다.

## 테스트

```powershell
pytest -q
python -m compileall postgres_storage.py product_history.py
```

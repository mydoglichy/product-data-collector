# Product Data Collector

쿠팡 파트너스, 오너클랜 Seller API, 도매꾹/도매매 Open API 상품 데이터를 수집해 PostgreSQL에 저장하는 프로젝트입니다.

## 폴더 구조

세 마켓 패키지는 같은 기준으로 나눕니다.

- `api/`: API 인증, HTTP client, rate limit, query 정의
- `workflows/`: 실행 진입점과 수집 플로우
- `services/`: 파싱, 정규화, 카테고리 등 도메인 처리
- `persistence/`: 파일 상태 저장, checkpoint, lock
- `config/`: 설정 로더와 `config.yaml`, `keywords.txt`
- `tests/`: 마켓별 테스트

공통 저장 로직은 루트의 `postgres_storage.py`, `product_history.py`, `shipping_fees.py`에 둡니다.

## 저장 원칙

운영 수집 결과의 기준 저장소는 PostgreSQL입니다. `POSTGRES_ENABLED=true`로 저장하며, 스키마 생성과 보강은 `postgres_storage.py`의 `init_schema()`가 담당합니다.

주요 테이블:

- `products`: 플랫폼별 상품 master와 최신 정규화 payload
- `product_prices`: 수집 시점별 가격 snapshot
- `product_inventory`: 수집 시점별 재고 snapshot
- `product_shipping_fees`: 수집 시점별 배송비 원본/조건 snapshot
- `product_change_history`: 정규화 payload fingerprint 변경 이력
- `product_raw_samples`: 디버깅용 raw 샘플
- `product_search_ranks`: 순위 의미가 있는 discovery/search 이력

자세한 컬럼 의미는 `docs/schema/DB_FIELD_SPEC.md`, 저장 흐름은 `docs/schema/DATA_STORAGE_SCHEMA.md`를 기준으로 확인합니다.

## 실행

```powershell
python -m coupang_API
python -m ownerclan_API
python -m ownerclan_API --refresh-categories
python -m domeggook_API
```

소량 검증:

```powershell
python -m ownerclan_API --refresh-categories --limit 1 --dry-run
python -m domeggook_API --limit 1 --dry-run
```

개별 workflow 실행:

```powershell
python -m ownerclan_API.workflows.sync_incremental
python -m ownerclan_API.workflows.collect_by_categories --refresh-categories
python -m domeggook_API.workflows.discover_products
python -m domeggook_API.workflows.collect_product_details
```

## 테스트

```powershell
pytest
```

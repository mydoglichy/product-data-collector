# Product Data Collector

쿠팡 파트너스, 오너클랜 Seller GraphQL API, 도매꾹/도매매 Open API 상품 데이터를 수집해 PostgreSQL에 저장하는 프로젝트입니다.

## 구조

세 플랫폼 패키지는 같은 기준으로 나뉩니다.

- `api/`: 인증, HTTP/GraphQL client, rate limiter, query 정의
- `workflows/`: 실행 진입점과 수집 흐름
- `services/`: 파싱, 정규화, 카테고리, 시간, 로깅 처리
- `persistence/`: 재개용 상태 파일, checkpoint, lock
- `config/`: 설정 로더와 `config.yaml`, `keywords.txt`
- `tests/`: 플랫폼별 테스트

공통 PostgreSQL 저장 로직은 루트의 `postgres_storage.py`, 변경 감지 로직은 `product_history.py`, 배송비 정규화는 `shipping_fees.py`에 둡니다.

## 저장 기준

운영 수집 결과의 기준 저장소는 PostgreSQL입니다. `POSTGRES_ENABLED=true`일 때 저장하며, 스키마 생성과 보강은 `postgres_storage.py`의 `init_schema()`가 담당합니다.

주요 테이블은 아래와 같습니다.

- `products`: 플랫폼별 상품 master와 최신 정규화 payload
- `product_prices`: 수집 시점별 가격 snapshot
- `product_inventory`: 수집 시점별 재고 snapshot
- `product_shipping_fees`: 수집 시점별 배송비 원본/조건 snapshot
- `product_change_history`: 비교 대상 payload fingerprint 변경 이력
- `product_raw_samples`: 디버깅용 raw 샘플
- `product_search_ranks`: 순위 의미가 있는 도매꾹/도매매 discovery 이력
- `product_discovery_targets`: 상세 수집 대상으로 재사용할 상품 ID 목록

중복 설명을 피하기 위해 컬럼 명세는 [DB_FIELD_SPEC.md](docs/schema/DB_FIELD_SPEC.md), 저장 흐름은 [DATA_STORAGE_SCHEMA.md](docs/schema/DATA_STORAGE_SCHEMA.md)를 기준 문서로 둡니다. 플랫폼별 `DATA_SCHEMA.md`는 해당 플랫폼의 원본 필드 매핑만 설명합니다.

## 실행

일일 운영은 플랫폼별로 분리 실행합니다.

```powershell
python scripts\run_daily_collector.py --platform ownerclan
python scripts\run_daily_collector.py --platform domeggook
python scripts\run_daily_collector.py --platform coupang
```

직접 실행도 가능합니다.

```powershell
python -m ownerclan_API
python -m ownerclan_API --refresh-categories
python -m domeggook_API
python -m domeggook_API --mode daily
python -m coupang_API
```

소량 검증:

```powershell
python -m ownerclan_API --refresh-categories --limit 1 --dry-run
python -m domeggook_API --limit 1 --dry-run
```

개별 workflow:

```powershell
python -m ownerclan_API.workflows.collect_by_categories --refresh-categories
python -m ownerclan_API.workflows.sync_incremental
python -m domeggook_API.workflows.discover_products
python -m domeggook_API.workflows.collect_product_details
```

운영 상세는 [DAILY_COLLECTION_OPERATIONS.md](docs/operations/DAILY_COLLECTION_OPERATIONS.md)를 봅니다. 플랫폼별 순회 방식, RPM/worker, 중단/재개 구현은 [COLLECTION_METHODS.md](docs/operations/COLLECTION_METHODS.md)에 정리했습니다.

## 테스트

```powershell
pytest
```

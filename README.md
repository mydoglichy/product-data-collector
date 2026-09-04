# Product Data Collector

쿠팡 파트너스, 오너클랜 Seller GraphQL API, 도매꾹/도매매 Open API의 상품 데이터를 수집해 PostgreSQL에 저장하는 프로젝트입니다.

현재 활성 수집기는 아래 3개입니다.

- `ownerclan_API/`: 오너클랜 상품 discovery, 카테고리 수집, 상세 수집, 증분 수집
- `domeggook_API/`: 도매꾹/도매매 상품 discovery와 상세 수집
- `coupang_API/`: 쿠팡 파트너스 키워드 검색 상품 수집

`naver-API/`, `dataLab_API/` 수집기는 현재 프로젝트에 포함되어 있지 않습니다.

## 프로젝트 구조

```text
.
├── coupang_API/
├── domeggook_API/
├── ownerclan_API/
├── docs/
│   ├── operations/
│   └── schema/
├── scripts/
├── tests/
├── docker-compose.yml
├── postgres_storage.py
├── product_history.py
└── shipping_fees.py
```

각 플랫폼 폴더는 대체로 같은 구성을 따릅니다.

- `api/`: 인증, HTTP/GraphQL client, rate limiter
- `workflows/`: 실행 진입점과 수집 흐름
- `services/`: 파싱, 정규화, 카테고리, 시간, 로깅 처리
- `persistence/`: 저장 adapter, checkpoint, 재개 상태 관리
- `config/`: `config.yaml`, `keywords.txt`, 설정 로더
- `tests/`: 플랫폼별 테스트

공통 PostgreSQL 저장 로직은 [postgres_storage.py](postgres_storage.py), 변경 감지 로직은 [product_history.py](product_history.py), 배송비 정규화는 [shipping_fees.py](shipping_fees.py)에 있습니다.

## DB 연결

운영 저장소는 PostgreSQL입니다. `.env`에 아래 값이 필요하며, `.env.example`을 복사해 채우면 됩니다.

```dotenv
POSTGRES_ENABLED=true
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=product_data_collector
POSTGRES_USER=collector
POSTGRES_PASSWORD=replace_with_local_password
```

로컬 PostgreSQL은 Docker Compose로 실행할 수 있습니다.

```powershell
docker compose up -d postgres
python scripts\test_postgres_connection.py
```

연결이 정상이고 스키마 초기화가 끝나면 아래와 같은 메시지가 출력됩니다.

```text
PostgreSQL connection ok: database=product_data_collector
```

스키마 생성과 기존 DB 보강은 `postgres_storage.py`의 `init_schema()`가 담당합니다. 주요 테이블은 다음과 같습니다.

- `products`: 플랫폼별 상품 master와 최신 정규화 payload
- `product_prices`: 수집 시점별 가격 snapshot
- `product_inventory`: 수집 시점별 재고 snapshot
- `product_shipping_fees`: 수집 시점별 배송비 snapshot
- `product_change_history`: 비교 대상 payload fingerprint 변경 이력
- `product_raw_samples`: 디버깅용 raw sample
- `product_search_ranks`: 순위 의미가 있는 검색/discovery 이력
- `product_discovery_targets`: 상세 수집 대상으로 재사용할 상품 ID 목록

컬럼 명세는 [DB_FIELD_SPEC.md](docs/schema/DB_FIELD_SPEC.md), 저장 흐름은 [DATA_STORAGE_SCHEMA.md](docs/schema/DATA_STORAGE_SCHEMA.md)를 기준으로 관리합니다. 플랫폼별 `DATA_SCHEMA.md`는 해당 플랫폼의 원본 필드 매핑만 설명합니다.

## 실행

의존성 설치:

```powershell
pip install -r requirements.txt
```

플랫폼별 일일 수집:

```powershell
python scripts\run_daily_collector.py --platform ownerclan
python scripts\run_daily_collector.py --platform domeggook
python scripts\run_daily_collector.py --platform coupang
```

Docker Compose로 DB와 수집기를 함께 실행:

```powershell
docker compose up data-collector
```

플랫폼 모듈 직접 실행:

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

운영 상세는 [DAILY_COLLECTION_OPERATIONS.md](docs/operations/DAILY_COLLECTION_OPERATIONS.md)를 기준으로 봅니다. 플랫폼별 조회 방식, RPM/worker, 중단/재개 구현은 [COLLECTION_METHODS.md](docs/operations/COLLECTION_METHODS.md)에 정리되어 있습니다.

## 테스트

```powershell
pytest
```

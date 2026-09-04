# Product Data Collector

쿠팡 파트너스, 오너클랜 Seller GraphQL API, 도매꾹/도매매 Open API의 상품 데이터를 수집해 PostgreSQL에 저장하는 프로젝트입니다.

## 구성

- `ownerclan_API/`: 오너클랜 상품 discovery, 카테고리 수집, 상세 수집, 증분 수집
- `domeggook_API/`: 도매꾹/도매매 상품 discovery와 상세 수집
- `coupang_API/`: 쿠팡 파트너스 키워드 검색 상품 수집
- `postgres_storage.py`: 공통 PostgreSQL 저장 로직
- `product_history.py`: 변경 감지 대상 필드 정규화 로직
- `shipping_fees.py`: 배송비 정규화

## DB 연결

`.env`에 PostgreSQL과 API 인증값을 설정합니다.

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

## 주요 테이블

- `products`: 플랫폼별 상품 master와 최신 조회용 scalar 값
- `product_prices`: 수집 시점별 가격 snapshot
- `product_inventory`: 수집 시점별 재고 snapshot
- `product_shipping_fees`: 수집 시점별 배송비 snapshot
- `product_change_history`: `products` scalar 값과 최신 snapshot row 비교 결과
- `product_raw_samples`: 디버깅용 제한 raw sample
- `product_search_ranks`: 순위 의미가 있는 검색/discovery 이력
- `product_discovery_targets`: 상세 수집 대상으로 사용할 상품 ID 목록

최신 API 응답 전체 JSON이나 비교용 JSON은 `products`에 저장하지 않습니다. 변경 감지는 `products`의 scalar 컬럼과 최신 가격/재고/배송 snapshot row를 기준으로 처리합니다.

컬럼 명세는 [DB_FIELD_SPEC.md](docs/schema/DB_FIELD_SPEC.md), 저장 흐름은 [DATA_STORAGE_SCHEMA.md](docs/schema/DATA_STORAGE_SCHEMA.md)를 기준으로 관리합니다.

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

개별 모듈 실행:

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

## 테스트

```powershell
pytest
```

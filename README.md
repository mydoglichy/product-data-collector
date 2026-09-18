# Product Data Collector

쿠팡 파트너스, 오너클랜 Seller GraphQL API, 도매꾹/도매매 Open API의 상품 데이터를 수집해 PostgreSQL에 저장하는 프로젝트입니다.

## 구성

- `ownerclan_API/`: 오너클랜 상품 discovery, 카테고리 수집, 상세 수집, 증분 수집
- `domeggook_API/`: 도매꾹/도매매 상품 discovery와 상세 수집
- `coupang_API/`: 쿠팡 파트너스 키워드 검색 상품 수집
- `product_data_collector/persistence/postgres_storage.py`: 공통 PostgreSQL 스키마 생성, 보강, 저장 로직
- `product_data_collector/domain/product_history.py`: 변경 감지 대상 필드 정규화 로직
- `product_data_collector/domain/shipping_fees.py`: 배송비 정규화 로직
- `docs/schema/`: PostgreSQL 스키마와 저장 규칙
- `docs/operations/`: 운영 절차와 재개 기준
- `docs/experiments/`: API 제한, 변화율, 신규 API 검증 결과
- `tests/`: 단위 테스트와 API probe 스크립트

## 빠른 시작

```powershell
pip install -r requirements.txt
docker compose up -d postgres
python scripts\test_postgres_connection.py
```

`.env`에는 PostgreSQL과 API 인증값을 설정합니다. 아래 값은 로컬 기본 예시입니다.

```dotenv
POSTGRES_ENABLED=true
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=product_data_collector
POSTGRES_USER=collector
POSTGRES_PASSWORD=replace_with_local_password
POSTGRES_PRODUCT_BATCH_SIZE=1000
```

## 일일 실행

```powershell
python scripts\run_daily_collector.py --platform ownerclan
python scripts\run_daily_collector.py --platform domeggook
python scripts\run_daily_collector.py --platform coupang
```

개별 수집기 실행:

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

## 저장 방식

운영 저장소는 PostgreSQL입니다. 상품 식별과 master 최신값은 `products`에 저장하고, 가격/재고/배송/상태 같은 추세 대상 값이 최초 수집되었거나 실제 변경된 경우에만 `product_history`를 남깁니다.

원본 API 전체 응답을 장기 보관하지 않습니다. 디버깅용 sample은 `product_raw_samples`에 플랫폼별 최대 100개만 보관하고, discovery/search 순위와 상세 수집 대상 ID는 별도 테이블에 정규화해서 저장합니다.

## 문서

- [운영 런북](docs/operations/RUNBOOK.md): 일일 실행, 백필, 상태 파일, 제한 대응
- [DB 스키마](docs/schema/DB_SCHEMA.md): 테이블 명세, 저장 흐름, 변경 감지 기준
- [API 실험 결과](docs/experiments/API_PROBE_RESULTS.md): rate limit, 변화율, `itemHistories` 검증 결과
- [오너클랜 수집기](ownerclan_API/README.md): Seller GraphQL API 특징과 필드 매핑
- [도매꾹/도매매 수집기](domeggook_API/README.md): Open API 특징과 필드 매핑
- [쿠팡 수집기](coupang_API/README.md): Partners API 특징과 필드 매핑

## 테스트

```powershell
pytest -q
python -m compileall product_data_collector
```

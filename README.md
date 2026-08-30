# Product Data Collector

쿠팡 파트너스, 오너클랜 Seller API, 도매꾹/도매매 Open API 상품 데이터를 수집해 PostgreSQL에 저장하는 프로젝트입니다.

## 저장 원칙

운영 수집 결과의 기준 저장소는 PostgreSQL입니다. `POSTGRES_ENABLED=true`일 때 저장하며, 스키마 생성과 보강은 [postgres_storage.py](postgres_storage.py)의 `init_schema()`가 담당합니다.

수집기와 DB 저장 단계에서는 배송비를 판매수량 기준으로 계산하지 않습니다. API에서 받은 배송비 원본값, 배송비 타입, 부담 방식, 지역 추가배송비, 파싱 가능한 조건 구조만 저장하고, 개당 배송비/MOQ 배분/마진 계산은 플랫폼 서버에서 처리합니다.

## PostgreSQL 테이블

| 테이블 | 용도 |
| --- | --- |
| `products` | 플랫폼별 상품 master와 최신 정규화 payload |
| `product_prices` | 수집 시점별 가격 snapshot |
| `product_inventory` | 수집 시점별 재고 snapshot |
| `product_shipping_fees` | 수집 시점별 배송비 원본/조건 snapshot |
| `product_change_history` | 비교 대상 payload fingerprint 변경 이력 |
| `product_raw_samples` | 디버깅용 raw 샘플 |
| `product_search_ranks` | 순위 의미가 있는 discovery/search 이력 |

배송비 row는 도매꾹 `market='dome'`, 도매매 `market='supply'`, 오너클랜 `market='ownerclan'`으로 구분합니다. `product_shipping_fees.fee`는 API/정규화 payload에서 단일 숫자로 확인되는 기본 배송비 원본값이며, 수량별비례/수량별차등 조건식은 계산하지 않고 `NULL`과 `payload.shipping_rules`로 저장합니다.

자세한 컬럼 의미는 [DB_FIELD_SPEC.md](DB_FIELD_SPEC.md), 저장 흐름은 [DATA_STORAGE_SCHEMA.md](DATA_STORAGE_SCHEMA.md)를 기준으로 확인합니다.

## 실행

```powershell
python -m coupang_API
python -m ownerclan_API.main
python -m ownerclan_API.main --refresh-categories
python -m ownerclan_API.sync_incremental
python -m domeggook_API.main
```

소량 검증:

```powershell
python -m ownerclan_API.main --refresh-categories --limit 1 --dry-run
python -m domeggook_API.main --limit 1 --dry-run
```

## 테스트

```powershell
pytest
```

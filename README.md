# Product Data Collector

쿠팡 파트너스, 오너클랜 Seller API, 도매꾹/도매매 Open API 상품 데이터를 수집해 PostgreSQL에 저장하는 프로젝트입니다.

## 저장 원칙

운영 수집 결과의 기준 저장소는 PostgreSQL입니다. 예전처럼 `processed`, `raw`, `history`, `summaries` 아래에 상품 결과 JSON/JSONL 파일을 만들지 않습니다.

DB 저장은 `.env`의 `POSTGRES_ENABLED=true`일 때 실행됩니다. 이 값이 꺼져 있으면 수집 결과 파일도 대체로 생성하지 않으므로 운영 실행 전 반드시 PostgreSQL 설정을 켜야 합니다.

```env
POSTGRES_ENABLED=true
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=...
POSTGRES_USER=...
POSTGRES_PASSWORD=...
```

## PostgreSQL 테이블

스키마 생성과 마이그레이션은 [postgres_storage.py](postgres_storage.py)의 `init_schema()`가 담당합니다. 전체 컬럼 명세는 [DB_FIELD_SPEC.md](DB_FIELD_SPEC.md)에 정리되어 있습니다.

| 테이블 | 용도 |
| --- | --- |
| `products` | 플랫폼별 상품 master 및 최신 정규화 payload |
| `product_prices` | 수집 시점별 가격 snapshot |
| `product_inventory` | 수집 시점별 재고 snapshot |
| `product_shipping_fees` | 수집 시점별 배송비 snapshot |
| `product_change_history` | 비교 대상 payload fingerprint 변경 이력 |
| `product_raw_samples` | 디버깅용 raw 샘플, 저장 호출당 최대 3개 상품 |
| `product_search_ranks` | 순위 의미가 있는 플랫폼의 discovery/search 순위 이력 |

도매꾹/도매매는 가격과 배송비를 `market='dome'`, `market='supply'` row로 분리합니다. 재고는 API가 `qty.inventory` 단일 재고만 제공하므로 현재는 상품 단위 단일 row로 저장합니다.

배송비 금액과 부담 방식은 분리합니다. `product_shipping_fees.fee`는 계산 가능한 기본 배송비이고, `payload.shipping_payment`는 `free`, `prepaid`, `collect`, `buyer_choice`, `unknown` 중 하나로 정규화된 부담 방식입니다.

## 파일로 남는 항목

아래 파일은 수집 결과 저장소가 아니라 실행 입력, 캐시, 재시작 상태라 유지합니다.

- `*_API/config.yaml`
- `*_API/keywords.txt`
- `domeggook_API/data/state/categories.json`
- `domeggook_API/data/state/tracked_products.json`
- `ownerclan_API/data/state/categories.json`
- `ownerclan_API/data/state/tracked_products.json`
- `ownerclan_API/data/state/incremental-state.json`
- `coupang_API/data/state/product_search_checkpoint.json`

오너클랜은 인기순, 판매량순, 랭킹 순위 API를 기준으로 저장하지 않습니다. 기본 수집은 오너클랜 카테고리 트리를 캐시한 뒤 최하위 카테고리별 `allItems(category: ...)` 페이지를 순회해 상품을 PostgreSQL에 저장합니다.

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

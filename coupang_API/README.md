# 쿠팡 수집기

쿠팡 파트너스 상품 검색 API 결과를 수집해 PostgreSQL에 저장합니다.

## 실행 흐름

```powershell
python -m coupang_API
python -m coupang_API --dry-run
python scripts\run_daily_collector.py --platform coupang
python scripts\run_daily_collector.py --platform coupang --dry-run
```

`config/keywords.txt`의 keyword를 순서대로 조회하고, keyword별 성공 여부를 checkpoint에 기록합니다.
`--dry-run`은 실제 API 호출과 파싱까지 수행하지만 checkpoint, raw sample, 상품 master/history를 저장하지 않습니다.

상세한 순회 방식은 [운영 런북](../docs/operations/RUNBOOK.md#쿠팡)을 봅니다. 요약하면 단일 worker가 keyword 1개당 Search API를 1회 호출하고, 성공 keyword를 `product_search_checkpoint.json`에 기록합니다. 현재 설정은 rolling window 기준 40 RPM이며, HTTP 200이어도 JSON `rCode` 제한을 검사합니다.

## 설정과 제한

`config/config.yaml`의 현재 기준:

- requests per minute: `40`
- keyword당 검색 limit: `10`
- image size: `512x512`
- raw sample limit: 플랫폼별 최대 `100`개

쿠팡 파트너스는 HTTP 200이어도 JSON `rCode`로 제한을 반환할 수 있으므로 client가 응답 본문을 함께 검사합니다. 로컬 관측 내용은 [API 실험 결과](../docs/experiments/API_PROBE_RESULTS.md#쿠팡-파트너스-호출-제한)에 따로 둡니다.

## 상태 파일

- `data/state/product_search_checkpoint.json`: 완료 keyword checkpoint

모든 keyword가 성공하면 checkpoint 파일은 삭제됩니다. 상품 데이터는 JSON 파일로 만들지 않고 PostgreSQL에 저장합니다.

## 데이터 매핑

쿠팡 파트너스 상품 검색 API 응답은 `coupang_API.services.models.parse_product_records()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다. 공통 테이블/저장 규칙은 [DB 스키마](../docs/schema/DB_SCHEMA.md)가 기준입니다.

### 상품 master

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `coupang` |
| `products.external_product_id` | `productId` |
| `products.product_name` | `productName` |
| `products.product_url` | `productUrl` |
| `products.image_url` | `productImage` |

### 핵심 history

가격, 배송, 판매 상태가 최초 수집되었거나 실제 변경된 경우에만 `product_history` row를 저장합니다.

| product_history JSON | source |
| --- | --- |
| `prices.rows[].market` | `coupang` |
| `prices.rows[].price_type` | `primary` |
| `prices.rows[].amount` | `productPrice` |
| `inventory.stockQuantity` | 검색 API에 재고가 없으므로 일반적으로 `null` |
| `shipping.rows[].market` | `coupang` |
| `shipping.rows[].isFreeShipping` | `isFreeShipping` 값이 있을 때 저장 |

예전 `data/raw/coupang_*_raw_{keyword}.json` 파일은 더 이상 생성하지 않습니다. raw sample은 `product_raw_samples`에 저장하며, 플랫폼별 최대 100개 상품까지만 보존합니다.

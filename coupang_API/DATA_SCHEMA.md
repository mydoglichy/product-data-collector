# 쿠팡 데이터 매핑

쿠팡 파트너스 상품 검색 API 응답은 `coupang_API.services.models.parse_product_records()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다. 공통 테이블 컬럼과 unique key는 [DB_FIELD_SPEC.md](../docs/schema/DB_FIELD_SPEC.md)를 기준으로 봅니다.

## 상품 master

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `coupang` |
| `products.external_product_id` | `productId` |
| `products.product_name` | `productName` |
| `products.product_url` | `productUrl` |
| `products.image_url` | `productImage` |

## 핵심 history

가격, 배송, 판매 상태가 최초 수집되었거나 실제 변경된 경우에만 `product_history` row를 저장합니다.

| product_history JSON | source |
| --- | --- |
| `prices.rows[].market` | `coupang` |
| `prices.rows[].price_type` | `primary` |
| `prices.rows[].amount` | `productPrice` |
| `inventory.stockQuantity` | 검색 API에 재고가 없으므로 일반적으로 `null` |
| `shipping.rows[].market` | `coupang` |
| `shipping.rows[].isFreeShipping` | `isFreeShipping` 값이 있을 때 저장 |

## raw sample과 상태

예전 `data/raw/coupang_*_raw_{keyword}.json` 파일은 더 이상 생성하지 않습니다. raw sample은 `product_raw_samples`에 저장하며, 저장 호출당 최대 3개 상품까지만 보존합니다.

`data/state/product_search_checkpoint.json`만 재시작 상태로 유지합니다. 모든 keyword가 성공하면 checkpoint 파일은 삭제됩니다.

# 쿠팡 데이터 매핑

쿠팡 파트너스 상품 검색 API 응답은 `coupang_API.services.models.parse_product_records()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다. 공통 테이블 컬럼과 unique key는 [DB_FIELD_SPEC.md](../docs/schema/DB_FIELD_SPEC.md)를 기준으로 봅니다.

## 상품 기본값

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `coupang` |
| `products.external_product_id` | `productId` |
| `products.product_name` | `productName` |
| `products.product_url` | `productUrl` |
| `products.image_url` | `productImage` |

## 가격, 재고, 배송

| PostgreSQL | source |
| --- | --- |
| `product_prices.market` | `coupang` |
| `product_prices.price_type` | `primary` |
| `product_prices.amount` | `productPrice` |
| `product_inventory.stock_quantity` | 검색 API에 재고가 없으므로 row를 저장하지 않음 |
| `product_shipping_fees.market` | `coupang` |
| `product_shipping_fees.is_free_shipping` | `isFreeShipping` 값이 있을 때 저장 |

## raw 샘플과 상태

예전 `data/raw/coupang_*_raw_{keyword}.json` 파일은 더 이상 생성하지 않습니다. raw 샘플은 `product_raw_samples`에 저장하며, 저장 호출당 최대 3개 상품까지만 보존합니다.

`data/state/product_search_checkpoint.json`만 재시작 상태로 유지합니다. 모든 keyword가 성공하면 checkpoint 파일은 삭제됩니다.

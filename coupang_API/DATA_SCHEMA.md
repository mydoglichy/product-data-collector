# 쿠팡 데이터 스키마

쿠팡 파트너스 검색 결과는 `parse_product_records()`에서 정규화한 뒤 PostgreSQL에 저장한다.

## PostgreSQL 매핑

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `coupang` |
| `products.external_product_id` | `productId` |
| `products.product_name` | `productName` |
| `products.product_url` | `productUrl` |
| `products.image_url` | `productImage` |
| `product_prices.market` | `coupang` |
| `product_prices.price_type` | `primary` |
| `product_prices.amount` | `productPrice` |
| `product_inventory.stock_quantity` | 검색 API에 없음, 보통 `NULL` |
| `product_shipping_fees.market` | `coupang` |
| `product_shipping_fees.is_free_shipping` | `isFreeShipping` |

## raw 샘플

예전 `data/raw/coupang_*_raw_{keyword}.json` 파일은 더 이상 생성하지 않는다.

raw 샘플은 `product_raw_samples`에 저장한다. 저장 호출당 최대 3개 상품까지만 저장하며, 전체 원본 보관용이 아니라 parser 검증과 장애 분석용이다.

## 파일 기반 상태

`data/state/product_search_checkpoint.json`만 재시작 상태로 유지한다. 상품 데이터 저장소가 아니다.

# 도매꾹·도매매 데이터 매핑

도매꾹·도매매 Open API 응답은 `domeggook_API.services.parsing.parse_detail_product()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다. 공통 테이블 컬럼과 unique key는 [DB_FIELD_SPEC.md](../docs/schema/DB_FIELD_SPEC.md)를 기준으로 봅니다.

## 상품 기본값

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `domeggook` |
| `products.external_product_id` | `basis.no`, `no`, `itemNo` |
| `products.product_name` | `basis.title` |
| `products.status` | `basis.status` |
| `products.image_url` | `thumb.original` 또는 첫 번째 이미지 URL |
| `products.backup_image_url` | 두 번째 이미지 URL |

## 판매자

| PostgreSQL | source |
| --- | --- |
| `products.seller_external_id` | `seller.id` |
| `products.seller_nickname` | `seller.nick` |
| `products.seller_type` | `seller.type` |
| `products.seller_grade` | `seller.rank` |
| `products.seller_excellent_seller` | `seller.good` |
| `products.seller_average_satisfaction` | `seller.score.avg` |
| `products.seller_review_count` | `seller.score.cnt` |

## 가격, 재고, 배송

| PostgreSQL | source |
| --- | --- |
| `product_prices.market='dome', price_type='current_supply'` | `price.dome` |
| `product_prices.market='supply', price_type='current_supply'` | `price.supply` |
| `product_prices.market='retail', price_type='minimum_retail'` | `price.labeledPrice.low` 또는 기존 `minimumRetailPrice` alias |
| `product_prices.market='retail', price_type='recommended_retail'` | `price.labeledPrice.recommend` 또는 기존 `recommendedRetailPrice` alias |
| `product_prices.market='resale', price_type='minimum'` | `price.resale.minimum`, 문서 오탈자 alias `price.resale.minumum` |
| `product_prices.market='resale', price_type='recommended'` | `price.resale.Recommand` |
| `product_inventory.stock_quantity` | `qty.inventory` |
| `product_shipping_fees.market='dome'` | `deli.dome.fee`, `deli.dome.tbl`, `deli.dome.type` |
| `product_shipping_fees.market='supply'` | `deli.supply.fee`, `deli.supply.tbl`, `deli.supply.type` |

도매꾹과 도매매 배송비는 `dome`, `supply` row로 분리합니다. 도매매 배송비가 비어 있어도 도매꾹 배송비로 `supply` row를 임의 생성하지 않습니다.

## 변경 감지

최신 API 응답 전체 JSON은 `products`에 저장하지 않습니다. 변경 감지는 `products` scalar 컬럼과 최신 가격/재고/배송 snapshot row를 기준으로 처리하며, 값이 바뀌면 `product_change_history.changed_fields`에 변경된 경로만 남깁니다.

# 도매꾹/도매매 데이터 매핑

도매꾹/도매매 Open API 응답은 `domeggook_API.services.parsing.parse_detail_product()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다. 공통 테이블 컬럼과 unique key는 [DB_FIELD_SPEC.md](../docs/schema/DB_FIELD_SPEC.md)를 기준으로 봅니다.

## 상품 master

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

## 핵심 history

가격, 재고, 배송, 판매 상태가 최초 수집되었거나 실제 변경된 경우에만 `product_history` row를 저장합니다.

| product_history JSON | source |
| --- | --- |
| `prices.rows[].market='dome', price_type='current_supply'` | `price.dome` |
| `prices.rows[].market='supply', price_type='current_supply'` | `price.supply` |
| `prices.rows[].market='retail', price_type='minimum_retail'` | `price.labeledPrice.low` 또는 기존 `minimumRetailPrice` alias |
| `prices.rows[].market='retail', price_type='recommended_retail'` | `price.labeledPrice.recommend` 또는 기존 `recommendedRetailPrice` alias |
| `prices.rows[].market='resale', price_type='minimum'` | `price.resale.minimum`, 문서 오탈자 alias `price.resale.minumum` |
| `prices.rows[].market='resale', price_type='recommended'` | `price.resale.Recommand` |
| `inventory.stockQuantity` | `qty.inventory` |
| `shipping.rows[].market='dome'` | `deli.dome.fee`, `deli.dome.tbl`, `deli.dome.type` |
| `shipping.rows[].market='supply'` | `deli.supply.fee`, `deli.supply.tbl`, `deli.supply.type` |

도매꾹과 도매매 배송비는 `dome`, `supply` row로 분리해 `product_history.shipping.rows`에 저장합니다. 도매매 배송비가 비어 있어도 도매꾹 배송비로 `supply` row를 임의 생성하지 않습니다.

## 변경 감지

상품명, 이미지, URL, 판매자 표시 정보만 바뀐 경우에는 history를 만들지 않습니다. 가격, 재고, 배송비, 배송 조건, 상태, MOQ/주문 단위가 바뀌면 변경 후 전체 핵심 상태를 `product_history`에 저장합니다.

# 오너클랜 데이터 매핑

오너클랜 Seller GraphQL API 응답은 `ownerclan_API.services.normalization.normalize_item()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다. 공통 테이블 컬럼과 unique key는 [DB_FIELD_SPEC.md](../docs/schema/DB_FIELD_SPEC.md)를 기준으로 봅니다.

## 상품 기본값

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `ownerclan` |
| `products.external_product_id` | `productId` 또는 `productKey` |
| `products.product_name` | 정규화된 상품명 |
| `products.product_url` | 정규화된 상품 URL |
| `products.image_url` | `images[0]` 또는 첫 번째 이미지 필드 |
| `products.backup_image_url` | `images[1]` 또는 두 번째 이미지 필드 |
| `products.status` | 정규화된 상태 값 |

## 가격, 재고, 배송

| PostgreSQL | source |
| --- | --- |
| `product_prices.market` | `ownerclan` |
| `product_prices.price_type` | `current_supply`, `fixed` |
| `product_prices.amount` | `prices.currentSupplyPrice`, `prices.fixedPrice` |
| `product_inventory.stock_quantity` | 옵션 수량 합계. 원본 수량은 inventory 보조 payload에 보존 |
| `product_shipping_fees.market` | `ownerclan` |
| `product_shipping_fees.fee` | `shippingFee`가 단일 숫자로 해석되는 경우 |
| `product_shipping_fees.shipping_type` | 계산 가능한 배송비 유형이면 정규화, 아니면 `unknown` |

오너클랜은 `product_search_ranks`에 저장하지 않습니다. 현재 수집 경로의 Seller API 응답은 순위 분석에 쓸 수 있는 랭킹 의미를 제공하지 않습니다.

## 변경 감지

최신 API 응답 전체 JSON은 `products`에 저장하지 않습니다. 변경 감지는 `products` scalar 컬럼과 최신 가격/재고/배송 snapshot row를 기준으로 처리하며, 값이 바뀌면 `product_change_history.changed_fields`에 변경된 경로만 남깁니다.

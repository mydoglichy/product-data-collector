# 오너클랜 데이터 매핑

오너클랜 Seller GraphQL API 응답은 `ownerclan_API.services.normalization.normalize_item()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다. 공통 테이블 컬럼과 unique key는 [DB_FIELD_SPEC.md](../docs/schema/DB_FIELD_SPEC.md)를 기준으로 봅니다.

## 상품 master

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `ownerclan` |
| `products.external_product_id` | `productId` 또는 `productKey` |
| `products.product_name` | 정규화된 상품명 |
| `products.product_url` | 정규화된 상품 URL |
| `products.image_url` | `images[0]` 또는 첫 번째 이미지 필드 |
| `products.backup_image_url` | `images[1]` 또는 두 번째 이미지 필드 |
| `products.status` | 정규화된 판매 상태 |

## 핵심 history

가격, 재고, 배송, 판매 상태가 최초 수집되었거나 실제 변경된 경우에만 `product_history` row를 저장합니다.

| product_history JSON | source |
| --- | --- |
| `prices.rows[].market` | `ownerclan` |
| `prices.rows[].price_type` | `current_supply`, `fixed` |
| `prices.rows[].amount` | `prices.currentSupplyPrice`, `prices.fixedPrice` |
| `inventory.stockQuantity` | 옵션 수량 합계 |
| `inventory.payload` | inventory 보조 값과 원본 수량 |
| `inventory.options` | 옵션별 가격/수량 |
| `shipping.rows[].market` | `ownerclan` |
| `shipping.rows[].fee` | `shippingFee`가 단일 숫자로 해석되는 경우 |
| `shipping.rows[].shippingType` | 계산 가능한 배송비 유형이면 정규화, 아니면 `unknown` |
| `shipping.rows[].payload` | 배송비 조건식 원문과 source fields |

오너클랜은 `product_search_ranks`에 저장하지 않습니다. 현재 수집 경로의 Seller API 응답은 순위 분석에 쓸 수 있는 검색 순위를 제공하지 않습니다.

## 변경 감지

상품명, 이미지, URL 같은 master 값만 바뀐 경우에는 history를 만들지 않습니다. 가격, 재고, 배송비, 배송 조건, 상태, 옵션 수량/가격이 바뀌면 변경 후 전체 핵심 상태를 `product_history`에 저장합니다.

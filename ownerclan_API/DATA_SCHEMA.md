# 오너클랜 데이터 매핑

오너클랜 Seller GraphQL 응답은 `ownerclan_API.services.normalization.normalize_item()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다. 공통 테이블 컬럼과 unique key는 [DB_FIELD_SPEC.md](../docs/schema/DB_FIELD_SPEC.md)를 기준으로 봅니다.

## 상품 기본값

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `ownerclan` |
| `products.external_product_id` | `productId` 또는 `productKey` |
| `products.product_name` | 정규화된 상품명 |
| `products.product_url` | 정규화된 상품 URL |
| `products.image_url` | `images[0]` 또는 이미지 필드의 첫 번째 URL |
| `products.backup_image_url` | `images[1]` 또는 이미지 필드의 두 번째 URL |
| `products.comparable_payload` | 가격, 재고, 배송, 옵션, 상태 등 변경 감지 대상 필드 |

## 가격, 재고, 배송

| PostgreSQL | source |
| --- | --- |
| `product_prices.market` | `ownerclan` |
| `product_prices.price_type` | `current_supply`, `fixed` |
| `product_prices.amount` | `prices.currentSupplyPrice`, `prices.fixedPrice` |
| `product_inventory.stock_quantity` | 옵션 수량 합계. 원본 수량은 `inventory.apiStockQuantity`에 보존 |
| `product_shipping_fees.market` | `ownerclan` |
| `product_shipping_fees.fee` | `shippingFee`가 단일 숫자로 해석되는 경우 |
| `product_shipping_fees.shipping_type` | 계산 가능한 배송비 유형이면 정규화, 아니면 `unknown` |

`shippingFee`와 `shippingType` 원본은 `shipping.feeRaw`, `shipping.typeRaw`, `payload.source_fields`에 보존합니다. `shippingType='inAdvance'`는 금액 유형이 아니라 결제 방식으로 보고 `payload.shipping_payment='prepaid'`로 저장합니다. 무료배송은 `shippingType`이 free 계열이거나 `shippingFee`가 0일 때만 `is_free_shipping=True`로 저장합니다.

## 보조 discovery

`ownerclan_API.workflows.discover_products`는 keyword 검색 결과의 상품 key를 PostgreSQL `product_discovery_targets`에 저장합니다. 기본 `python -m ownerclan_API` 실행은 카테고리 전체 수집과 증분 수집만 수행하므로 이 보조 discovery를 자동 실행하지 않습니다.

오너클랜은 `product_search_ranks`에 저장하지 않습니다. 현재 수집 경로의 Seller API 응답은 순위 분석에 쓸 수 있는 인기순/랭킹 의미를 제공하지 않습니다.

## 재개 상태

- `data/state/category-collection-state.json`: 단일 worker 카테고리 수집 재개 위치
- `data/state/category-collection-progress.json`: 병렬 worker 카테고리 수집 재개 위치
- `data/state/detail-collection-state.json`: 보조 상세 수집 workflow 재개 위치
- `data/state/incremental-state.json`: 증분 수집 기준 시각

카테고리/상세 상태 파일은 PostgreSQL 저장이 성공한 뒤에만 다음 cursor 또는 다음 배치 위치를 기록합니다.

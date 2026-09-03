# 도매꾹/도매매 데이터 매핑

도매꾹/도매매 Open API 응답은 `domeggook_API.services.parsing.parse_detail_product()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다. 공통 테이블 컬럼과 unique key는 [DB_FIELD_SPEC.md](../docs/schema/DB_FIELD_SPEC.md)를 기준으로 봅니다.

## 상품 기본값

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `domeggook` |
| `products.external_product_id` | `productId` |
| `products.product_name` | 정규화된 상품명 |
| `products.product_url` | 정규화된 상품 URL |
| `products.image_url` | `thumb.original` 또는 이미지 필드의 첫 번째 URL |
| `products.backup_image_url` | `image`, `imageInfo`, `img`, `imageUrl`, `productImage` 등 추가 이미지 후보 |

## 가격, 재고, 배송

| PostgreSQL | source |
| --- | --- |
| `product_prices.market='dome'` | `prices.domeCurrentSupplyPrice` |
| `product_prices.market='supply'` | `prices.supplyCurrentSupplyPrice` |
| `product_prices.market='retail'` | `minimumRetailPrice`, `recommendedRetailPrice` |
| `product_inventory.stock_quantity` | `qty.inventory` |
| `product_shipping_fees.market='dome'` | `deli.dome.fee`, `deli.dome.tbl`, `deli.dome.type` |
| `product_shipping_fees.market='supply'` | `deli.supply.fee`, `deli.supply.tbl`, `deli.supply.type` |

도매꾹과 도매매 배송비는 `dome`, `supply` row로 분리합니다. 수량별 조건표는 최종 배송비로 계산하지 않고 `payload.shipping_fee_raw`, `payload.shipping_rules`, `payload.requires_quantity_calculation`에 보존합니다. 도매매 배송비가 비어 있어도 도매꾹 배송비로 `supply` row를 임의 생성하지 않습니다.

## discovery와 순위 이력

| PostgreSQL | source |
| --- | --- |
| `product_discovery_targets` | discovery/recent discovery에서 발견한 상품 ID |
| `product_search_ranks` | 순위 의미가 있는 category, market, sort, 전체 결과 기준 rank |

`product_search_ranks`는 `ha`, `rd` sort만 저장합니다. `da`는 최근 등록/수정일 기준이며 순위 분석용 sort가 아니므로 daily recent discovery에서는 `product_discovery_targets`만 보강합니다.

## 재개 상태

- `data/state/discovery-state.json`: full discovery 재개 위치
- `data/state/detail-collection-state.json`: 상세 수집 재개 위치
- `data/state/recent-discovery-state.json`: daily recent discovery 재개 위치

상태 파일은 상품 데이터 저장소가 아닙니다. PostgreSQL 저장이 성공한 뒤에만 다음 페이지 또는 다음 배치 위치를 기록합니다.

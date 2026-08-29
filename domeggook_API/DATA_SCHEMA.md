# 도매꾹/도매매 데이터 스키마

도매꾹/도매매 Open API 응답은 `parse_detail_product()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장한다.

## PostgreSQL 매핑

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `domeggook` |
| `products.external_product_id` | `productId` |
| `product_prices.market='dome'` | `prices.domeCurrentSupplyPrice` |
| `product_prices.market='supply'` | `prices.supplyCurrentSupplyPrice` |
| `product_prices.market='retail'` | `minimumRetailPrice`, `recommendedRetailPrice` |
| `product_inventory.stock_quantity` | `qty.inventory` |
| `product_shipping_fees.market='dome'` | `shipping.domeFee` / `shipping.domeFeeRaw` |
| `product_shipping_fees.market='supply'` | `shipping.supplyFee` / `shipping.supplyFeeRaw` |
| `product_raw_samples.payload` | raw 디버깅 샘플 |
| `product_search_ranks` | category, market, sort, rank |

## 배송비

도매꾹/도매매 배송비는 별도 row로 저장한다.

- 도매꾹: `market='dome'`
- 도매매: `market='supply'`

배송비 부담 방식은 `shipping.feePayer`에서 정규화되어 `product_shipping_fees.payload.shipping_payment`에 보존된다.

## 재고

현재 API 문서와 parser 기준으로 재고는 `qty.inventory` 하나다. `domeInventory`나 `supplyInventory`처럼 시장별 재고 필드는 사용하지 않는다.

시장별 주문 조건은 별도 필드로 보존한다.

- `inventory.domeMoq`
- `inventory.domeMaxOrderQuantity`
- `inventory.domeOrderUnit`
- `inventory.supplyOrderUnit`

## raw 샘플

예전 `data/raw/domeggook_*_raw.json` 파일은 더 이상 생성하지 않는다. raw 샘플은 `product_raw_samples`에 저장하고, 저장 호출당 최대 3개 상품으로 제한한다.

## 파일 기반 상태

- `data/state/categories.json`
- `data/state/tracked_products.json`

이 파일들은 실행 입력/캐시이며 상품 결과 저장소가 아니다.

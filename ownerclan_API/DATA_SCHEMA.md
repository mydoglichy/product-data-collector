# 오너클랜 데이터 스키마

오너클랜 Seller GraphQL 응답은 `normalize_item()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장한다.

## PostgreSQL 매핑

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `ownerclan` |
| `products.external_product_id` | `productId` 또는 `productKey` |
| `products.current_payload` | 최신 정규화 상품 payload |
| `products.comparable_payload` | `prices`, `inventory`, `shipping`, `options`, `status`, `sourceStatus` |
| `product_prices.market` | `ownerclan` |
| `product_prices.amount` | `prices.currentSupplyPrice`, `prices.fixedPrice` |
| `product_inventory.stock_quantity` | `inventory.stockQuantity` |
| `product_shipping_fees.market` | `ownerclan` |
| `product_shipping_fees.fee` | `shippingFee`가 단일 숫자로 확인되는 경우의 원본 배송비 |
| `product_shipping_fees.shipping_type` | 계산 가능한 배송비 타입. 확정할 수 없으면 `unknown` |
| `product_raw_samples.payload` | raw 디버깅 샘플 |

## 배송비

현재 쿼리에서 수집하는 오너클랜 배송비 API 필드는 `shippingFee`, `shippingType`이다.

- `shippingFee`는 `shipping.fee`에 숫자 변환 가능하면 숫자로 저장하고, 원본은 `shipping.feeRaw`와 `payload.source_fields.shippingFee`에 보존한다.
- `shippingType`은 `shipping.type`, `shipping.typeRaw`, `payload.source_fields.shippingType`에 보존한다.
- DB 배송비 row는 `market='ownerclan'`으로 저장한다.
- `shippingType='inAdvance'`는 배송비 금액 타입이 아니라 부담 방식으로 보고 `payload.shipping_payment='prepaid'`로 저장한다.
- 무료배송은 `shippingType`이 free 계열이거나 `shippingFee`가 0인 경우에만 `is_free_shipping=True`로 저장한다.

수량별/조건부 배송비 문자열이 내려오면 수집기와 DB 저장 단계에서는 계산하지 않고 원문과 파싱 가능한 구조만 저장한다. 개당 배송비, MOQ 배분, 판매수량 기준 배송비, 마진 계산은 플랫폼 서버에서 처리한다.

## 재고

옵션별 `quantity`가 있으면 `inventory.stockQuantity`는 `sum(options[].quantity)`로 저장한다. API 원본 수량은 `inventory.apiStockQuantity`에 보존한다.

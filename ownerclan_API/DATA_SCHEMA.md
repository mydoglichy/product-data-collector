# Ownerclan API Data Schema

이 문서는 오너클랜 Seller GraphQL API 수집 결과의 현재 파일 구조를 정리합니다. DB 연동 시에는 `output/latest-products.json`과 `output/history/product-history-YYYY-MM-DD.json`의 정규화 상품 구조를 기준으로 사용합니다.

## `tracked_products.json`

상품 key별 추적 마스터입니다. key는 `productKey` 문자열입니다.

```json
{
  "{productKey}": {
    "productId": "string",
    "productKey": "string",
    "keywords": ["string"],
    "searchTypes": ["default_top | register_date_desc | string"],
    "reasons": ["string"],
    "firstSeenAt": "ISO-8601 datetime",
    "lastSeenAt": "ISO-8601 datetime",
    "active": "boolean"
  }
}
```

## Normalized Product

`latest-products.json`, `product-snapshots-YYYY-MM-DD.json`, `product-history-YYYY-MM-DD.json`에서 공통으로 사용하는 상품 구조입니다.

```json
{
  "source": "ownerclan",
  "productId": "string | null",
  "productKey": "string | null",
  "collectedAt": "ISO-8601 datetime",
  "status": "available | soldout | discontinued | unavailable | string | null",
  "sourceStatus": "string | null",
  "productName": "string | null",
  "keywords": ["string"],
  "registeredAt": "any",
  "updatedAt": "any",
  "prices": {
    "currentSupplyPrice": "number | string | null",
    "fixedPrice": "number | string | null"
  },
  "inventory": {
    "stockQuantity": "integer | null",
    "stockQuantitySource": "sum(options[].quantity)",
    "apiStockQuantity": "any"
  },
  "options": [
    {
      "skuKey": "string | null",
      "skuType": "default | option",
      "optionAttributes": [
        {
          "name": "string | null",
          "value": "string | null"
        }
      ],
      "price": "any",
      "quantity": "any"
    }
  ],
  "shipping": {
    "fee": "any",
    "type": "any"
  },
  "category": {
    "code": "any",
    "name": "any",
    "fullName": "any"
  },
  "image": {
    "representativeUrl": "string | null",
    "urls": ["string"]
  },
  "manufacturer": "any",
  "origin": "any",
  "model": "any",
  "sourceSpecific": {
    "id": "any",
    "content": "string | null",
    "pricePolicy": "any",
    "taxFree": "any",
    "adultOnly": "any",
    "returnable": "any",
    "noReturnReason": "any",
    "guaranteedShippingPeriod": "any",
    "openmarketSellable": "any",
    "boxQuantity": "any",
    "attributes": "any",
    "closingTime": "any",
    "returnCriteria": "any",
    "metadata": "compacted metadata object",
    "vendorKey": "any"
  },
  "raw": "original API item, snapshot only"
}
```

`sourceSpecific.metadata.productNotificationInformation.categorySpecific`와 `common`이 `"상품 상세정보에 별도 표기"` 같은 placeholder 반복 배열이면 정규화 영역에서는 각각 `categorySpecificSummary`, `commonSummary`로 압축합니다. `raw` 또는 `rawSnapshots[].raw`에는 API 응답 구조를 보존하되, `productNotificationInformation.common`처럼 같은 값만 반복되는 배열은 순서 유지 중복 제거 후 저장합니다.

## `output/product-snapshots-YYYY-MM-DD.json`

해당 날짜 수집 결과입니다.

- `collectedAt`: 마지막 저장 시각
- `successCount`: `products[]` 개수
- `failureCount`: `failures[]` 개수
- `products[]`: `Normalized Product`, `raw` 포함
- `failures[]`: 실패 상품 또는 배치 정보

## `output/latest-products.json`

상품별 최신 상태입니다. key는 `productId`입니다.

- `fingerprint`: 가격, 재고, 옵션, 배송, 상태 기반 SHA-256 해시
- `rawSnapshots[]`: 상품별 최근 raw 응답. 보관 개수는 `output.raw_retention_per_product` 설정값을 따릅니다.

## `output/history/product-history-YYYY-MM-DD.json`

`fingerprint`가 변경된 정규화 상품만 누적합니다. `raw`는 포함하지 않습니다.

## `output/search-ranks-YYYY-MM-DD.json`

키워드 검색에서 발견된 순위 이력입니다.

- `collectedAt`: 마지막 rank 레코드의 수집 시각
- `ranks[]`: `collectedAt`, `keyword`, `searchType`, `rank`, `productId`, `productName` 등을 포함하는 검색 노출 레코드

## `state/incremental-state.json`

증분 수집 기준 시각입니다.

- `lastSuccessfulItemSyncAt`: 마지막 성공 증분 수집 시각

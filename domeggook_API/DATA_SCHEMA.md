# Domeggook API Data Schema

이 문서는 도매꾹/도매매 API 수집 결과의 현재 파일 구조를 정리합니다. DB 연동 시에는 `product-snapshots-YYYY-MM-DD.json`의 `products[]`를 상품 상세 snapshot 기준으로 사용합니다.

## `tracked_products.json`

상품번호별 추적 마스터입니다. key는 상품번호 문자열입니다.

```json
{
  "{productId}": {
    "productId": "string",
    "keywords": ["string"],
    "markets": ["dome | supply | string"],
    "reasons": ["string"],
    "firstSeenAt": "ISO-8601 datetime",
    "lastSeenAt": "ISO-8601 datetime",
    "active": "boolean"
  }
}
```

## `output/product-snapshots-YYYY-MM-DD.json`

일별 상품 상세 snapshot입니다. 같은 날짜 파일은 상품번호 기준으로 병합됩니다.

```json
{
  "collectedAt": "ISO-8601 datetime",
  "successCount": "integer",
  "failureCount": "integer",
  "products": [
    {
      "productId": "string | null",
      "collectedAt": "ISO-8601 datetime",
      "status": "string | null",
      "productName": "string | null",
      "keywords": "any",
      "registeredAt": "any",
      "saleStartedAt": "any",
      "saleEndedAt": "any",
      "prices": {
        "domeCurrentSupplyPrice": "any",
        "domeOriginalSupplyPrice": "any",
        "supplyCurrentSupplyPrice": "any",
        "supplyOriginalSupplyPrice": "any",
        "minimumRetailPrice": "any",
        "recommendedRetailPrice": "any"
      },
      "inventory": {
        "stockQuantity": "any",
        "domeMoq": "any",
        "domeMaxOrderQuantity": "any",
        "domeOrderUnit": "any",
        "supplyOrderUnit": "any"
      },
      "shipping": {
        "method": "any",
        "feePayer": "any",
        "domeFee": "any",
        "domeFeeType": "any",
        "supplyFee": "any",
        "supplyFeeType": "any",
        "preparationPeriod": "any",
        "averageShippingDays": "any",
        "fastShipping": "any",
        "overseasDirectShipping": "any"
      },
      "markets": {
        "domeOnSale": "any",
        "supplyOnSale": "any"
      },
      "seller": {
        "id": "any",
        "nickname": "any",
        "type": "any",
        "grade": "any",
        "excellentSeller": "any",
        "averageSatisfaction": "any",
        "reviewCount": "any"
      },
      "category": {
        "code": "any",
        "name": "any"
      },
      "image": {
        "representativeUrl": "any",
        "lastChangedAt": "any"
      },
      "raw": "original API item, optional"
    }
  ],
  "failures": [
    {
      "productId": "string | null",
      "error": "string | null",
      "code": "string | null"
    }
  ]
}
```

`raw`는 설정값 `details.raw_sample_limit` 범위 안에서만 포함됩니다.

## `output/search-ranks-YYYY-MM-DD.json`

키워드 검색에서 발견된 순위 이력입니다.

- `collectedAt`: 마지막 rank 레코드의 수집 시각
- `ranks[]`: `collectedAt`, `keyword`, `market`, `sort`, `rank`, `productId`, `productName` 등을 포함하는 검색 노출 레코드


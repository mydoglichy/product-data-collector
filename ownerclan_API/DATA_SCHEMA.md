# Ownerclan API Data Schema

오너클랜 Seller GraphQL API 수집 결과의 파일 구조입니다. DB 적재 기준은 `data/processed/*_product-snapshots.json`, `data/history/*_product-history.json`, `data/processed/*_search-ranks.json`입니다.

## 파일명 규칙

런타임 결과 파일은 `ownerclan_YYYY_MMDD_HHMM_역할.json` 형식을 사용합니다.

- 예: `ownerclan_2026_0825_1810_product-snapshots.json`
- 예: `ownerclan_2026_0825_1810_search-ranks.json`
- 예: `ownerclan_2026_0825_1810_product-history.json`

시각은 `config.yaml`의 `timezone` 기준입니다. `data/state/tracked_products.json`, `data/state/latest-products.json`, `data/state/incremental-state.json`은 다음 실행이 계속 읽는 상태 파일이므로 고정 이름을 유지합니다.

## `data/state/tracked_products.json`

상품 key별 추적 마스터입니다.

```json
{
  "{productKey}": {
    "productId": "string",
    "productKey": "string",
    "keywords": ["string"],
    "reasons": ["string"],
    "firstSeenAt": "ISO-8601 datetime",
    "lastSeenAt": "ISO-8601 datetime",
    "active": "boolean"
  }
}
```

## Normalized Product

`product-snapshots`, `latest-products`, `product-history`에서 공통으로 사용하는 상품 구조입니다.

```json
{
  "source": "ownerclan",
  "productId": "string | null",
  "productKey": "string | null",
  "collectedAt": "ISO-8601 datetime",
  "status": "available | soldout | discontinued | unavailable | string | null",
  "sourceStatus": "string | null",
  "productName": "string | null",
  "prices": {
    "currentSupplyPrice": "number | string | null",
    "fixedPrice": "number | string | null"
  },
  "inventory": {
    "stockQuantity": "integer | null",
    "stockQuantitySource": "sum(options[].quantity)",
    "apiStockQuantity": "any"
  },
  "options": [],
  "shipping": {},
  "category": {},
  "sourceSpecific": {}
}
```

상품 상세 snapshot에는 공급사 원본 검색키워드, 이미지 URL, 상세문구 HTML, 외부몰 자동등록용 카테고리 매핑 metadata, raw 응답을 저장하지 않습니다. 검색에 사용한 키워드와 순위는 `search-ranks.json`에만 저장합니다.

## `data/processed/ownerclan_YYYY_MMDD_HHMM_product-snapshots.json`

해당 실행의 상품 상세 snapshot입니다.

- `collectedAt`: 저장 시각
- `successCount`: `products[]` 개수
- `failureCount`: `failures[]` 개수
- `products[]`: 정규화 상품. 원본 `raw`는 포함하지 않음
- `failures[]`: 실패 상품 또는 요청 정보

## `data/raw/ownerclan_YYYY_MMDD_HHMM_raw.json`

원본 API 응답 샘플입니다. 항상 최대 3개 상품만 저장하며, 이미지 URL, 상세문구, 공급사 원본 검색키워드, 외부몰 카테고리 매핑 metadata는 제거한 축약본입니다.

## `data/state/latest-products.json`

상품별 최신 정규화 상태입니다. 변경 감지용 `fingerprint`를 저장하며 raw 응답은 포함하지 않습니다.

## `data/history/ownerclan_YYYY_MMDD_HHMM_product-history.json`

`fingerprint`가 변경된 정규화 상품만 저장합니다. `raw`는 포함하지 않습니다.

## `data/processed/ownerclan_YYYY_MMDD_HHMM_search-ranks.json`

키워드 검색에서 발견된 상품 순위 기록입니다.

```json
{
  "collectedAt": "ISO-8601 datetime",
  "ranks": [
    {
      "collectedAt": "ISO-8601 datetime",
      "keyword": "string",
      "sortBy": "default | registerDateDesc | string",
      "productId": "string",
      "productKey": "string",
      "rank": "integer"
    }
  ]
}
```

`sortBy`는 API 요청에 실제 사용된 정렬 조건입니다. 기본 정렬은 API 요청에 `sortBy` 파라미터를 보내지 않고, 저장 시에는 `"default"`로 기록합니다.

## `data/state/incremental-state.json`

증분 수집 기준 시각입니다.

- `lastSuccessfulItemSyncAt`: 마지막 성공 증분 수집 시각

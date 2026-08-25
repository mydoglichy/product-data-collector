# Domeggook API Data Schema

도매꾹/도매매 API 수집 결과의 파일 구조입니다. DB 적재 기준은 `data/processed/*_product-snapshots.json`의 `products[]`와 `data/processed/*_search-ranks.json`의 `ranks[]`입니다.

## 파일명 규칙

런타임 결과 파일은 `domeggook_YYYY_MMDD_HHMM_역할.json` 형식을 사용합니다.

- 예: `domeggook_2026_0825_1810_product-snapshots.json`
- 예: `domeggook_2026_0825_1810_search-ranks.json`

시각은 `config.yaml`의 `timezone` 기준입니다. `data/state/tracked_products.json`은 다음 실행이 계속 읽는 상태 파일이므로 고정 이름을 유지합니다.

## `data/state/tracked_products.json`

상품번호별 추적 마스터입니다.

```json
{
  "{productId}": {
    "productId": "string",
    "keywords": ["string"],
    "markets": ["dome | supply"],
    "reasons": ["popular | recent"],
    "firstSeenAt": "ISO-8601 datetime",
    "lastSeenAt": "ISO-8601 datetime",
    "active": "boolean"
  }
}
```

## Normalized Product

상품 상세 snapshot의 `products[]`에 들어가는 정규화 상품 구조입니다.

```json
{
  "source": "domeggook",
  "productId": "string | null",
  "collectedAt": "ISO-8601 datetime",
  "status": "string | null",
  "productName": "string | null",
  "prices": {},
  "inventory": {},
  "shipping": {},
  "seller": {},
  "category": {},
  "image": {},
  "sourceSpecific": {},
  "raw": "original API item, optional"
}
```

`raw`는 `details.raw_sample_limit` 범위 안에서만 포함됩니다.

## `data/processed/domeggook_YYYY_MMDD_HHMM_product-snapshots.json`

상품 상세 snapshot입니다.

- `collectedAt`: 저장 시각
- `successCount`: `products[]` 개수
- `failureCount`: `failures[]` 개수
- `products[]`: 상품별 정규화 상세 데이터
- `failures[]`: 실패 상품 또는 요청 정보

## `data/processed/domeggook_YYYY_MMDD_HHMM_search-ranks.json`

검색 순위 기록입니다.

- `collectedAt`: 마지막 rank 레코드의 수집 시각
- `ranks[]`: `collectedAt`, `keyword`, `market`, `sort`, `reason`, `productId`, `rank`

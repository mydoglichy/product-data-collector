# Coupang API Data Schema

쿠팡 파트너스 상품 검색 API 수집 결과의 파일 구조입니다. DB 적재 기준은 `data/processed/*_products.jsonl`의 한 줄 단위 상품 레코드입니다.

## 파일명 규칙

수집 결과 파일은 `coupang_YYYY_MMDD_HHMM_역할.확장자` 형식을 사용합니다.

- 예: `coupang_2026_0825_1810_products.jsonl`
- 예: `coupang_2026_0825_1810_summary.json`
- 예: `coupang_2026_0825_1810_raw_USB.json`

시각은 `Asia/Seoul` 기준입니다.

## `data/processed/coupang_YYYY_MMDD_HHMM_products.jsonl`

상품 1개를 한 줄 JSON으로 저장합니다. 불필요하거나 중복되는 `collector`, `requestedKeyword`, `landingUrl`, `productImage`는 저장하지 않습니다.

```json
{
  "productId": "integer | string | null",
  "itemId": "string | null",
  "vendorItemId": "string | null",
  "productName": "string | null",
  "productPrice": "integer | float | string | null",
  "productUrl": "string | null",
  "keyword": "string",
  "rank": "integer | null",
  "isRocket": "boolean | null",
  "isFreeShipping": "boolean | null",
  "collectedAt": "ISO-8601 datetime"
}
```

`keyword`는 해당 검색에 사용한 키워드입니다. API 응답 상품에 `keyword`가 없으면 요청 키워드를 저장합니다.

## `data/raw/coupang_YYYY_MMDD_HHMM_raw_{keyword}.json`

키워드별 API 원본 응답 샘플입니다. `config.yaml`의 `output.raw_sample_limit` 개수만 저장합니다.

## `data/summaries/coupang_YYYY_MMDD_HHMM_summary.json`

한 번의 실행 요약입니다.

- `runStartedAt`, `runEndedAt`: 실행 시작/종료 시각
- `totalKeywords`, `processedKeywords`: 전체/처리 키워드 수
- `successCount`, `failureCount`: 성공/실패 수
- `collectedProductCount`: 저장된 상품 수
- `duplicateProductCount`: 같은 실행 안에서 제거된 완전 중복 수
- `rawSampleLimit`, `rawSavedCount`, `removedRawFileCount`: raw 샘플 저장/정리 결과

## `data/state/product_search_checkpoint.json`

중간 재시작용 상태 파일입니다. 모든 키워드가 성공하면 삭제합니다.

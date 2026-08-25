# Coupang API Data Schema

이 문서는 쿠팡 파트너스 상품 검색 API 수집 결과의 현재 파일 구조를 정리합니다. 신규 저장소나 DB 테이블을 만들 때는 `data/processed/*.jsonl`의 레코드를 기준 구조로 봅니다.

## `data/processed/{run_stamp}_products.jsonl`

한 줄에 상품 1개를 저장하는 JSON Lines 파일입니다.

```json
{
  "api": {
    "keyword": "string | null",
    "rank": "integer | null",
    "isRocket": "boolean | null",
    "isFreeShipping": "boolean | null",
    "productId": "integer | string | null",
    "itemId": "string | null",
    "vendorItemId": "string | null",
    "productImage": "string | null",
    "productName": "string | null",
    "productPrice": "integer | float | string | null",
    "productUrl": "string | null",
    "landingUrl": "string | null"
  },
  "collector": {
    "requestedKeyword": "string",
    "collectedAt": "ISO-8601 datetime",
    "source": "coupang_partners_product_search"
  }
}
```

## `data/raw/{run_stamp}_{keyword}_raw.json`

키워드별 API 원본 응답입니다. 장애 분석과 필드 추가 검토용으로만 사용하고, 정규화 기준은 `data/processed/*.jsonl`을 우선합니다.

## `data/summaries/{run_stamp}_summary.json`

수집 실행 단위 요약입니다.

- `runStamp`: 실행 식별 시각
- `startedAt`, `finishedAt`: 실행 시작/종료 시각
- `processedPath`: JSONL 결과 파일 경로
- `totalWritten`: 저장된 상품 레코드 수
- `successKeywords`: 성공 키워드 목록
- `failureKeywords`: 실패 키워드 목록

# Coupang API Collector

쿠팡 파트너스 상품 검색 API에서 키워드별 상품 검색 결과를 수집합니다. 상품 분석과 DB 적재 기준은 `data/processed/*_products.jsonl`입니다.

## 수집 흐름

1. `coupang_API/keywords.txt`에서 키워드를 읽습니다.
2. 키워드별로 쿠팡 파트너스 상품 검색 API를 호출합니다.
3. 상품명, 가격, 이미지, 상품 URL, 순위, 로켓배송/무료배송 여부를 정규화합니다.
4. 정규화 결과를 JSONL로 저장합니다.
5. raw 원본 응답은 설정된 샘플 개수만 남깁니다.
6. 실행 요약과 실패 키워드를 summary 파일에 저장합니다.
7. 중간 실패 시 checkpoint로 완료 키워드를 기억하고 다음 실행에서 이어갑니다.

## 주요 파일

| 용도 | 경로 |
| --- | --- |
| 검색 키워드 | `coupang_API/keywords.txt` |
| 설정 | `coupang_API/config.yaml` |
| 정규화 상품 결과 | `coupang_API/data/processed/coupang_YYYY_MMDD_HHMM_products.jsonl` |
| raw 원본 샘플 | `coupang_API/data/raw/coupang_YYYY_MMDD_HHMM_raw_{keyword}.json` |
| 실행 요약 | `coupang_API/data/summaries/coupang_YYYY_MMDD_HHMM_summary.json` |
| 재시작 상태 | `coupang_API/data/state/product_search_checkpoint.json` |

`data/`는 런타임 결과라 Git에 올리지 않습니다.

## 파일명 규칙

수집 결과 파일은 `coupang_YYYY_MMDD_HHMM_역할.확장자` 형식을 사용합니다.

예:

```text
coupang_2026_0825_1810_products.jsonl
coupang_2026_0825_1810_summary.json
coupang_2026_0825_1810_raw_USB_허브.json
```

시각은 `Asia/Seoul` 기준입니다.

## 설정

```yaml
requests_per_minute: 40

request:
  limit: 10
  image_size: 512x512
  srp_link_only: false

output:
  raw_sample_limit: 3
```

- `requests_per_minute`: 분당 요청 수. 코드에서 최대 50으로 제한합니다.
- `request.limit`: 쿠팡 공식 검색 요청은 10으로 고정됩니다.
- `request.image_size`: 상품 이미지 크기 옵션입니다.
- `output.raw_sample_limit`: raw 원본 응답을 실행별로 몇 개 남길지 정합니다. 기본값은 3입니다.

## 실행

프로젝트 루트에서 실행합니다.

```powershell
python -m coupang_API
```

테스트:

```powershell
pytest coupang_API/tests
```

## DB 전환 기준

나중에 DB로 옮길 때는 `processed`의 상품 레코드를 기준으로 테이블을 만들면 됩니다.

- `collector.collectedAt`: 상품별 수집 시각
- 파일명 stamp `coupang_YYYY_MMDD_HHMM`: 실행 묶음 식별자
- `api.productId`, `api.itemId`, `api.vendorItemId`: 상품 식별용 후보

DB 저장 시에도 연도/날짜/시간이 필요하면 파일명만 믿기보다 `collection_run_id` 또는 `collected_at` 컬럼으로 저장하는 쪽이 안전합니다.

# Ownerclan API Collector

오너클랜 Seller GraphQL API로 상품코드를 발견하고, 추적 대상 상품의 가격, 재고, 옵션, 배송, 판매상태를 주기적으로 저장합니다. Partner/Vendor API가 아니라 Seller API 기준입니다.

## 수집 흐름

1. `ownerclan_API/keywords.txt`에서 키워드를 읽습니다.
2. 키워드별 기본 검색과 최신 등록순 검색을 실행합니다.
3. 발견한 `Item.key`를 `data/state/tracked_products.json`에 누적합니다.
4. 추적 대상 상품을 batch로 상세 조회합니다.
5. 상품 상세 snapshot, 최신 상태, 변경 이력을 저장합니다.
6. 증분 수집은 마지막 성공 시각 이후 수정된 상품을 다시 조회합니다.

## 주요 파일

| 용도 | 경로 |
| --- | --- |
| 검색 키워드 | `ownerclan_API/keywords.txt` |
| 설정 | `ownerclan_API/config.yaml` |
| 추적 상품 마스터 | `ownerclan_API/data/state/tracked_products.json` |
| 상품 상세 snapshot | `ownerclan_API/data/processed/ownerclan_YYYY_MMDD_HHMM_product-snapshots.json` |
| 검색 순위 이력 | `ownerclan_API/data/processed/ownerclan_YYYY_MMDD_HHMM_search-ranks.json` |
| 변경 상품 이력 | `ownerclan_API/data/history/ownerclan_YYYY_MMDD_HHMM_product-history.json` |
| raw 원본 샘플 | `ownerclan_API/data/raw/ownerclan_YYYY_MMDD_HHMM_raw.json` |
| 최신 상품 상태 | `ownerclan_API/data/state/latest-products.json` |
| 실패 요약 | `ownerclan_API/data/summaries/ownerclan_YYYY_MMDD_HHMM_failures.json` |
| 증분 수집 상태 | `ownerclan_API/data/state/incremental-state.json` |
| 실행 로그 | `ownerclan_API/data/logs/collector.log` |

`data/`는 런타임 파일이라 Git에 올리지 않습니다.

## 파일명 규칙

수집 결과 파일은 `ownerclan_YYYY_MMDD_HHMM_역할.json` 형식을 사용합니다.

예:

```text
ownerclan_2026_0825_1810_product-snapshots.json
ownerclan_2026_0825_1810_search-ranks.json
ownerclan_2026_0825_1810_product-history.json
```

`data/state/tracked_products.json`, `data/state/latest-products.json`, `data/state/incremental-state.json`은 다음 실행이 계속 읽어야 하는 상태 파일이므로 고정 이름을 유지합니다.

## 설정

```yaml
output:
  tracked_products_path: ownerclan_API/data/state/tracked_products.json
  output_dir: ownerclan_API/data/processed
  state_dir: ownerclan_API/data/state
  log_dir: ownerclan_API/data/logs
  raw_sample_limit: 3
```

- `discovery.top_limit_per_keyword`: 기본 검색 상위 상품 수
- `discovery.new_limit_per_keyword`: 최신 등록순 상위 상품 수
- `details.batch_size`: 상세 조회 batch 크기
- `incremental.overlap_minutes`: 증분 수집 기준 시각 겹침
- `output.raw_sample_limit`: `data/raw`에 저장할 원본 응답 샘플 개수. 저장 함수에서 항상 최대 3개로 제한합니다.

## 실행

프로젝트 루트에서 실행합니다.

```powershell
python -m ownerclan_API.main
```

단계별 실행:

```powershell
python -m ownerclan_API.discover_products
python -m ownerclan_API.collect_product_details
python -m ownerclan_API.sync_incremental
```

소량 테스트:

```powershell
python -m ownerclan_API.main --limit 1
python -m ownerclan_API.main --limit 1 --dry-run
```

테스트:

```powershell
pytest ownerclan_API/tests
```

## DB 전환 기준

DB 적재 기준은 timestamp가 붙은 snapshot/history/rank 파일입니다.

- `ownerclan_*_product-snapshots.json` -> 상품 snapshot 테이블
- `ownerclan_*_product-history.json` -> 변경 이력 테이블
- `ownerclan_*_search-ranks.json` -> 검색 노출 이력 테이블
- `data/state/tracked_products.json` -> 추적 상품 마스터 테이블

DB 저장 시에는 `collectedAt`과 별도의 `collection_run_id`를 함께 저장하는 편이 좋습니다. 파일명 stamp와 같은 값을 `collection_run_id`로 쓰면 파일 저장 방식과 DB 저장 방식을 맞출 수 있습니다.

검색 순위 파일의 `ranks[]`는 `keyword`, `sortBy`, `productId`, `productKey`, `rank`, `collectedAt`을 저장합니다. 기본 정렬은 API 요청에 `sortBy` 파라미터를 보내지 않고 저장 데이터에는 `"default"`로 남기며, 최신 등록순은 `"registerDateDesc"`로 남깁니다.

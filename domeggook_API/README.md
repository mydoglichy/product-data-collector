# Domeggook API Collector

도매꾹/도매매 Open API 수집기입니다. 카테고리 기반 상품 목록에서 추적 대상 상품번호를 발견하고, 추적 대상의 상세 정보를 주기적으로 저장합니다.

## 현재 수집 방식

1. `getCategoryList`로 카테고리 목록을 가져와 `data/state/categories.json`에 캐시합니다.
2. 중분류 이하 카테고리를 기준으로 도매꾹(`dome`)과 도매매(`supply`) 상품 목록을 조회합니다.
3. 인기순(`ha`)과 최신/수정순(`da`) 결과에서 상품번호와 검색 순위를 저장합니다.
4. 발견한 상품번호는 `data/state/tracked_products.json`에 누적합니다.
5. 추적 대상 상품은 `getItemView`로 100개씩 묶어 상세 snapshot을 저장합니다.
6. 실행별 검색 순위, 상품 snapshot, raw 샘플, 실패 내역을 런타임 파일로 남깁니다.

## 실행

프로젝트 루트에서 실행합니다.

```powershell
python -m domeggook_API.main
```

소량 확인:

```powershell
python -m domeggook_API.main --limit 1
python -m domeggook_API.main --limit 1 --dry-run
```

단계별 실행:

```powershell
python -m domeggook_API.discover_products
python -m domeggook_API.collect_product_details
```

테스트:

```powershell
pytest domeggook_API/tests
```

## 환경 변수

`.env`에 도매꾹 API 키를 설정합니다.

```text
DOMEGGOOK_API_KEY_1=...
DOMEGGOOK_API_KEY_2=...
```

기존 단일 키 환경은 `DOMEGGOOK_API_KEY`로도 동작합니다. numbered key가 하나라도 있으면 `DOMEGGOOK_API_KEY_1`, `DOMEGGOOK_API_KEY_2`가 모두 필요합니다.

## 설정

기본 설정은 `domeggook_API/config.yaml`입니다.

```yaml
discovery:
  markets:
    - dome
    - supply
  sorts:
    popular: ha
    recent: da
  items_per_keyword: 20

details:
  batch_size: 100
  raw_sample_limit: 3

request:
  max_requests_per_minute: 120
  max_requests_per_hour: 9000
  max_requests_per_day: 14000
  timeout_seconds: 20
  max_retries: 3

timezone: Asia/Seoul
```

운영 기본값은 공식 한도보다 낮게 잡습니다. 실측 기준 180 RPM 이상에서는 429가 발생했고, 120 RPM은 180초 테스트에서 429 없이 통과했습니다.

## 산출물

`data/` 아래 파일은 런타임 산출물이므로 Git에 올리지 않습니다.

| 용도 | 경로 |
| --- | --- |
| 카테고리 캐시 | `domeggook_API/data/state/categories.json` |
| 추적 상품 마스터 | `domeggook_API/data/state/tracked_products.json` |
| 최신 상품 상태 | `domeggook_API/data/state/latest-products.json` |
| 실행 이력 | `domeggook_API/data/state/collection-runs.json` |
| 상품 snapshot | `domeggook_API/data/processed/domeggook_YYYY_MMDD_HHMM_product-snapshots.json` |
| 검색 순위 이력 | `domeggook_API/data/processed/domeggook_YYYY_MMDD_HHMM_search-ranks.json` |
| 상품 변경 이력 | `domeggook_API/data/history/domeggook_YYYY_MMDD_HHMM_product-history.json` |
| raw 샘플 | `domeggook_API/data/raw/domeggook_YYYY_MMDD_HHMM_raw.json` |
| 실패 내역 | `domeggook_API/data/summaries/domeggook_YYYY_MMDD_HHMM_failures.json` |
| 실행 로그 | `domeggook_API/data/logs/collector.log` |

파일명 시각은 `config.yaml`의 `timezone` 기준입니다. DB 적재 기준 구조는 `domeggook_API/DATA_SCHEMA.md`를 따릅니다.

## 운영 한도 결론

2026-08-29 KST 기준 실측 결론입니다.

- 안정 운영 속도는 전체 120 RPM, 요청 간격 0.5초입니다.
- 보수적으로 장시간 운영할 때는 전체 100 RPM, 요청 간격 0.6초를 사용합니다.
- 5개 API Key 라운드로빈에서도 429 없는 최대 실측값은 전체 120 RPM, Key당 24 RPM이었습니다.
- 180 RPM은 공식 분당 최대값과 같지만, 실측에서는 약 117초부터 429가 발생해 운영 기본값으로 쓰지 않습니다.
- 240 RPM은 이전 측정에서 53~89초 사이에 429가 발생했습니다.
- 429 직후 모든 Key가 일괄 차단되지는 않았지만, 다른 Key에서도 429가 이어져 단순 Key별 제한만으로 설명하기 어렵습니다.
- 운영상 제한은 Key별 한도보다 계정/IP/엔드포인트/sliding window/burst 제한이 함께 걸린다고 보고 보수적으로 다룹니다.
- 하루 호출 한도는 공식 문서 기준 15,000회이며, 로컬 기본값은 여유를 둔 14,000회입니다.

## 전체 상품 수집 결론

2026-08-29 KST 기준 검증 결과입니다.

- 도매꾹 판매중 상품 수는 depth 2 카테고리별 `getItemList.header.numberOfItems` 합산 기준 약 4,134,761개입니다.
- 상품 목록 API의 `sz=200`은 실제 호출에서 동작했습니다.
- depth 2 카테고리 전체 목록 수집에는 `sz=200` 기준 약 20,776회 호출이 필요합니다.
- 하루 15,000회 제한이 적용되면 도매꾹 전체 판매중 상품을 하루 안에 모두 수집하는 것은 불가능합니다.
- 하루 최대 수집량은 `sz=200` 기준 약 3,000,000개, 전체의 약 72.6%입니다.

## 429 대응 기준

- 429가 발생한 요청은 즉시 재시도하지 않습니다.
- 해당 Key는 최소 60초 cooldown 처리합니다.
- 전체 호출 간격은 일시적으로 0.5초에서 0.75~1.0초로 늦춥니다.
- 재시도는 60초, 120초, 240초 백오프를 사용하고 10~20% jitter를 둡니다.
- 같은 10분 구간에서 429가 3회 이상 발생하면 전체 RPM을 120에서 100으로 낮춥니다.

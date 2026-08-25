# Domeggook API Collector

도매꾹/도매매 Open API로 키워드 검색 결과에서 상품번호를 발견하고, 추적 대상 상품의 가격, 재고, 배송, 판매자 정보를 주기적으로 저장합니다.

## 수집 흐름

1. `domeggook_API/keywords.txt`에서 키워드를 읽습니다.
2. 도매꾹(`dome`)과 도매매(`supply`)를 각각 검색합니다.
3. 인기순(`popular`)과 최신/수정순(`recent`) 검색 결과에서 상품번호를 발견합니다.
4. 발견 상품번호를 `data/state/tracked_products.json`에 누적합니다.
5. 추적 대상 상품을 batch로 상세 조회합니다.
6. 검색 순위 이력과 상품 상세 snapshot을 저장합니다.

## 주요 파일

| 용도 | 경로 |
| --- | --- |
| 검색 키워드 | `domeggook_API/keywords.txt` |
| 설정 | `domeggook_API/config.yaml` |
| 추적 상품 마스터 | `domeggook_API/data/state/tracked_products.json` |
| 상품 상세 snapshot | `domeggook_API/data/processed/domeggook_YYYY_MMDD_HHMM_product-snapshots.json` |
| 검색 순위 이력 | `domeggook_API/data/processed/domeggook_YYYY_MMDD_HHMM_search-ranks.json` |
| 실행 로그 | `domeggook_API/data/logs/collector.log` |

`data/`는 런타임 파일이라 Git에 올리지 않습니다.

## 파일명 규칙

수집 결과 파일은 `domeggook_YYYY_MMDD_HHMM_역할.json` 형식을 사용합니다.

예:

```text
domeggook_2026_0825_1810_product-snapshots.json
domeggook_2026_0825_1810_search-ranks.json
```

`data/state/tracked_products.json`은 다음 실행이 계속 읽어야 하는 상태 파일이므로 고정 이름을 유지합니다.

## 설정

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
  raw_sample_limit: 20
```

- `discovery.items_per_keyword`: 키워드/마켓/정렬별 검색 상품 수
- `details.batch_size`: 상세 조회 batch 크기
- `details.raw_sample_limit`: snapshot 안에 raw 원본 응답을 포함할 상품 수
- `request.max_requests_per_minute`: 분당 요청 수
- `timezone`: 파일명과 수집 시각 기준 timezone

## 실행

프로젝트 루트에서 실행합니다.

```powershell
python -m domeggook_API.main
```

단계별 실행:

```powershell
python -m domeggook_API.discover_products
python -m domeggook_API.collect_product_details
```

소량 테스트:

```powershell
python -m domeggook_API.main --limit 1
python -m domeggook_API.main --limit 1 --dry-run
```

테스트:

```powershell
pytest domeggook_API/tests
```

## DB 전환 기준

DB 적재 기준은 timestamp가 붙은 snapshot/rank 파일입니다.

- `domeggook_*_product-snapshots.json` -> 상품 snapshot 테이블
- `domeggook_*_search-ranks.json` -> 검색 노출 이력 테이블
- `data/state/tracked_products.json` -> 추적 상품 마스터 테이블

DB 저장 시에는 `collectedAt`과 별도의 `collection_run_id`를 함께 저장하는 편이 좋습니다. 파일명 stamp와 같은 값을 `collection_run_id`로 쓰면 파일 저장 방식과 DB 저장 방식을 맞출 수 있습니다.

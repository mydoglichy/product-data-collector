# Product Data Collector

쿠팡 파트너스, 오너클랜, 도매꾹/도매매 상품 데이터를 수집하는 프로젝트입니다.

## 수집기

| 수집기 | 폴더 | 역할 |
| --- | --- | --- |
| 쿠팡 파트너스 | `coupang_API/` | 키워드별 상품 검색 결과 수집 |
| 오너클랜 Seller API | `ownerclan_API/` | 상품 발견, 상세 snapshot, 변경 이력, 증분 수집 |
| 도매꾹/도매매 Open API | `domeggook_API/` | 상품 발견, 상세 snapshot, 검색 순위 이력 |

## 설치

```powershell
cd C:\dev\product-data-collector
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env`는 프로젝트 루트에만 둡니다.

```env
COUPANG_ACCESS_KEY=...
COUPANG_SECRET_KEY=...
OWNERCLAN_USERNAME=...
OWNERCLAN_PASSWORD=...
DOMEGGOOK_API_KEY=...
```

## 파일명 규칙

런타임 결과 파일은 API명과 수집 시각을 앞에 붙입니다.

```text
{api}_YYYY_MMDD_HHMM_{role}.json
```

예:

```text
coupang_2026_0825_1810_summary.json
ownerclan_2026_0825_1810_product-snapshots.json
domeggook_2026_0825_1810_search-ranks.json
```

쿠팡의 정규화 상품 결과는 한 줄에 상품 1개를 저장하는 JSONL이라 `.jsonl` 확장자를 사용합니다.

다음 실행이 계속 읽는 상태 파일은 고정 이름을 유지합니다.

- `data/state/tracked_products.json`
- `data/state/latest-products.json`
- `data/state/incremental-state.json`
- `data/state/product_search_checkpoint.json`

## 주요 결과 파일

| API | 기준 데이터 | raw 보관 방식 |
| --- | --- | --- |
| 쿠팡 | `coupang_API/data/processed/coupang_YYYY_MMDD_HHMM_products.jsonl` | `output.raw_sample_limit` 개수만 별도 raw 파일 저장 |
| 오너클랜 | `ownerclan_API/data/processed/ownerclan_YYYY_MMDD_HHMM_product-snapshots.json` | `data/raw/ownerclan_YYYY_MMDD_HHMM_raw.json`에 샘플 저장 |
| 도매꾹/도매매 | `domeggook_API/data/processed/domeggook_YYYY_MMDD_HHMM_product-snapshots.json` | `data/raw/domeggook_YYYY_MMDD_HHMM_raw.json`에 샘플 저장 |

각 수집기의 상세 파일 구조는 개별 README와 DATA_SCHEMA를 봅니다.

- `coupang_API/README.md`
- `ownerclan_API/README.md`
- `domeggook_API/README.md`

## 실행

```powershell
python -m coupang_API
python -m ownerclan_API.main
python -m domeggook_API.main
```

소량 테스트:

```powershell
python -m ownerclan_API.main --limit 1 --dry-run
python -m domeggook_API.main --limit 1 --dry-run
```

## 테스트

```powershell
pytest
```

개별 테스트:

```powershell
pytest coupang_API/tests
pytest ownerclan_API/tests
pytest domeggook_API/tests
```

## DB 전환 기준

나중에 JSON 대신 DB에 저장할 때도 현재 구조를 그대로 옮기면 됩니다.

- 파일명 stamp와 같은 값: `collection_run_id`
- 상품별 수집 시각: `collected_at`
- API 구분: `source` 또는 `api_name`

파일명에만 시각을 넣는 것보다 DB 컬럼으로 `collection_run_id`와 `collected_at`을 저장하는 것이 안전합니다. 현재 JSON 구조에는 이미 `collectedAt` 계열 시각이 들어가므로, DB 저장 코드를 만들 때 해당 값을 컬럼으로 매핑하면 됩니다.

## Git 제외 대상

```gitignore
.env
coupang_API/data/
ownerclan_API/data/
domeggook_API/data/
```

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

각 수집 결과 파일은 API명과 수집 시각을 앞에 붙입니다.

```text
{api}_YYYY_MMDD_HHMM_{role}.json
```

예:

```text
coupang_2026_0825_1810_summary.json
ownerclan_2026_0825_1810_product-snapshots.json
domeggook_2026_0825_1810_search-ranks.json
```

쿠팡은 정규화된 상품 검색 결과를 한 줄에 상품 1개씩 저장하는 JSONL 파일(`.jsonl`)을 사용합니다.

다음 파일은 실행 간 계속 쓰는 상태 파일이므로 고정 이름을 사용합니다.

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

## DB 전환 전 고려사항

JSON 저장 구조를 DB로 옮길 때는 상품의 현재 상태와 검색 노출 이력을 분리해서 설계합니다. 상품 snapshot은 최신 상태 조회와 변경 감지에 쓰고, 검색 순위 이력은 분석용 append-only 로그로 봅니다.

### 숫자 타입 정규화

DB 저장 전에 단순 숫자 문자열은 숫자로 변환합니다.

- 예: `"8250"` -> `8250`
- 예: `"3,000"` -> `3000`
- 예: `"10"` -> `10`
- 예: `"1.5"` -> `1.5`

재고, MOQ, 주문 단위, 배송비, 준비/배송일, 판매가처럼 숫자 컬럼으로 조회/집계할 값은 문자열로 저장하지 않습니다. 단, `"1~9개: 2,000원 / 10개 이상: 1,800원"`, `"150+3000|150+3000"`처럼 조건식 또는 구간식 의미가 있는 문자열은 원문을 보존합니다.

### 권장 테이블

- `products`: source별 상품 마스터. 외부 상품 ID와 이름, 카테고리, 대표 이미지 등 자주 조회하는 정적/준정적 필드 저장
- `product_snapshots`: 수집 시점별 상품 상세 상태. 가격, 재고, 배송, 판매 상태 등 변할 수 있는 값 저장
- `product_latest`: 상품별 최신 snapshot 캐시. 필수는 아니지만 화면 조회가 많으면 유용
- `product_change_history`: fingerprint가 바뀐 snapshot만 저장하는 변경 이력
- `search_rank_history`: 키워드 검색 결과의 노출 순위 이력. 삭제/갱신하지 않는 append-only 테이블 권장
- `collection_runs`: 실행 단위 메타데이터. source, 시작/종료 시각, 성공/실패 건수, 설정값, 오류 요약 저장
- `raw_samples`: 디버깅용 원본 응답 샘플. 운영 DB와 분리하거나 보관 기간을 짧게 둠

### 유니크 조건

상품 마스터는 source별 외부 상품 ID를 기준으로 유니크하게 잡습니다.

- 쿠팡: `(source, productId)`를 우선 사용. 필요하면 `itemId`, `vendorItemId`를 별도 컬럼으로 보존
- 오너클랜: `(source, productKey)` 또는 `(source, productId)`. 현재 정규화 결과에서는 둘 다 같은 키를 담음
- 도매꾹/도매매: `(source, productId)`

snapshot은 같은 실행에서 같은 상품이 중복 적재되지 않도록 `(source, product_id, collection_run_id)` 또는 `(source, product_id, collected_at)`를 유니크 후보로 둡니다. 단, 같은 run 안에서 마켓/채널별 별도 snapshot을 저장하도록 구조가 바뀌면 해당 구분값을 유니크 키에 포함해야 합니다.

검색 순위 이력은 같은 상품이어도 `keyword`, `rank`, `collectedAt`별로 모두 저장해야 합니다. 이전 순위와 다른 키워드에서의 순위가 사라질 수 있기 때문에 상품 ID만 기준으로 upsert하면 안 됩니다.

권장 유니크 후보:

- 쿠팡 검색 결과: `(source, requested_keyword, collected_at, product_id, rank)`
- 오너클랜 검색 순위: `(source, keyword, search_type, collected_at, product_id, rank)`
- 도매꾹 검색 순위: `(source, keyword, market, sort, collected_at, product_id, rank)`

동일 API 응답 안에서 완전히 같은 rank 레코드가 반복될 때만 중복 제거합니다. 서로 다른 키워드, 정렬, 마켓, 수집 시각의 레코드는 같은 상품이어도 모두 남깁니다.

### 중복 제거 기준

- 수집 입력 키워드는 파일 로딩 단계에서 공백/주석을 제거하고 동일 키워드를 1회만 실행합니다.
- tracked products는 상품 ID 기준으로 합치되 `keywords`, `markets`, `reasons`, `searchTypes`는 누적 배열로 보존합니다.
- snapshot은 같은 run에서 동일 상품이 여러 경로로 발견될 수 있으므로 상품 ID 기준으로 1개만 저장하되 발견 경로는 tracked metadata에 남깁니다.
- search rank history는 분석 이력이므로 상품 ID 기준 dedupe를 하지 않습니다.
- raw sample은 운영 데이터가 아니므로 보관 개수와 보관 기간을 제한합니다.

### 시간과 실행 단위

파일명 stamp만 믿지 말고 DB 컬럼으로 `collection_run_id`와 `collected_at`을 저장합니다. 현재 JSON 구조에는 이미 `collectedAt` 계열 수집 시각이 있으므로 DB 저장 코드에서 해당 값을 컬럼으로 매핑합니다.

권장 컬럼:

- `collection_run_id`: 파일명 stamp 또는 UUID
- `source`: `coupang`, `ownerclan`, `domeggook`
- `collected_at`: 상품/순위 레코드의 실제 수집 시각
- `created_at`: DB 적재 시각

### 운영 체크리스트

- API 원본 ID는 숫자처럼 보여도 식별자이므로 문자열 컬럼도 검토합니다.
- 가격/재고/배송비는 nullable numeric 컬럼으로 두고, 원문이 필요한 복합 문자열은 별도 text 컬럼 또는 sourceSpecific JSON에 보존합니다.
- 실패 레코드는 버리지 말고 실패 테이블 또는 run summary에 저장합니다.
- upsert 대상은 상품 마스터와 최신 snapshot 캐시로 제한하고, 분석 이력 테이블은 append-only로 운영합니다.
- 개인정보나 인증 값이 raw 응답에 섞이지 않는지 확인하고, raw 보관 기간을 정합니다.

## Git 제외 대상

```gitignore
.env
coupang_API/data/
ownerclan_API/data/
domeggook_API/data/
```

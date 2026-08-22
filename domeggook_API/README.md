# 도매꾹/도매매 일별 상품 데이터 수집기

`domeggook_API`는 도매꾹(`market=dome`)과 도매매(`market=supply`) 상품의 가격, 재고, 판매상태, 배송, 판매자 정보 등을 매일 파일로 누적 저장하는 수집기입니다.

도매꾹/도매매 Open API는 과거 가격/재고 이력을 제공하지 않습니다. 그래서 이 수집기는 매일 주요 키워드 검색으로 상품번호를 발견하고, 한 번 발견한 상품은 이후 검색 상위권에서 빠져도 상품번호 기반 상세조회로 계속 추적합니다.

## 핵심 파일 위치

| 용도 | 파일 |
| --- | --- |
| 검색 키워드 목록 | `domeggook_API/keywords.txt` |
| API/수집 설정 | `domeggook_API/config.yaml` |
| 추적 상품번호 마스터 | `domeggook_API/tracked_products.json` |
| 추적 상품번호 예시 | `domeggook_API/tracked_products.example.json` |
| 일별 상품 상세 snapshot | `domeggook_API/output/product-snapshots-YYYY-MM-DD.json` |
| 일별 검색순위 이력 | `domeggook_API/output/search-ranks-YYYY-MM-DD.json` |
| 실행 로그 | `domeggook_API/logs/collector.log` |
| 동시 실행 방지 lock | `domeggook_API/logs/collector.lock` |
| 환경변수 | 프로젝트 최상위 `.env` |

`tracked_products.json`, `output/`, `logs/`는 런타임 파일이라 Git에 올리지 않습니다.

## 전체 수집 흐름

1. `domeggook_API/keywords.txt`에서 키워드 읽기
2. 각 키워드로 도매꾹/도매매 각각 검색
3. 각 마켓에서 인기순(`so=ha`)과 최근 등록/수정순(`so=da`) 검색
4. 검색 결과에서 상품번호 추출
5. 새 상품번호를 `tracked_products.json`에 추가
6. 검색순위 이력을 `output/search-ranks-YYYY-MM-DD.json`에 저장
7. `tracked_products.json`의 `active=true` 상품 전체를 상세조회
8. 가격/재고/배송/판매자 등 상세 snapshot을 `output/product-snapshots-YYYY-MM-DD.json`에 저장

`so=da`는 신규등록 상품만 의미하지 않습니다. 도매꾹 API 기준 최근 등록 또는 최근 수정된 상품이 포함되므로, 코드와 데이터에서는 `recent`로 관리합니다.

## API 역할

상품리스트 API:

```text
mode=getItemList
ver=4.1
```

상품번호 발견과 검색순위 기록용입니다. 키워드, 마켓, 정렬 조건으로 상위 상품을 검색합니다.

상품상세정보 API:

```text
mode=getItemView
ver=4.6
multiple=true
```

일별 가격/재고 snapshot 저장용입니다. 상품번호를 최대 100개씩 묶어서 조회합니다. 상세 응답 하나에 도매꾹/도매매 정보가 함께 들어오므로, 도매꾹과 도매매 상세 API를 따로 두 번 호출하지 않습니다.

## 환경변수 설정

프로젝트 최상위 `.env`에 도매꾹 API 키를 넣습니다.

```env
DOMEGGOOK_API_KEY=발급받은_도매꾹_API_KEY
```

주의사항:

- `domeggook_API` 폴더 안에 별도 `.env`를 만들지 않습니다.
- 실제 `.env`는 Git에 올리지 않습니다.
- `.env.example`에는 변수명과 예시값만 둡니다.

## 키워드 관리

키워드는 이 파일에 있습니다.

```text
domeggook_API/keywords.txt
```

형식:

```text
# 한 줄에 하나씩 입력
안경 케이스
선글라스 케이스
```

규칙:

- 빈 줄은 무시합니다.
- `#`으로 시작하는 줄은 주석으로 무시합니다.
- 중복 키워드는 한 번만 요청합니다.

## 상품번호 추적 파일

발견된 상품번호는 여기에 저장됩니다.

```text
domeggook_API/tracked_products.json
```

예시:

```json
{
  "12345678": {
    "productId": "12345678",
    "keywords": ["안경 케이스", "선글라스 케이스"],
    "markets": ["dome", "supply"],
    "reasons": ["popular", "recent"],
    "firstSeenAt": "2026-08-22T09:00:00+09:00",
    "lastSeenAt": "2026-08-22T09:00:00+09:00",
    "active": true
  }
}
```

관리 기준:

- 상품번호는 숫자가 아니라 문자열로 저장합니다.
- 이미 있는 상품번호는 중복 추가하지 않습니다.
- 같은 상품이 다른 키워드/마켓/정렬에서 다시 발견되면 `keywords`, `markets`, `reasons`, `lastSeenAt`만 병합 갱신합니다.
- 검색 상위 20개에서 빠져도 자동 삭제하거나 비활성화하지 않습니다.
- `active=true`인 상품은 매일 상세조회 대상입니다.
- 수집 대상에서 제외하고 싶으면 해당 상품의 `active`를 `false`로 바꾸면 됩니다.

## 실행 방법

프로젝트 루트에서 실행합니다.

```powershell
cd C:\dev\product-data-collector
```

전체 수집:

```powershell
python -m domeggook_API.main
```

소량 테스트:

```powershell
python -m domeggook_API.main --limit 1
```

API 호출은 하지만 파일 저장은 하지 않는 테스트:

```powershell
python -m domeggook_API.main --limit 1 --dry-run
```

단계별 실행:

```powershell
python -m domeggook_API.discover_products
python -m domeggook_API.collect_product_details
```

## `--limit` 의미

`--limit 1`은 운영용이 아니라 테스트용입니다.

```powershell
python -m domeggook_API.main --limit 1
```

동작:

- 발견 단계: 키워드 1개만 검색
- 상세 단계: 추적 상품 중 1개만 상세조회

처음 API 키 연결, 응답 파싱, 파일 저장이 정상인지 확인할 때 사용합니다. 실제 매일 수집은 `--limit` 없이 실행합니다.

## 출력 파일

### 상품 상세 snapshot

파일 위치:

```text
domeggook_API/output/product-snapshots-YYYY-MM-DD.json
```

예시:

```json
{
  "collectedAt": "2026-08-22T09:00:00+09:00",
  "successCount": 100,
  "failureCount": 0,
  "products": [],
  "failures": []
}
```

`products`에는 상품별 상세 데이터가 들어갑니다.

주요 필드:

- 상품번호
- 수집시각
- 판매상태
- 상품명
- 상품 등록일/판매 시작일/판매 종료일
- 도매꾹/도매매 현재 공급가
- 도매꾹/도매매 할인 전 공급가
- 최저판매준수가격/추천판매준수가격
- 재고수량
- 도매꾹 MOQ/최대구매수량/구매단위
- 도매매 구매단위
- 배송방법/배송비/상품 준비기간/평균 발송일
- 빠른배송/해외직배송 여부
- 도매꾹/도매매 판매 여부
- 판매자 ID/닉네임/유형/등급/평점/후기 수
- 카테고리 코드/카테고리명
- 대표 이미지 URL/이미지 최종 변경일
- 원본 응답 일부를 보존하는 `raw`

같은 날 다시 실행하면 기존 파일을 무조건 덮어 날리지 않습니다. 상품번호 기준으로 병합하며, 같은 상품은 그날의 최신 수집값으로 교체합니다.

### 검색순위 이력

파일 위치:

```text
domeggook_API/output/search-ranks-YYYY-MM-DD.json
```

각 record에는 최소 다음 정보가 들어갑니다.

- 수집시각
- 키워드
- 마켓: `dome` 또는 `supply`
- 정렬코드: `ha` 또는 `da`
- 발견 사유: `popular` 또는 `recent`
- 상품번호
- 해당 검색결과 내 순위

검색순위 이력은 상품 발견 경로와 검색 노출 변화를 보기 위한 파일입니다. 실제 가격/재고 변동 분석은 `product-snapshots-YYYY-MM-DD.json`을 기준으로 합니다.

## 설정 파일

설정 위치:

```text
domeggook_API/config.yaml
```

기본값:

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

request:
  max_requests_per_minute: 120
  timeout_seconds: 20
  max_retries: 3

timezone: Asia/Seoul
```

검증 규칙:

- `items_per_keyword`는 공식 최대값 100 이하
- `details.batch_size`는 공식 최대값 100 이하
- `max_requests_per_minute`는 공식 제한 180회/분보다 낮아야 함
- 기본 timezone은 `Asia/Seoul`

## 안정성 정책

- 기본 요청 속도는 120회/분으로 공식 제한 180회/분보다 낮게 설정했습니다.
- HTTP 429는 `Retry-After` 헤더를 우선 사용합니다.
- `Retry-After`가 없으면 exponential backoff로 재시도합니다.
- 5xx와 네트워크 오류도 제한 횟수만 재시도합니다.
- 잘못된 상품 하나 때문에 전체 배치가 중단되지 않도록 실패 건은 `failures`에 따로 남깁니다.
- API Key는 로그에 남기지 않습니다.
- `tracked_products.json`과 output JSON은 임시 파일에 먼저 쓴 뒤 원자적으로 교체합니다.
- `collector.lock`으로 동일 작업의 동시 실행을 막습니다.
- 모든 날짜시간은 `Asia/Seoul` 기준 ISO-8601로 기록합니다.

## 로그 확인

실행 로그:

```powershell
Get-Content domeggook_API\logs\collector.log -Tail 100
```

Linux:

```bash
tail -n 100 domeggook_API/logs/collector.log
```

## 테스트

전체 테스트:

```powershell
pytest
```

도매꾹 수집기 테스트만:

```powershell
pytest domeggook_API/tests
```

테스트는 mock/fixture 기반입니다. 테스트 실행 시 실제 도매꾹 API를 호출하지 않습니다.

## 서버 배포와 매일 자동 실행

`python -m domeggook_API.main`은 한 번 실행하고 종료합니다. 매일 자동 수집하려면 서버 스케줄러가 필요합니다.

Linux cron 예시:

```cron
10 6 * * * cd /home/ubuntu/product-data-collector && /home/ubuntu/product-data-collector/.venv/bin/python -m domeggook_API.main >> domeggook_API/logs/cron.log 2>&1
```

의미:

- 매일 06:10 실행
- 프로젝트 루트로 이동
- 가상환경 Python으로 수집 실행
- cron 로그를 `domeggook_API/logs/cron.log`에 저장

서버 배포 시 확인할 것:

- 서버에 `.env` 파일이 있는지
- `.env`에 `DOMEGGOOK_API_KEY`가 있는지
- `pip install -r requirements.txt`가 실행됐는지
- cron에서 사용하는 Python 경로가 맞는지
- `domeggook_API/logs/`와 `domeggook_API/output/`에 쓰기 권한이 있는지

## 운영 시 자주 보는 파일

최근 발견/추적 상품 확인:

```powershell
Get-Content domeggook_API\tracked_products.json -TotalCount 80
```

오늘 상품 snapshot 확인:

```powershell
Get-Content domeggook_API\output\product-snapshots-YYYY-MM-DD.json -TotalCount 80
```

오늘 검색순위 확인:

```powershell
Get-Content domeggook_API\output\search-ranks-YYYY-MM-DD.json -TotalCount 80
```

파일이 커지면 에디터나 JSON viewer로 여는 편이 좋습니다.

## 향후 DB 전환 계획

현재는 파일 기반입니다. 나중에 DB로 전환할 때는 다음처럼 분리할 수 있게 구현했습니다.

- `tracked_products.json` -> `tracked_products` 테이블
- `product-snapshots-YYYY-MM-DD.json` -> `product_snapshots` 테이블
- `search-ranks-YYYY-MM-DD.json` -> `search_ranks` 테이블

상품 마스터 저장 로직과 일별 snapshot 저장 로직은 `storage.py`에서 분리되어 있습니다.

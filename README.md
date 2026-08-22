# Product Data Collector

쿠팡 파트너스, 도매꾹/도매매, 네이버, DataLab 관련 상품 데이터를 수집하기 위한 프로젝트입니다.

현재 구현된 주요 수집기는 다음과 같습니다.

| 수집기 | 폴더 | 상태 |
| --- | --- | --- |
| 쿠팡 파트너스 상품 검색 | `coupang_API/` | 구현됨 |
| 도매꾹/도매매 상품 발견 및 일별 상세 snapshot | `domeggook_API/` | 구현됨 |
| 네이버 API | `naver-API/` | 구조만 있음 |
| DataLab API | `dataLab_API/` | 구조만 있음 |

## 설치

프로젝트 루트에서 실행합니다.

```powershell
cd C:\dev\product-data-collector
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cd /path/to/product-data-collector
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 환경변수

프로젝트 최상위 `.env`에 API 키를 설정합니다.

```env
COUPANG_ACCESS_KEY=...
COUPANG_SECRET_KEY=...
DOMEGGOOK_API_KEY=...
```

주의사항:

- 실제 `.env`는 Git에 올리지 않습니다.
- 각 수집기 폴더 안에 별도 `.env`를 만들지 않습니다.
- `.env.example`에는 실제 키를 넣지 않습니다.

## 쿠팡 파트너스 수집기

쿠팡 파트너스 키워드 상품 검색 결과를 수집합니다.

주요 파일:

| 용도 | 파일 |
| --- | --- |
| 키워드 목록 | `coupang_API/keywords.txt` |
| 설정 | `coupang_API/config.yaml` |
| 원본 응답 | `coupang_API/data/raw/` |
| 가공 결과 | `coupang_API/data/processed/` |
| 실행 요약 | `coupang_API/data/summaries/` |
| 재시작 체크포인트 | `coupang_API/data/checkpoints/` |

실행:

```powershell
python -m coupang_API
```

키워드는 `coupang_API/keywords.txt`에 한 줄에 하나씩 입력합니다. 빈 줄과 `#`으로 시작하는 줄은 무시합니다.

## 도매꾹/도매매 수집기

도매꾹(`market=dome`)과 도매매(`market=supply`) 상품의 가격, 재고, 판매상태, 배송, 판매자 정보를 매일 파일로 누적 저장합니다.

도매꾹/도매매는 과거 가격/재고 이력을 API로 제공하지 않으므로, 수집기가 매일 키워드 검색으로 상품번호를 발견하고 한 번 발견한 상품은 계속 상세조회합니다.

주요 파일:

| 용도 | 파일 |
| --- | --- |
| 검색 키워드 목록 | `domeggook_API/keywords.txt` |
| 설정 | `domeggook_API/config.yaml` |
| 추적 상품번호 마스터 | `domeggook_API/tracked_products.json` |
| 추적 상품번호 예시 | `domeggook_API/tracked_products.example.json` |
| 일별 상품 상세 snapshot | `domeggook_API/output/product-snapshots-YYYY-MM-DD.json` |
| 일별 검색순위 이력 | `domeggook_API/output/search-ranks-YYYY-MM-DD.json` |
| 실행 로그 | `domeggook_API/logs/collector.log` |

전체 수집:

```powershell
python -m domeggook_API.main
```

소량 테스트:

```powershell
python -m domeggook_API.main --limit 1
```

파일 저장 없이 API 호출 흐름만 확인:

```powershell
python -m domeggook_API.main --limit 1 --dry-run
```

단계별 실행:

```powershell
python -m domeggook_API.discover_products
python -m domeggook_API.collect_product_details
```

도매꾹 수집기의 상세 운영 문서는 `domeggook_API/README.md`를 확인합니다.

## `--limit` 옵션

`--limit`은 운영용이 아니라 테스트용입니다.

```powershell
python -m domeggook_API.main --limit 1
```

도매꾹 수집기 기준 동작:

- 발견 단계에서 키워드 1개만 검색
- 상세 단계에서 추적 상품 1개만 상세조회

실제 매일 수집은 `--limit` 없이 실행합니다.

## 테스트

전체 테스트:

```powershell
pytest
```

도매꾹 수집기 테스트만:

```powershell
pytest domeggook_API/tests
```

쿠팡 수집기 테스트만:

```powershell
pytest coupang_API/tests
```

테스트는 mock/fixture 기반이며, 실제 외부 API를 호출하지 않습니다.

## 서버에서 매일 자동 실행

`python -m ...` 명령은 한 번 실행하고 종료합니다. 매일 자동 수집하려면 Linux cron 같은 스케줄러를 따로 설정해야 합니다.

도매꾹/도매매 매일 06:10 실행 예시:

```cron
10 6 * * * cd /home/ubuntu/product-data-collector && /home/ubuntu/product-data-collector/.venv/bin/python -m domeggook_API.main >> domeggook_API/logs/cron.log 2>&1
```

쿠팡 매일 06:30 실행 예시:

```cron
30 6 * * * cd /home/ubuntu/product-data-collector && /home/ubuntu/product-data-collector/.venv/bin/python -m coupang_API >> coupang_API/data/cron.log 2>&1
```

서버 배포 시 확인할 것:

- 서버에 `.env` 파일이 있는지
- `.env`에 필요한 API 키가 들어 있는지
- `pip install -r requirements.txt`를 실행했는지
- cron에서 사용하는 Python 경로가 맞는지
- output/log 디렉터리에 쓰기 권한이 있는지

## Git 관리

Git에 올리지 않는 런타임 파일:

```gitignore
.env
coupang_API/data/
domeggook_API/tracked_products.json
domeggook_API/output/
domeggook_API/logs/
```

브랜치 작업은 `main` 기준으로 PR을 올리는 방식을 기본으로 합니다.

```powershell
git switch main
git pull --ff-only origin main
git switch -c 작업브랜치명
```

작업 후:

```powershell
pytest
git add .
git commit -m "변경 내용"
git push -u origin 작업브랜치명
gh pr create --base main --head 작업브랜치명
```

## 향후 계획

현재는 파일 기반 수집입니다. 도매꾹/도매매 수집기는 향후 DB 전환을 고려해 상품 마스터와 일별 snapshot 저장 로직을 분리했습니다.

예상 테이블:

- `tracked_products`
- `product_snapshots`
- `search_ranks`

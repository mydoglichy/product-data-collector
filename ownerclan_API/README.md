# 오너클랜 수집기

오너클랜 Seller GraphQL API에서 최하위 카테고리별 상품을 순회하고, 증분 변경분을 PostgreSQL에 저장합니다.

## 실행 흐름

기본 실행은 카테고리 전체 수집 후 증분 수집을 이어서 실행합니다.

```powershell
python -m ownerclan_API
python -m ownerclan_API --refresh-categories
python -m ownerclan_API --category-workers 8
python -m ownerclan_API --refresh-categories --limit 1 --dry-run
```

일일 운영에서는 공통 wrapper를 사용합니다.

```powershell
python scripts\run_daily_collector.py --platform ownerclan
```

`category_workers`가 2 이상이면 여러 최하위 카테고리를 병렬 처리합니다. 모든 worker는 하나의 공유 `RateLimiter`를 사용하므로 worker 수를 늘려도 전체 API 호출 간격은 `config/config.yaml`의 `request.interval_seconds` 기준으로 제한됩니다.

상세한 순회 방식은 루트 운영 문서의 [COLLECTION_METHODS.md](../docs/operations/COLLECTION_METHODS.md#오너클랜)를 봅니다. 요약하면 최하위 카테고리 캐시를 만들고, 각 카테고리의 `allItems(first=500, after=cursor)` 페이지를 끝까지 순회합니다. 병렬 진행상태는 `category-collection-progress.json`에 완료 카테고리와 카테고리별 cursor를 저장해 재시작 시 이어갑니다.

## 설정과 제한

`config/config.yaml`의 현재 기준:

- category page size: `500`
- API 호출 간격: `0.4`초, 전체 약 `150 RPM`
- request timeout: `15`초
- request retry: `2`회
- `Retry-After` 최대 대기 반영: `300`초
- raw sample limit: `100` per platform

`scripts\run_daily_collector.py --platform ownerclan`의 기본 운영값은 worker `8`, rate-limit 재시작 대기 `90`초, 일반 실패 재시작 대기 `60`초, 일반 실패 최대 재시작 `50`회입니다.

## 상태 파일

- `data/state/categories.json`: 최하위 카테고리 캐시
- `data/state/category-collection-state.json`: 단일 worker 카테고리 수집 재개 위치
- `data/state/category-collection-progress.json`: 병렬 worker 카테고리 수집 재개 위치
- `data/state/incremental-state.json`: 증분 수집의 마지막 안전 성공 시각

카테고리 수집이 정상 완료되면 `category-collection-state.json`과 `category-collection-progress.json`을 삭제합니다.

## 데이터 매핑

플랫폼 고유 필드 매핑은 [DATA_SCHEMA.md](DATA_SCHEMA.md)를 봅니다. 공통 테이블 저장 규칙은 루트의 [DB_FIELD_SPEC.md](../docs/schema/DB_FIELD_SPEC.md)와 [DATA_STORAGE_SCHEMA.md](../docs/schema/DATA_STORAGE_SCHEMA.md)가 기준입니다.

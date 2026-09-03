# 도매꾹/도매매 수집기

도매꾹/도매매 Open API에서 상품 ID를 발견하고 상세 상품 snapshot을 PostgreSQL에 저장합니다.

## 실행 흐름

`python -m domeggook_API`의 기본 `full` 모드는 discovery를 먼저 실행한 뒤 상세 수집을 실행합니다. `--mode daily`는 운영용 흐름으로, PostgreSQL `product_discovery_targets`에 이미 저장된 상품 ID의 상세 수집을 먼저 끝내고 남은 API 예산으로 최근 등록 상품 ID를 얕게 보강합니다.

```powershell
python -m domeggook_API
python -m domeggook_API --mode daily
python -m domeggook_API --limit 1 --dry-run
```

일일 운영에서는 공통 wrapper를 사용합니다.

```powershell
python scripts\run_daily_collector.py --platform domeggook
```

상세한 순회 방식은 루트 운영 문서의 [COLLECTION_METHODS.md](../docs/operations/COLLECTION_METHODS.md#도매꾹도매매)를 봅니다. 요약하면 최하위 카테고리마다 `dome`, `supply` market과 설정된 sort 조합을 만들고 list page를 끝까지 순회해 상품 ID를 `product_discovery_targets`에 저장합니다. daily 모드는 기존 ID의 상세 수집을 먼저 수행하고, 예산이 남을 때만 `recent=da`를 position당 기본 1페이지씩 얕게 확인합니다.

## 설정과 제한

`config/config.yaml`의 현재 기준:

- discovery 대상 market: `dome`, `supply`
- 순위 저장 대상 sort: `ha`, `rd`
- 최근 상품 보강 sort: `da`
- 상세 batch size: `100`
- raw sample limit: `3`
- API 예산: 분당 `120`, 시간당 `9000`, 일당 `14000`

`--max-api-calls`는 실행 1회의 API 호출 상한을 덮어씁니다. `--max-runtime-hours`는 지정 시간에 도달하면 상태 파일을 저장하고 정상 중단합니다.

## 상태 파일

- `data/state/categories.json`: 최하위 카테고리 캐시
- `data/state/discovery-state.json`: full discovery 재개 위치
- `data/state/detail-collection-state.json`: 상세 수집 재개 위치
- `data/state/recent-discovery-state.json`: daily 모드의 최근 상품 보강 재개 위치

상세 수집 대상 상품 ID는 JSON 파일이 아니라 PostgreSQL `product_discovery_targets`에서 읽습니다. 상태 파일은 상품 데이터 저장소가 아니라 재시작용 checkpoint입니다.

## 데이터 매핑

플랫폼 고유 필드 매핑은 [DATA_SCHEMA.md](DATA_SCHEMA.md)를 봅니다. 공통 테이블/저장 규칙은 루트의 [DB_FIELD_SPEC.md](../docs/schema/DB_FIELD_SPEC.md)와 [DATA_STORAGE_SCHEMA.md](../docs/schema/DATA_STORAGE_SCHEMA.md)가 기준입니다.

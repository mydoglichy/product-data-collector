# 쿠팡 수집기

쿠팡 파트너스 상품 검색 API 결과를 수집해 PostgreSQL에 저장합니다.

## 실행 흐름

```powershell
python -m coupang_API
python -m coupang_API --dry-run
python scripts\run_daily_collector.py --platform coupang
python scripts\run_daily_collector.py --platform coupang --dry-run
```

`config/keywords.txt`의 keyword를 순서대로 조회하고, keyword별 성공 여부를 checkpoint에 기록합니다.
`--dry-run`은 실제 API 호출과 파싱까지 수행하지만 checkpoint, raw sample, 상품 snapshot을 저장하지 않습니다.

상세한 순회 방식은 루트 운영 문서의 [COLLECTION_METHODS.md](../docs/operations/COLLECTION_METHODS.md#쿠팡)를 봅니다. 요약하면 단일 worker가 keyword 1개당 Search API를 1회 호출하고, 성공 keyword를 `product_search_checkpoint.json`에 기록합니다. 현재 설정은 rolling window 기준 40 RPM이며, HTTP 200이어도 JSON `rCode` 제한을 검사합니다.

## 설정과 제한

`config/config.yaml`의 현재 기준:

- requests per minute: `40`
- keyword당 검색 limit: `10`
- image size: `512x512`
- raw sample limit: `3`

쿠팡 파트너스는 HTTP 200이어도 JSON `rCode`로 제한을 반환할 수 있으므로 client가 응답 본문을 함께 검사합니다. 로컬 관측 내용은 [COUPANG_PARTNERS_RATE_LIMIT_REPORT.md](../tests/probes/COUPANG_PARTNERS_RATE_LIMIT_REPORT.md)에 따로 둡니다.

## 상태 파일

- `data/state/product_search_checkpoint.json`: 완료 keyword checkpoint

모든 keyword가 성공하면 checkpoint 파일은 삭제됩니다. 상품 데이터는 JSON 파일로 만들지 않고 PostgreSQL에 저장합니다.

## 데이터 매핑

플랫폼 고유 필드 매핑은 [DATA_SCHEMA.md](DATA_SCHEMA.md)를 봅니다. 공통 테이블/저장 규칙은 루트의 [DB_FIELD_SPEC.md](../docs/schema/DB_FIELD_SPEC.md)와 [DATA_STORAGE_SCHEMA.md](../docs/schema/DATA_STORAGE_SCHEMA.md)가 기준입니다.

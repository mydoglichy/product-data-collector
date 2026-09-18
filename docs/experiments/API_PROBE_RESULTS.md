# API 실험 결과

이 문서는 운영 판단에 영향을 준 probe와 실험 결과만 보관합니다. 실행 절차는 [운영 런북](../operations/RUNBOOK.md), 실제 운영 DB 구조는 [DB 스키마](../schema/DB_SCHEMA.md)를 기준으로 봅니다.

## 오너클랜 호출 제한

테스트 조건:

- 테스트일: 2026-08-30
- 환경: production
- 대상: Seller GraphQL API
- 요청: `allItems(first: 1)`
- 저장: 없음
- 스크립트: `tests/probes/ownerclan_rate_probe.py`

분당 호출 테스트 결과:

| 목표 RPM | 관측 RPM | 결과 |
| ---: | ---: | --- |
| 60 | 60.84 | 61/61 성공, rate limit 없음 |
| 120 | 120.78 | 121/121 성공, rate limit 없음 |
| 180 | 180.58 | 181/181 성공, rate limit 없음 |
| 210 | 203.63 | 204/204 성공, rate limit 없음 |
| 240 | 32.99 | rate limit 없음, `ReadTimeout` 2회 발생 |

1시간 지속 테스트:

| 목표 RPM | 지속 시간 | 시도 | 성공 | 오류 | 결과 |
| ---: | ---: | ---: | ---: | ---: | --- |
| 180 | 3600초 | 10571 | 10520 | 51 | rate limit 없음, 502/ConnectionError 발생 |

추가 백필 중 관측:

- 200 RPM probe는 884회 성공 후 885번째 호출에서 GraphQL `Too many requests.` 발생
- 경과 278.813초, observed RPM 190.4
- 직후 150 RPM probe에서는 초반부터 ReadTimeout과 `502 + Retry-After: 60`이 연속 발생

운영 판단:

- 200 RPM은 위험합니다.
- 240 RPM에서는 rate limit보다 응답 지연/타임아웃이 먼저 발생했습니다.
- 현재 운영 수집 설정은 전역 limiter 기준 약 150 RPM입니다.
- 권장값은 `request.interval_seconds: 0.4`이며, `Retry-After`, 429, GraphQL `Too many requests`는 90초 이상 백오프로 처리합니다.

재테스트 명령:

```powershell
python tests\probes\ownerclan_rate_probe.py --rpm 150 --duration 60
```

## 오너클랜 백필 처리량

작성일: 2026-09-03

로컬 검증에서는 PostgreSQL 저장까지 확인했고, 서버 배포 시에는 전체 상품 백필 가능 여부와 호출 한도 안정성이 핵심이었습니다.

마지막 확인 시점 기준:

- `products` 오너클랜 총계: 579,219개
- 첫 대형 단일 수집 저장 상품: 276,048개
- `allItems` 호출 시도: 689회
- 성공 호출: 657회
- ReadTimeout: 30회
- 429: 0회

4 worker 실행 중 최근 15분 샘플:

- 저장 상품: 148,011개
- 처리 속도: 약 9,867개/min
- 시간당 환산: 약 592,000개/hour
- 1,000만개 단순 투영: 약 16.9시간
- 429: 0
- 최근 API success: 525
- 최근 timeout: 24

`page_size=500` 기준 전체 상품 1,000만 개 백필은 최소 20,000 successful page calls가 필요합니다. timeout, retry, 카테고리 마지막 페이지, 빈 페이지를 감안하면 운영상 21,000~25,000 API attempts 정도를 예상합니다.

병렬 worker + 전역 limiter 변경 후 판단:

- worker는 여러 카테고리를 동시에 맡지만 API 호출 직전에는 같은 전역 limiter를 통과합니다.
- `interval_seconds=0.4` 기준 총합 최대 150 RPM을 넘지 않습니다.
- 실효 처리량은 보수적으로 500,000~1,500,000개/hour 범위로 봅니다.
- 1,000만 개 백필 예상은 약 7~20시간입니다.

## 오너클랜 `itemHistories`

검증일: 2026-09-09

대상 API: Ownerclan Seller GraphQL `itemHistories`

결론:

`itemHistories`는 오너클랜 전체 상품을 매일 다시 훑지 않고, 변경된 상품 키만 찾는 용도로 충분히 사용할 수 있습니다.

확인된 동작:

- `itemHistories(itemKey: "...")`로 특정 상품 이력 조회 가능
- `itemHistories(dateFrom, dateTo)`로 전체 상품 변경 이력 조회 가능
- `kind`로 변경 종류 필터 가능
- `after/endCursor/hasNextPage` cursor pagination 정상 동작
- 한 번의 `dateFrom/dateTo` 범위는 최대 7일
- `first`는 1000 초과 요청 시에도 1000개까지만 반환
- 90일 전 1일 구간도 조회됨

최근 24시간 전체 `itemHistories` 조회 결과:

| 항목 | 값 |
| --- | ---: |
| 조회 범위 | 2026-09-08 16:26:27 ~ 2026-09-09 16:26:27 KST |
| 페이지 수 | 164 |
| 이벤트 수 | 163,663 |
| 고유 `itemKey` 수 | 105,445 |
| 오류 | 0 |

대략적인 일일 호출량:

| 단계 | 추정 호출 수 |
| --- | ---: |
| `itemHistories(first: 1000)` | 약 164 calls |
| `items(keys: [...])`, batch 100 기준 | 약 1,055 calls |
| 합계 | 약 1,219 calls/day |

30개 상품 90일 추세 probe:

| 항목 | 값 |
| --- | ---: |
| 샘플 상품 수 | 30 |
| 조회 기간 | 2026-06-11 16:40:27 ~ 2026-09-09 16:40:27 KST |
| `itemHistories` 호출 수 | 390 |
| 조회 페이지 수 | 390 |
| 총 이벤트 수 | 291 |
| 이벤트 있는 상품 수 | 30 |
| 오류 | 0 |
| 총 소요시간 | 289.75초 |
| 현재 상세 `items` batch 조회 | 30/30 성공, 1.14초 |

이벤트 범주별 결과:

| 범주 | 이벤트 수 | 해당 상품 수 | 판단 |
| --- | ---: | ---: | --- |
| 가격 | 41 | 20 | before/after가 숫자로 안정적으로 들어와 추세 분석 가능 |
| 재고 수량 | 1 | 1 | 이벤트는 있으나 숫자 복원 품질은 낮음 |
| 품절/재입고/단종 | 187 | 20 | 수량보다 상태 추세 분석에 강함 |
| 배송 | 12 | 8 | 배송비/배송방식 변경 추적 가능 |
| 반품 정책 | 10 | 9 | 반품배송비/반품기준 변경 감지 가능 |
| 인증/고시/판매제한 | 5 | 4 | 상품정보고시 변경 감지 가능 |
| 상품명/상세/이미지/카테고리 등 | 35 | 다수 | 리스팅 품질 변화 감지 가능 |

값 품질:

| 항목 | 수 |
| --- | ---: |
| `valueBefore` 또는 `valueAfter`가 있는 이벤트 | 127 / 291 |
| before/after 둘 다 숫자인 이벤트 | 56 / 291 |
| 가격 이벤트 중 before/after 둘 다 숫자 | 41 / 41 |
| 재고 수량 이벤트 중 before/after 둘 다 숫자 | 0 / 1 |

권장 수집 방식:

1. 마지막 성공 시각을 sync state에 저장합니다.
2. 매일 `last_success - overlap`부터 현재까지 조회합니다.
3. `dateFrom/dateTo`는 7일 이하로 쪼갭니다.
4. 각 구간을 `first: 1000`과 cursor로 끝까지 가져옵니다.
5. 이벤트에서 나온 `itemKey`를 dedupe합니다.
6. dedupe된 key만 `items(keys: [...])`로 상세 재조회합니다.
7. 기존 저장 함수로 master와 snapshot diff history를 저장합니다.
8. 주 1회 또는 월 1회 전체 보정 수집을 별도로 둡니다.

미적용 DB 권장안:

`itemHistories` 원본 이벤트는 기존 `product_history`와 분리해서 저장하는 것이 맞습니다. 기존 `product_history`는 우리 쪽 snapshot diff 이력이고, `itemHistories`는 오너클랜이 제공하는 source event log입니다. 아래 테이블은 현재 운영 DB에 생성되어 있지 않은 권장안입니다.

```sql
CREATE TABLE ownerclan_item_histories (
    id BIGSERIAL PRIMARY KEY,
    item_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    value_before TEXT NULL,
    value_after TEXT NULL,
    event_created_at TIMESTAMPTZ NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (item_key, kind, title, value_before, value_after, event_created_at)
);
```

## 쿠팡 파트너스 호출 제한

작성 기준: 2026-09-02 KST

핵심 결론:

- 2026-08-26에는 쿠팡 파트너스 Search API로 100개 키워드를 모두 성공 조회했고, 총 994개 상품 row를 만들었습니다.
- 당시 실제 평균 호출 속도는 약 0.805 req/sec, 48.32 RPM이었습니다.
- 2026-09-02 제한 테스트에서는 Search API를 약 2.0 req/sec, 120 RPM 속도로 호출했고, 52번째 호출에서 HTTP 200 + `rCode=403`이 발생했습니다.
- 응답 메시지는 `검색 API의 시간당 사용 횟수 초과`였고, 재시도 가능 시각으로 2026-09-03 17:46:28 이후를 반환했습니다.
- 제한 상태에서 Best Category API를 1회 호출했을 때도 HTTP 200 + `rCode=403`이 반환되어 Search API와 Best Category API는 같은 상품 검색 계열 쿼터를 공유하는 것으로 보입니다.

근거 파일:

| 구분 | 파일 | 의미 |
| --- | --- | --- |
| 과거 정상 수집 상품 파일 | `coupang_API/data/processed/coupang_2026_0826_2101_products.jsonl` | 2026-08-26 실행 결과 상품 row 994개 |
| 과거 정상 수집 요약 | `coupang_API/data/summaries/coupang_2026_0826_2101_summary.json` | 100개 키워드 성공, 실패 0개 |
| Search 제한 테스트 로그 | `tests/probes/logs/coupang_rate_probe_20260902_174602.jsonl` | 601회 호출, 52번째부터 제한 관측 |
| Best Category 제한 확인 로그 | `tests/probes/logs/coupang_rate_probe_best-category_20260902_210715.jsonl` | 제한 상태에서 1회 호출, 즉시 `rCode=403` |

2026-09-02 Search 제한 테스트:

| 항목 | 값 |
| --- | ---: |
| 총 호출 수 | 601회 |
| 성공 수 | 204회 |
| 실패 수 | 397회 |
| HTTP 상태코드 분포 | `200`: 601회 |
| rCode 분포 | `0`: 204회, `403`: 397회 |
| 전체 테스트 실제 평균 | 120.2 RPM |
| 최초 제한 attempt | 52번째 |
| 제한 발생 전 성공 수 | 51회 |
| 최초 제한 HTTP 상태코드 | 200 |
| 최초 제한 rCode | `403` |
| Retry-After 헤더 | 없음 |

운영 판단:

- Search API와 Best Category API를 같은 쿼터로 묶어서 계산합니다.
- HTTP 상태코드와 JSON `rCode/rMessage`를 함께 검사합니다.
- `rCode=403`, `rCode=429`, 시간당 사용 횟수 초과 메시지는 즉시 중단합니다.
- 제한 상태 재확인을 반복하지 않습니다.
- 재개는 쿠팡 응답의 재시도 가능 시각 이후로 미룹니다.
- 현재 운영 속도는 저장소 설정의 40 RPM을 사용하되, 제한 메시지가 재발하면 계정 상태 기준으로 더 낮춰야 합니다.

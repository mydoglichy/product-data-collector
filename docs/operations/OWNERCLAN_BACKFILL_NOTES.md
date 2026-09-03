# Ownerclan Backfill Notes

작성일: 2026-09-03

## 현재 목적

오너클랜 Seller GraphQL API에서 전체 상품을 카테고리 기준으로 백필한다. 로컬 검증에서는 PostgreSQL 저장까지 확인했고, 서버 배포 시에는 전체 상품 백필 가능 여부와 호출 한도 안정성이 핵심이다.

## DB 저장 현황

마지막 확인 시점 기준:

- `products` 오너클랜 총계: 579,219개
- 첫 대형 단일 수집:
  - 저장 상품: 276,048개
  - `allItems` 호출 시도: 689회
  - 성공 호출: 657회
  - ReadTimeout: 30회
  - 429: 0회
- 이후 병렬 수집 포함 전체 정확한 호출 총합은 로그를 최근 1000줄 유지로 바꿔서 더 이상 전체 로그만으로 복원할 수 없다.

## 호출 수 산정

`page_size=500` 기준:

- 1,000만 상품 / 500개 = 최소 20,000 successful page calls
- timeout, retry, 카테고리 마지막 페이지, 빈 페이지를 감안하면 운영상 21,000~25,000 API attempts 정도를 예상한다.

`page_size=1000` 기준 최소 호출 수는 10,000회지만, 로컬 테스트에서 1000개 payload가 느린 응답과 ReadTimeout을 유발했다.

## 현재 백필 설정

`ownerclan_API/config/config.yaml`

```yaml
incremental:
  page_size: 500

request:
  interval_seconds: 0.4
  timeout_seconds: 15
  max_retries: 2
  retry_after_max_seconds: 300
```

## 병렬 수집

실행 명령:

```powershell
python -m ownerclan_API --category-workers 8 --failure-retry-seconds 60 --max-failure-restarts 50
```

동작:

- 서로 다른 카테고리를 여러 worker가 동시에 수집한다.
- 같은 카테고리 안에서는 cursor 때문에 페이지 순서를 유지한다.
- DB 저장은 백그라운드 저장 worker로 넘겨서 다음 API 요청과 겹치게 했다.
- 진행상태는 `ownerclan_API/data/state/category-collection-progress.json`에 저장한다.
- 재시작 시 progress 파일 기준으로 완료 카테고리는 건너뛰고 진행 중 카테고리는 cursor부터 이어간다.

## 병렬 수집 실측

4 worker 실행 중 최근 15분 샘플:

- 저장 상품: 148,011개
- 처리 속도: 약 9,867개/min
- 시간당 환산: 약 592,000개/hour
- 1,000만개 단순 투영: 약 16.9시간
- 429: 0
- 최근 API success: 525
- 최근 timeout: 24

이 페이스가 유지되면 하루 안 백필 가능하다. 다만 서버/gateway 상태, timeout, 카테고리 마지막 페이지 비율에 따라 17~24시간 범위로 보는 것이 현실적이다.

## 호출 한도 probe

probe는 데이터 저장 없이 `allItems(first: 1)`만 호출한다.

```powershell
python tests\probes\ownerclan_rate_probe.py --rpm 200 --duration 7200 --timeout 5 --quiet
```

200 rpm 결과:

- 884회 성공
- 885번째 호출에서 GraphQL `Too many requests.`
- 경과: 278.813초
- observed RPM: 190.4

이 결과만으로 일일 한도인지 분당/슬라이딩 윈도우 한도인지는 확정할 수 없다. 다만 200 rpm은 위험하다.

직후 150 rpm probe에서는 초반부터 ReadTimeout이 연속 발생했고, 이후 `502` + `Retry-After: 60`이 대량 발생했다. 이는 200 rpm probe 직후 서버/gateway가 백오프를 요구한 상태로 판단한다.

이전 기록:

- 180 rpm 1시간 probe에서 10,571회 호출, rate limit 없음
- 210 rpm 1분 probe에서 rate limit 없음
- 240 rpm probe에서 rate limit보다 ReadTimeout이 먼저 발생

## 백오프 정책

운영 클라이언트 반영 사항:

- `Retry-After: 60` 같은 명시 백오프 신호가 오면 30초 여유를 붙여 최소 90초 쉰다.
- 429에 `Retry-After`가 없어도 최소 90초 쉰다.
- GraphQL `Too many requests`는 최소 90초 쉰다.
- ReadTimeout은 1회는 짧은 재시도, 같은 요청에서 2회째부터 90초 백오프한다.

probe 반영 사항:

- `502/503/504`와 `Retry-After`가 같이 오면 rate-limit/backoff 계열로 처리한다.
- timeout 등 비-rate-limit 에러가 너무 많이 쌓이면 중단한다.
- timeout으로 스케줄이 밀려도 catch-up burst를 보내지 않는다.

## 운영 판단

서버 배포에서 처음 권장:

- `category_workers=8`
- `page_size=500`
- 전체 합산 목표 RPM은 120~150부터 시작
- 429, `Too many requests`, `502 + Retry-After`가 보이면 즉시 90초 이상 쉬고 RPM을 낮춘다.

서버 자원이 충분하고 429/Retry-After가 없으면 worker 수를 8까지 사용할 수 있다. 단, 호출 한도보다 Ownerclan 응답 지연과 PostgreSQL write throughput이 먼저 병목이 될 수 있다.
## 2026-09-03 변경: 병렬 worker + 전역 150 RPM limiter

### 변경 목적

기존 병렬 수집은 worker마다 `RateLimiter`가 따로 생성되었다. 예를 들어 `category_workers=4`, `interval_seconds=1.2`이면 worker별 50 RPM이 적용되어 전체로는 최대 약 200 RPM까지 올라갈 수 있었다.

이번 변경은 모든 병렬 worker가 하나의 공유 `RateLimiter`를 사용하도록 바꿨다. 따라서 worker 수를 늘려도 전체 API 호출은 공유 limiter가 직렬화하며, `interval_seconds=0.4` 기준 총합 최대 150 RPM을 넘지 않는다.

### 현재 운영 설정

`ownerclan_API/config/config.yaml`

```yaml
incremental:
  page_size: 500

request:
  interval_seconds: 0.4
  timeout_seconds: 15
  max_retries: 2
  retry_after_max_seconds: 300
```

권장 실행:

```powershell
python -m ownerclan_API --category-workers 8 --failure-retry-seconds 60 --max-failure-restarts 50
```

worker는 여러 카테고리를 동시에 맡지만 API 호출 직전에는 같은 전역 limiter를 통과한다. 한 worker가 timeout이나 DB 저장으로 막혀도 다른 worker가 다음 카테고리 작업을 이어갈 수 있고, 동시에 총합 RPM은 150 이하로 제한된다.

### 처리량 추정

`page_size=500` 기준 150 RPM의 이론상 최대 처리량:

- 분당 최대 상품 수: 150 calls * 500 items = 75,000개/min
- 시간당 최대 상품 수: 4,500,000개/hour

다만 이 값은 모든 페이지가 500개를 꽉 채우고, timeout/retry/빈 페이지/DB 저장 지연이 전혀 없을 때의 상한이다. 실제 운영 추정은 아래처럼 보는 것이 현실적이다.

- 안정적 수집 목표: 120~150 RPM 이하
- 실효 처리량 보수 추정: 500,000~1,500,000개/hour
- 기존 4 worker 실측: 약 592,000개/hour
- 1,000만 개 백필 예상: 약 7~20시간

오너클랜 응답 지연이 커지거나 `ReadTimeout`, `502/503/504`, `Retry-After`, GraphQL `Too many requests`가 늘면 worker 수보다 전역 RPM을 먼저 낮추는 것이 맞다. `page_size=100`은 호출 수가 5배로 증가하므로 기본값으로 쓰지 않는다. `page_size=500`에서 payload timeout이 반복될 때만 `300` 또는 `250`으로 낮춰 비교 테스트한다.

### 실패 카운트 수정

기존 병렬 수집은 실패가 발생해도 마지막에 `failureCount`를 0으로 덮어써 상위 `main.run()`이 실패 상태를 알기 어려웠다.

변경 후 동작:

- rate limit 계열 실패: `failureCount`와 `rateLimitFailureCount`를 올리고 전체 worker 소비를 멈춘다. 상위 실행 루프가 지정된 시간만큼 쉰 뒤 progress cursor 기준으로 재시작한다.
- 일반 네트워크 실패: 같은 카테고리를 최대 3회까지 내부 재시도한다.
- 같은 카테고리가 3회 연속 실패: `failureCount`를 올리고 progress 파일을 보존한다.
- 모든 카테고리가 최종 성공한 경우에만 progress/state 파일을 정리한다.

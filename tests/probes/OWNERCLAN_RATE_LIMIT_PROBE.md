# 오너클랜 API 호출 제한 테스트

## 테스트 조건

- 테스트일: 2026-08-30
- 환경: production
- 대상: Seller GraphQL API
- 요청: `allItems(first: 1)`
- 저장: 없음
- 스크립트: `tests/probes/ownerclan_rate_probe.py`

## 분당 호출 테스트 결과

| 목표 RPM | 관측 RPM | 결과 |
| ---: | ---: | --- |
| 60 | 60.84 | 61/61 성공, rate limit 없음 |
| 120 | 120.78 | 121/121 성공, rate limit 없음 |
| 180 | 180.58 | 181/181 성공, rate limit 없음 |
| 210 | 203.63 | 204/204 성공, rate limit 없음 |
| 240 | 32.99 | rate limit 없음, `ReadTimeout` 2회 발생 |

## 1시간 지속 테스트

| 목표 RPM | 지속 시간 | 시도 | 성공 | 오류 | 결과 |
| ---: | ---: | ---: | ---: | ---: | --- |
| 180 | 3600초 | 10571 | 10520 | 51 | rate limit 없음, 502/ConnectionError 발생 |

## 판단

- 분당 200회 안팎까지는 429 또는 GraphQL `Too many requests`가 확인되지 않았다.
- 180 RPM 1시간 지속 테스트에서도 rate limit은 확인되지 않았다.
- 240 RPM에서는 rate limit보다 응답 지연/타임아웃이 먼저 발생했다.
- 180 RPM 1시간 지속 테스트는 성공했지만 이후 더 높은 속도에서 timeout과 gateway backoff가 먼저 관측됐다.
- 현재 운영 수집 설정은 전역 limiter 기준 약 150 RPM이다.
- 현재 권장값: `request.interval_seconds: 0.4`

## 재테스트 명령

```powershell
python tests\probes\ownerclan_rate_probe.py --rpm 150 --duration 60
```

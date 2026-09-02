# 도매꾹/도매매 수집기

도매꾹/도매매 Open API에서 상품을 발견하고 상세 수집 결과를 PostgreSQL에 저장한다.

## 구조

- `api/`: Open API client와 rate limiter
- `workflows/`: discovery, 상세 수집, 통합 실행 흐름
- `services/`: 카테고리 처리, 응답 파싱, 시간 유틸, 로깅 설정
- `persistence/`: tracked products, state, lock 저장
- `config/`: `config.yaml`, `keywords.txt`, 설정 로더
- `tests/`: 도매꾹/도매매 수집기 테스트

## 상태 파일

- `config/keywords.txt`: discovery 입력
- `data/state/categories.json`: 최하위 카테고리 캐시
- PostgreSQL `product_discovery_targets`: 상세 수집 대상 상품번호
- `data/state/discovery-state.json`: discovery 재개 위치
- `data/state/detail-collection-state.json`: 상세 수집 재개 위치

## 실행

```powershell
python -m domeggook_API
```

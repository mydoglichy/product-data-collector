# 쿠팡 수집기

쿠팡 파트너스 상품 검색 API 결과를 수집해 PostgreSQL에 저장한다.

## 구조

- `api/`: HMAC 인증, Partners API client, rate limiter
- `workflows/`: keyword 검색 수집 실행 흐름
- `services/`: 상품 응답 파싱과 정규화
- `persistence/`: 중단/재시작용 checkpoint와 중복 제거
- `config/`: `config.yaml`, `keywords.txt`, 설정 로더
- `tests/`: 쿠팡 수집기 테스트

## 상태 파일

- `data/state/product_search_checkpoint.json`: 완료 keyword checkpoint
- `config/keywords.txt`: 검색 keyword 입력

모든 keyword가 성공하면 checkpoint 파일은 삭제된다.

## 실행

```powershell
python -m coupang_API
```

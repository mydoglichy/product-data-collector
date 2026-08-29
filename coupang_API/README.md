# 쿠팡 수집기

쿠팡 파트너스 상품 검색 API 결과를 수집해 PostgreSQL에 저장한다.

## 저장 방식

수집기는 더 이상 상품 결과 JSONL, raw JSON, summary JSON 파일을 만들지 않는다. keyword 처리 중단/재시작을 위한 checkpoint만 파일로 유지한다.

저장 테이블:

- `products`: 상품 master와 최신 정규화 payload
- `product_prices`: `productPrice` 가격 snapshot
- `product_inventory`: 검색 API에 재고가 없어 보통 `NULL`
- `product_shipping_fees`: `isFreeShipping` 기반 배송 정보
- `product_change_history`: 변경 감지 이력
- `product_raw_samples`: raw 검색 응답 샘플, 저장 호출당 최대 3개 상품

## 실행 상태 파일

- `keywords.txt`: 검색 keyword 입력
- `data/state/product_search_checkpoint.json`: 완료 keyword checkpoint

모든 keyword가 성공하면 checkpoint 파일은 삭제된다.

## 실행

```powershell
python -m coupang_API
```

# 오너클랜 수집기

오너클랜 Seller GraphQL API에서 상품을 발견하고 상세/증분 수집 결과를 PostgreSQL에 저장한다.

## 저장 방식

수집기는 더 이상 product snapshot, raw sample, search rank, latest cache, product history, summary, collection run JSON 파일을 만들지 않는다.

저장 테이블:

- `products`: 상품 master와 최신 정규화 payload
- `product_prices`: 공급가/고정가 snapshot
- `product_inventory`: 옵션 수량 합산 재고 snapshot
- `product_shipping_fees`: 배송비 snapshot
- `product_change_history`: 변경 감지 이력
- `product_raw_samples`: raw 샘플, 저장 호출당 최대 3개 상품
- `product_search_ranks`: keyword discovery 순위 이력

## 실행 상태 파일

- `keywords.txt`: discovery keyword 입력
- `data/state/tracked_products.json`: 상세 수집 대상 상품
- `data/state/incremental-state.json`: 증분 수집 기준 시각

## 실행

```powershell
python -m ownerclan_API.main
python -m ownerclan_API.sync_incremental
```

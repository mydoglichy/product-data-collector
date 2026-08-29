# 도매꾹/도매매 수집기

도매꾹/도매매 Open API에서 상품을 발견하고 상세 수집 결과를 PostgreSQL에 저장한다.

## 저장 방식

수집기는 더 이상 product snapshot, raw sample, search rank, latest cache, product history, summary, collection run JSON 파일을 만들지 않는다.

저장 테이블:

- `products`: 상품 master와 최신 정규화 payload
- `product_prices`: 도매꾹/도매매/판매가 가격 snapshot
- `product_inventory`: 단일 재고 snapshot
- `product_shipping_fees`: 도매꾹/도매매 배송비 snapshot
- `product_change_history`: 변경 감지 이력
- `product_raw_samples`: raw 샘플, 저장 호출당 최대 3개 상품
- `product_search_ranks`: 카테고리/마켓/정렬별 discovery 순위 이력

## 재고

현재 상세 API는 `qty.inventory` 단일 재고만 제공한다. 가격과 배송비처럼 도매꾹(`dome`)과 도매매(`supply`) 재고가 분리되어 내려오지 않으므로 DB도 상품 단위 재고 row 하나를 저장한다.

시장별로 달라지는 주문 제약은 inventory payload에 보존한다.

- `qty.domeMoq`
- `qty.domeLoq`
- `qty.domeUnit`
- `qty.supplyUnit`

## 실행 상태 파일

- `keywords.txt`: discovery 입력
- `data/state/categories.json`: 카테고리 캐시
- `data/state/tracked_products.json`: 상세 수집 대상 상품

## 실행

```powershell
python -m domeggook_API.main
```

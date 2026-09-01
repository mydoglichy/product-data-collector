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

### 순위 이력

- `da`는 공식적으로 상품정보 등록/수정일 최근순인 최근등록순이므로 `product_search_ranks`에 저장하지 않습니다.
- discovery는 자식 카테고리가 없는 최하위 카테고리만 대상으로 삼고, 각 카테고리/마켓/정렬 조합의 모든 리스트 페이지를 순회합니다.
- `da` 리스트 호출, 상품번호 발견, tracked 상품 병합, 상세 수집 대상 포함은 유지합니다.
- `ha`(인기상품순), `rd`(도매꾹랭킹순)만 현재 순위 분석 저장 대상입니다.
- `aa`, `ad`, `sd`, `qa`, `qd`, `se`는 가격, 신규판매자, 판매단위, 정확도 정렬이므로 현재 저장 대상이 아닙니다.
- `rank`는 전체 결과 기준 순위이며, `currentPage`와 `itemsPerPage`로 계산합니다.
- rank가 없는 데이터에는 `0`을 사용하지 않습니다.
- 순위 이력은 상품번호 단독 unique가 아니라 수집 시각, keyword, category, market, sort 조건별로 보존합니다.

## 재고

현재 상세 API는 `qty.inventory` 단일 재고만 제공한다. 가격과 배송비처럼 도매꾹(`dome`)과 도매매(`supply`) 재고가 분리되어 내려오지 않으므로 DB도 상품 단위 재고 row 하나를 저장한다.

시장별로 달라지는 주문 제약은 inventory payload에 보존한다.

- `qty.domeMoq`
- `qty.domeLoq`
- `qty.domeUnit`
- `qty.supplyUnit`

## 실행 상태 파일

- `keywords.txt`: discovery 입력
- `data/state/categories.json`: 최하위 카테고리 캐시
- `data/state/tracked_products.json`: 상세 수집 대상 상품

## 실행

```powershell
python -m domeggook_API.main
```

## 재개 상태 파일

수집기는 중복 호출을 허용하고 데이터 손실을 줄이는 방식으로 동작한다. 리스트 페이지나 상세 배치 데이터를 PostgreSQL과 `tracked_products.json`에 저장한 뒤에만 다음 시작 위치를 상태 파일에 기록한다. 같은 `runCollectedAt`으로 재개하므로 중복 호출이 발생해도 DB unique/upsert 조건으로 같은 수집 시점의 중복 row는 추가되지 않는다.

- `data/state/discovery-state.json`: 상품번호 리스트 생성 재개 지점. `categoryCode`, `market`, `reason`, `sort`, `nextPage`를 저장한다.
- `data/state/detail-collection-state.json`: 상세 수집 재개 지점. 정렬된 상품번호 목록의 `trackedListHash`, `nextIndex`, `lastCompletedProductId`를 저장한다.

전체 수집이 정상 완료되면 위 상태 파일은 삭제된다. 실패나 프로세스 중단으로 남아 있으면 다음 실행에서 해당 위치부터 재개한다. 정렬 결과가 실행 중 바뀔 수 있으므로 discovery 재개는 중복 호출을 감수하고 저장 완료 이후의 페이지부터 진행한다.

# 도매꾹/도매매 데이터 스키마

도매꾹/도매매 Open API 응답은 `parse_detail_product()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장한다.

## PostgreSQL 매핑

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `domeggook` |
| `products.external_product_id` | `productId` |
| `products.image_url` | `thumb.original` 등 이미지 후보 첫 번째 URL |
| `products.backup_image_url` | `image`, `imageInfo`, `img`, `imageUrl`, `productImage` 등 이미지 후보 두 번째 URL |
| `product_prices.market='dome'` | `prices.domeCurrentSupplyPrice` |
| `product_prices.market='supply'` | `prices.supplyCurrentSupplyPrice` |
| `product_prices.market='retail'` | `minimumRetailPrice`, `recommendedRetailPrice` |
| `product_inventory.stock_quantity` | `qty.inventory` |
| `product_shipping_fees.market='dome'` | `deli.dome.fee`, `deli.dome.tbl`, `deli.dome.type` |
| `product_shipping_fees.market='supply'` | `deli.supply.fee`, `deli.supply.tbl`, `deli.supply.type` |
| `product_raw_samples.payload` | raw 디버깅 샘플 |
| `product_search_ranks` | rank 의미가 있는 category, market, sort, 전체 결과 기준 rank |

## 순위 이력

- `da`는 공식적으로 상품정보 등록/수정일 최근순인 최근등록순이므로 `product_search_ranks`에 저장하지 않는다.
- discovery는 자식 카테고리가 없는 최하위 카테고리만 대상으로 삼고, 각 카테고리/마켓/정렬 조합의 모든 리스트 페이지를 순회한다.
- `ha`(인기상품순), `rd`(도매꾹랭킹순)처럼 실제 순위 분석에 사용하는 정렬만 저장한다.
- `aa`, `ad`, `sd`, `qa`, `qd`, `se`는 현재 프로젝트에서는 순위 이력 저장 대상이 아니다.
- `rank`는 페이지 내 순번이 아니라 전체 결과 기준 순위다. `(currentPage - 1) * itemsPerPage + 페이지 내 순번`으로 계산한다.
- rank가 없는 데이터에는 `0`을 사용하지 않는다.
- 순위 이력은 상품번호 단독 unique가 아니며 수집 시각, keyword, category, market, sort 조건별로 보존한다.

## 배송비

배송비는 도매꾹(`market='dome'`)과 도매매(`market='supply'`) row로 분리한다.

- `fee` 컬럼은 API가 단일 숫자로 준 기본 배송비만 저장한다.
- `deli.dome.tbl`, `deli.supply.tbl` 같은 수량별 조건식은 계산하지 않고 `payload.shipping_fee_raw`와 `payload.shipping_rules`에 저장한다.
- `deli.pay`는 도매꾹 부담 방식으로, `deli.supply.pay`는 도매매 부담 방식으로 저장한다.
- `deli.feeExtra.jeju`, `deli.feeExtra.islands`는 `payload.remote_area_fee`에 저장하고 기본 배송비에 합산하지 않는다.
- 도매매 배송비가 없으면 도매꾹 배송비로 `supply` row를 만들지 않는다.

실제 판매수량 기준 배송비, 개당 배송비, MOQ 배분, 마진 계산은 수집기 범위가 아니며 플랫폼 서버에서 처리한다.

## 재고

현재 상세 API는 재고를 `qty.inventory` 단일값으로 제공한다. 가격/배송비처럼 `dome`과 `supply` 재고가 따로 내려오지 않으므로 DB도 상품 단위 단일 재고 row를 저장한다.

## 재개 상태 파일

`data/state/discovery-state.json`과 `data/state/detail-collection-state.json`은 상품 데이터 저장소가 아니라 재개용 체크포인트다. 수집기는 PostgreSQL 저장과 `tracked_products.json` 저장이 성공한 뒤에만 다음 페이지 또는 다음 배치 위치를 기록한다.

- discovery 상태는 `categoryCode`, `market`, `reason`, `sort`, `nextPage`, `runCollectedAt`을 저장한다.
- 상세 수집 상태는 `trackedListHash`, `nextIndex`, `lastCompletedProductId`, `runCollectedAt`을 저장한다.
- 정상 완료되면 상태 파일은 삭제된다.

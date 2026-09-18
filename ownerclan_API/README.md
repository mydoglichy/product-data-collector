# 오너클랜 수집기

오너클랜 Seller GraphQL API에서 최하위 카테고리별 상품을 순회하고, 증분 변경분을 PostgreSQL에 저장합니다.

## 실행 흐름

기본 실행은 카테고리 전체 수집 후 증분 수집을 이어서 실행합니다.

```powershell
python -m ownerclan_API
python -m ownerclan_API --refresh-categories
python -m ownerclan_API --category-workers 8
python -m ownerclan_API --refresh-categories --limit 1 --dry-run
```

일일 운영에서는 공통 wrapper를 사용합니다.

```powershell
python scripts\run_daily_collector.py --platform ownerclan
```

`category_workers`가 2 이상이면 여러 최하위 카테고리를 병렬 처리합니다. 모든 worker는 하나의 공유 `RateLimiter`를 사용하므로 worker 수를 늘려도 전체 API 호출 간격은 `config/config.yaml`의 `request.interval_seconds` 기준으로 제한됩니다.

상세한 순회 방식은 [운영 런북](../docs/operations/RUNBOOK.md#오너클랜)을 봅니다. 요약하면 최하위 카테고리 캐시를 만들고, 각 카테고리의 `allItems(first=500, after=cursor)` 페이지를 끝까지 순회합니다. 병렬 진행상태는 `category-collection-progress.json`에 완료 카테고리와 카테고리별 cursor를 저장해 재시작 시 이어갑니다.

## 설정과 제한

`config/config.yaml`의 현재 기준:

- category page size: `500`
- API 호출 간격: `0.4`초, 전체 약 `150 RPM`
- request timeout: `15`초
- request retry: `2`회
- `Retry-After` 최대 대기 반영: `300`초
- raw sample limit: 플랫폼별 최대 `100`개

`scripts\run_daily_collector.py --platform ownerclan`의 기본 운영값은 worker `8`, rate-limit 재시작 대기 `90`초, 일반 실패 재시작 대기 `60`초, 일반 실패 최대 재시작 `50`회입니다.

## 상태 파일

- `data/state/categories.json`: 최하위 카테고리 캐시
- `data/state/category-collection-state.json`: 단일 worker 카테고리 수집 재개 위치
- `data/state/category-collection-progress.json`: 병렬 worker 카테고리 수집 재개 위치
- `data/state/incremental-state.json`: 증분 수집의 마지막 안전 성공 시각

카테고리 수집이 정상 완료되면 `category-collection-state.json`과 `category-collection-progress.json`을 삭제합니다.

## 데이터 매핑

오너클랜 Seller GraphQL API 응답은 `ownerclan_API.services.normalization.normalize_item()`에서 공통 상품 구조로 정규화한 뒤 PostgreSQL에 저장합니다. 공통 테이블 저장 규칙은 [DB 스키마](../docs/schema/DB_SCHEMA.md)가 기준입니다.

### 상품 master

| PostgreSQL | source |
| --- | --- |
| `products.platform` | `ownerclan` |
| `products.external_product_id` | `productId` 또는 `productKey` |
| `products.product_name` | 정규화된 상품명 |
| `products.product_url` | `productUrl`, `url`, `link` 등 원본 URL 필드. 없으면 `https://www.ownerclan.com/V2/product/view.php?selfcode={productKey}` |
| `products.image_url` | `images[0]` 또는 첫 번째 이미지 필드 |
| `products.backup_image_url` | `images[1]` 또는 두 번째 이미지 필드 |
| `products.status` | 정규화된 판매 상태 |
| `products.source_specific` | `metadata.vendorKey`, `metadata.certificateInformation`, `metadata.productNotificationInformation`, `metadata.returnShippingFee`, `returnable`, `noReturnReason`, `returnCriteria`, `guaranteedShippingPeriod`, `openmarketSellable`, `attributes` 등 플랫폼 전용 보조 정보 |

### 핵심 history

가격, 재고, 배송, 판매 상태가 최초 수집되었거나 실제 변경된 경우에만 `product_history` row를 저장합니다.

| product_history JSON | source |
| --- | --- |
| `prices.rows[].market` | `ownerclan` |
| `prices.rows[].price_type` | `current_supply`, `fixed` |
| `prices.rows[].amount` | `prices.currentSupplyPrice`, `prices.fixedPrice` |
| `inventory.stockQuantity` | 옵션 수량 합계 |
| `inventory.payload` | inventory 보조 값과 원본 수량 |
| `inventory.options` | 옵션별 가격/수량 |
| `shipping.rows[].market` | `ownerclan` |
| `shipping.rows[].fee` | `shippingFee`가 단일 숫자로 해석되는 경우 |
| `shipping.rows[].shippingType` | 계산 가능한 배송비 유형이면 정규화, 아니면 `unknown` |
| `shipping.rows[].payload` | 배송비 조건식 원문과 source fields |

오너클랜은 `product_search_ranks`에 저장하지 않습니다. 현재 수집 경로의 Seller API 응답은 순위 분석에 쓸 수 있는 검색 순위를 제공하지 않습니다.

상품명, 이미지, URL 같은 master 값만 바뀐 경우에는 history를 만들지 않습니다. 가격, 재고, 배송비, 배송 조건, 상태, 옵션 수량/가격이 바뀌면 변경 후 전체 핵심 상태를 `product_history`에 저장합니다.

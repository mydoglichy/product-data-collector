# Ownerclan Seller API Collector

`ownerclan_API`는 오너클랜 Seller API로 상품코드를 발견하고, 상세 상품 데이터를 주기적으로 저장하는 독립 수집기입니다. Partner/Vendor API는 사용하지 않습니다.

## 전제

- 오너클랜 Seller API 계정과 사용 권한이 필요합니다.
- 실제 인증정보는 프로젝트 최상위 `.env`에만 둡니다. `ownerclan_API` 안에 실제 `.env`를 만들지 않습니다.
- 2020년 Seller 매뉴얼을 기준으로 구현했지만, 현재 GraphQL 스키마가 다르면 실제 API 응답과 스키마를 우선합니다.

```env
OWNERCLAN_USERNAME=판매사_ID
OWNERCLAN_PASSWORD=판매사_비밀번호
OWNERCLAN_ENV=production
```

Sandbox는 `https://auth-sandbox.ownerclan.com/auth`, `https://api-sandbox.ownerclan.com/v1/graphql`을 사용합니다. Production은 `https://auth.ownerclan.com/auth`, `https://api.ownerclan.com/v1/graphql`을 사용합니다.

## 수집 흐름

1. `ownerclan_API/keywords.txt`에서 키워드를 읽습니다.
2. 각 키워드마다 `allItems(search: 키워드)` 기본 검색 결과 상위 N개와 `allItems(search: 키워드, sortBy: registerDateDesc)` 신규등록순 상위 N개를 조회합니다.
3. `Item.key`를 `ownerclan_API/tracked_products.json`에 문자열로 중복 없이 누적합니다.
4. 누적된 활성 상품코드를 `items(keys: [...])`로 묶어 상세 조회합니다. 현재 스키마가 거부하면 매뉴얼의 `itemsByKeys(keys: [...])`, 그 다음 `item(key: "...")`로 폴백합니다.
5. `allItems(dateFrom, dateTo, sortBy: dateAsc)`로 수정상품 증분을 끝까지 페이지네이션합니다.
6. 최신 데이터, 날짜별 이력, 실패 정보, 마지막 성공 시각을 모두 `ownerclan_API` 전용 경로에 저장합니다.

기본 검색은 매뉴얼이 판매량 기준 인기순을 보장하지 않으므로 “기본 검색 결과 상위 상품”으로 기록합니다.

실제 Production 스키마 확인 결과, 2026-08-24 현재 `items(keys: [...])`는 지원되지 않고 HTTP 400 GraphQL 오류를 반환했습니다. 수집기는 이 오류를 실패로 종료하지 않고 `itemsByKeys(keys: [...])`로 폴백하며, 이 경우 실행 요약의 `fallbackBatchCount`가 증가합니다.

## 설정

`ownerclan_API/config.yaml`에서 변경합니다.

- `discovery.top_limit_per_keyword`: 기본 검색 결과 상위 개수
- `discovery.new_limit_per_keyword`: 신규등록순 상위 개수
- `details.batch_size`: 복수 상품 상세조회 배치 크기
- `request.interval_seconds`: 요청 간격. 공식 호출 제한이 아니라 프로젝트 기본값입니다.
- `incremental.overlap_minutes`: 수정상품 증분 조회 기간 겹침
- `output.raw_retention_per_product`: 상품별 raw 보존 개수

## 출력 구조

- `ownerclan_API/tracked_products.json`: 상품번호 목록과 발견 키워드, 검색 종류, 최초/최근 발견 시각, 활성 여부
- `ownerclan_API/output/search-ranks-YYYY-MM-DD.json`: 키워드별 발견 순위 기록
- `ownerclan_API/output/product-snapshots-YYYY-MM-DD.json`: 해당 날짜 상품별 최신 snapshot과 실패 목록
- `ownerclan_API/output/latest-products.json`: 상품별 최신 상태와 최근 raw 응답
- `ownerclan_API/output/history/product-history-YYYY-MM-DD.json`: 변경된 정규화 상품 이력
- `ownerclan_API/state/incremental-state.json`: 마지막 성공 증분 수집 시각
- `ownerclan_API/output/failures.json`: 실패 상품 또는 요청 정보
- `ownerclan_API/logs/collector.log`: 실행 로그

`latest-products.json`의 `fingerprint`는 원본 데이터를 복사한 문자열이 아니라 SHA-256 해시입니다. 변경 감지에 필요한 `productId`, 가격, 옵션별 가격/재고, 계산 재고, 배송비, 원본/정규화 상태만 해시 입력으로 사용합니다. 상세설명 `content`, `metadata`, raw 응답은 fingerprint에 넣지 않습니다.

## 실행

프로젝트 최상위에서 실행합니다.

```powershell
python -m ownerclan_API.check_connection
python -m ownerclan_API.discover_products
python -m ownerclan_API.collect_product_details
python -m ownerclan_API.sync_incremental
python -m ownerclan_API.main
```

소량 실 API 확인:

```powershell
python -m ownerclan_API.main --limit 1
```

`--limit 1`은 테스트용입니다. 키워드 1개, 상세조회 상품 1개, 증분 수집 변경상품 1개만 확인합니다. 운영 수집에서는 `--limit`을 빼야 합니다.

API를 호출하되 파일을 쓰지 않는 확인:

```powershell
python -m ownerclan_API.main --limit 1 --dry-run
```

증분 수집만 소량 확인:

```powershell
python -m ownerclan_API.sync_incremental --item-limit 1 --page-limit 1 --dry-run
```

## 옵션, 재고, 상태

- `Item.options[].quantity`를 옵션별 재고수량으로 저장합니다.
- `optionAttributes`가 빈 배열이면 옵션 없는 기본 SKU로 저장합니다.
- 옵션별 `price`와 `quantity`는 원본 의미 그대로 보존합니다. 옵션 `price`를 추가금으로 임의 해석하지 않습니다.
- 전체 재고는 API 원본 전체 재고값이 아니라 유효한 옵션 수량 합계로 계산해 `inventory.stockQuantity`에 저장합니다.
- `inventory.stockQuantitySource`는 항상 `sum(options[].quantity)`로 기록해 계산 근거를 명시합니다.
- API가 별도 전체 재고 필드를 제공하면 `inventory.apiStockQuantity`에 따로 저장합니다.
- 상태는 `sourceStatus`에 원본값, `status`에 정규화값을 저장합니다. `available`, `soldout`, `discontinued`, `unavailable`을 구분하며 재고만으로 판매 가능 여부를 판단하지 않습니다.

## 상품코드 필드

`productId`와 `productKey`는 현재 같은 값인 `Item.key`를 저장합니다.

- `productId`: 기존 도매꾹·도매매 snapshot 구조와 맞추기 위한 공통 식별자입니다.
- `productKey`: 오너클랜 Seller API의 원본 상품코드임을 명확히 하기 위한 출처별 식별자입니다.

두 필드는 값은 중복되지만 역할이 다릅니다. 공통 처리나 기존 분석 코드에서는 `productId`를 쓰고, 오너클랜 API 재조회나 디버깅에서는 `productKey`를 쓰면 됩니다.

## 실제 테스트 중 확인된 동작

- 인증 서버는 JSON이 아니라 JWT 문자열을 본문에 그대로 반환할 수 있습니다. 수집기는 JSON 토큰과 plain-text JWT를 모두 처리합니다.
- GraphQL `Too many requests`가 HTTP 200 응답의 `errors`로 내려올 수 있습니다. 수집기는 제한된 횟수로 백오프 후 재시도합니다.
- `items(keys: [...])`가 없는 스키마에서는 `itemsByKeys(keys: [...])`로 폴백합니다.
- `metadata.productNotificationInformation.categorySpecific`는 품목별 상품고시 항목 답변 배열입니다. 여러 항목이 모두 "상품 상세정보에 별도 표기" 같은 placeholder이면 같은 문구가 반복됩니다. 정규화 snapshot의 `sourceSpecific.metadata`에서는 이런 반복 placeholder 배열을 `categorySpecificSummary`로 압축하고, 원본 raw에는 그대로 보존합니다.

## 수집 필드

요청 필드는 Seller 매뉴얼의 `Item` 예시를 기준으로 합니다. `createdAt`, `updatedAt`, `key`, `id`, `name`, `model`, `production`, `origin`, `price`, `pricePolicy`, `fixedPrice`, `searchKeywords`, `category`, `content`, `shippingFee`, `shippingType`, `images(size: large)`, `status`, `options`, `taxFree`, `adultOnly`, `returnable`, `noReturnReason`, `guaranteedShippingPeriod`, `openmarketSellable`, `boxQuantity`, `attributes`, `closingTime`, `returnCriteria`, `metadata`를 요청합니다.

현재 스키마에서 제거된 필드가 있으면 GraphQL 오류가 발생할 수 있습니다. 그런 경우 실제 스키마에 맞춰 쿼리를 조정해야 하며, 매뉴얼보다 실제 API를 우선합니다.

## 오류 처리

- JWT는 실행 중 재사용하고, `exp`가 있으면 만료 전에 재발급합니다.
- `exp`가 없으면 유효시간을 임의로 단정하지 않습니다.
- 401 또는 인증 만료로 보이는 응답은 JWT를 재발급하고 같은 요청을 한 번만 재시도합니다.
- 429와 일시적 5xx는 제한된 횟수로 exponential backoff를 적용합니다.
- `Retry-After`가 있으면 설정된 최대 범위 안에서 우선 적용합니다.
- GraphQL HTTP 200 응답도 `errors`가 있으면 실패로 처리합니다.
- 비밀번호, JWT, 인증 응답 전문은 로그나 파일에 저장하지 않습니다.

## 서버 스케줄러 예시

Linux cron:

```cron
20 6 * * * cd /home/ubuntu/product-data-collector && /home/ubuntu/product-data-collector/.venv/bin/python -m ownerclan_API.main >> ownerclan_API/logs/cron.log 2>&1
*/30 * * * * cd /home/ubuntu/product-data-collector && /home/ubuntu/product-data-collector/.venv/bin/python -m ownerclan_API.sync_incremental >> ownerclan_API/logs/incremental-cron.log 2>&1
```

다른 수집기와 같은 시간에 몰리지 않도록 쿠팡, 도매꾹·도매매와 분 단위를 다르게 두는 것을 권장합니다.

## 테스트

단위 테스트는 실제 API를 호출하지 않습니다.

```powershell
pytest ownerclan_API/tests
```

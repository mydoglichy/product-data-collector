# API 실험 결과

이 문서는 운영 판단에 영향을 준 probe와 실험 결과만 보관합니다. 실행 절차는 [운영 런북](../operations/RUNBOOK.md), 실제 운영 DB 구조는 [DB 스키마](../schema/DB_SCHEMA.md)를 기준으로 봅니다.

## 오너클랜 호출 제한

테스트 조건:

- 테스트일: 2026-08-30
- 환경: production
- 대상: Seller GraphQL API
- 요청: `allItems(first: 1)`
- 저장: 없음
- 스크립트: `tests/probes/ownerclan_rate_probe.py`

분당 호출 테스트 결과:

| 목표 RPM | 관측 RPM | 결과 |
| ---: | ---: | --- |
| 60 | 60.84 | 61/61 성공, rate limit 없음 |
| 120 | 120.78 | 121/121 성공, rate limit 없음 |
| 180 | 180.58 | 181/181 성공, rate limit 없음 |
| 210 | 203.63 | 204/204 성공, rate limit 없음 |
| 240 | 32.99 | rate limit 없음, `ReadTimeout` 2회 발생 |

1시간 지속 테스트:

| 목표 RPM | 지속 시간 | 시도 | 성공 | 오류 | 결과 |
| ---: | ---: | ---: | ---: | ---: | --- |
| 180 | 3600초 | 10571 | 10520 | 51 | rate limit 없음, 502/ConnectionError 발생 |

추가 백필 중 관측:

- 200 RPM probe는 884회 성공 후 885번째 호출에서 GraphQL `Too many requests.` 발생
- 경과 278.813초, observed RPM 190.4
- 직후 150 RPM probe에서는 초반부터 ReadTimeout과 `502 + Retry-After: 60`이 연속 발생

운영 판단:

- 200 RPM은 위험합니다.
- 240 RPM에서는 rate limit보다 응답 지연/타임아웃이 먼저 발생했습니다.
- 현재 운영 수집 설정은 전역 limiter 기준 약 150 RPM입니다.
- 권장값은 `request.interval_seconds: 0.4`이며, `Retry-After`, 429, GraphQL `Too many requests`는 90초 이상 백오프로 처리합니다.

재테스트 명령:

```powershell
python tests\probes\ownerclan_rate_probe.py --rpm 150 --duration 60
```

## 오너클랜 백필 처리량

작성일: 2026-09-03

로컬 검증에서는 PostgreSQL 저장까지 확인했고, 서버 배포 시에는 전체 상품 백필 가능 여부와 호출 한도 안정성이 핵심이었습니다.

마지막 확인 시점 기준:

- `products` 오너클랜 총계: 579,219개
- 첫 대형 단일 수집 저장 상품: 276,048개
- `allItems` 호출 시도: 689회
- 성공 호출: 657회
- ReadTimeout: 30회
- 429: 0회

4 worker 실행 중 최근 15분 샘플:

- 저장 상품: 148,011개
- 처리 속도: 약 9,867개/min
- 시간당 환산: 약 592,000개/hour
- 1,000만개 단순 투영: 약 16.9시간
- 429: 0
- 최근 API success: 525
- 최근 timeout: 24

`page_size=500` 기준 전체 상품 1,000만 개 백필은 최소 20,000 successful page calls가 필요합니다. timeout, retry, 카테고리 마지막 페이지, 빈 페이지를 감안하면 운영상 21,000~25,000 API attempts 정도를 예상합니다.

병렬 worker + 전역 limiter 변경 후 판단:

- worker는 여러 카테고리를 동시에 맡지만 API 호출 직전에는 같은 전역 limiter를 통과합니다.
- `interval_seconds=0.4` 기준 총합 최대 150 RPM을 넘지 않습니다.
- 실효 처리량은 보수적으로 500,000~1,500,000개/hour 범위로 봅니다.
- 1,000만 개 백필 예상은 약 7~20시간입니다.

## 오너클랜 `itemHistories`

검증일: 2026-09-09

대상 API: Ownerclan Seller GraphQL `itemHistories`

결론:

`itemHistories`는 오너클랜 전체 상품을 매일 다시 훑지 않고, 변경된 상품 키만 찾는 용도로 충분히 사용할 수 있습니다.

확인된 동작:

- `itemHistories(itemKey: "...")`로 특정 상품 이력 조회 가능
- `itemHistories(dateFrom, dateTo)`로 전체 상품 변경 이력 조회 가능
- `kind`로 변경 종류 필터 가능
- `after/endCursor/hasNextPage` cursor pagination 정상 동작
- 전체 상품 `dateFrom/dateTo` 조회는 한 번의 범위를 7일 이하로 쪼개는 방식 권장
- `itemKey` 지정 조회는 최근 3개월 범위를 한 번에 조회 가능
- `first`는 1000 초과 요청 시에도 1000개까지만 반환
- 90일 전 1일 구간도 조회됨

최근 24시간 전체 `itemHistories` 조회 결과:

| 항목 | 값 |
| --- | ---: |
| 조회 범위 | 2026-09-08 16:26:27 ~ 2026-09-09 16:26:27 KST |
| 페이지 수 | 164 |
| 이벤트 수 | 163,663 |
| 고유 `itemKey` 수 | 105,445 |
| 오류 | 0 |

2026-09-21 재확인 smoke test:

| 항목 | 값 |
| --- | ---: |
| 조회 범위 | 2026-09-21 00:43:55 ~ 2026-09-21 01:43:55 KST |
| 요청 | `itemHistories(first: 5, dateFrom, dateTo)` |
| timestamp 단위 | milliseconds |
| 반환 이벤트 수 | 5 |
| `hasNextPage` | true |
| 첫 이벤트 `itemKey` | `WFJ3CQ1` |
| 첫 이벤트 `kind` | `soldout` |
| 첫 이벤트 `createdAt` | `1789922609000` |
| 오류 | 0 |

2026-09-21 `itemKey` 범위 재확인:

| 항목 | 값 |
| --- | ---: |
| 대상 `itemKey` | `WFJ3CQ1` |
| 최근 90일 단일 범위 | 성공, 이벤트 1건 |
| 최근 91일 단일 범위 | 성공, 이벤트 1건 |
| 최근 92일 단일 범위 | 실패 |
| 최근 120일 단일 범위 | 실패 |
| 120~113일 전 7일 범위 | 실패 |
| 오류 메시지 | `itemHistories 쿼리는 최대 3개월 이전 내역까지 조회할 수 있습니다.` |

대략적인 일일 호출량:

| 단계 | 추정 호출 수 |
| --- | ---: |
| `itemHistories(first: 1000)` | 약 164 calls |
| `items(keys: [...])`, batch 100 기준 | 약 1,055 calls |
| 합계 | 약 1,219 calls/day |

상품별 90일 가격/재고 추세 probe:

| 항목 | 값 |
| --- | ---: |
| 검증일 | 2026-09-21 |
| 샘플 상품 수 | 10 |
| 조회 기간 | 2026-06-23 02:06:28 ~ 2026-09-21 02:06:28 KST |
| 조회 방식 | 상품별 `itemHistories(itemKey, dateFrom, dateTo, first: 1000)` 단일 호출 |
| 상품당 `itemHistories` 호출 수 | 1 |
| 전체 `itemHistories` 호출 수 | 10 |
| 전체 이벤트 수 | 70 |
| 가격/재고 이벤트 수 | 15 |
| 이벤트 있는 상품 수 | 10 |
| 오류 | 0 |
| 총 소요시간 | 5.535초 |
| 상품당 평균 소요시간 | 0.553초 |
| 상품당 중앙값 | 0.601초 |
| 상품당 최소/최대 | 0.085초 / 1.493초 |
| 페이지 추가 조회 | 0 |

가격/재고 이벤트 범주별 결과:

| 범주 | 이벤트 수 | 해당 상품 수 | 판단 |
| --- | ---: | ---: | --- |
| 가격 상승 | 2 | 2 | `priceIncreased`로 before/after 추적 가능 |
| 가격 하락 | 2 | 2 | `priceDecreased`로 before/after 추적 가능 |
| 재고 수량 | 10 | 10 | `stockChanged` 이벤트는 확인되나 숫자→숫자 변화는 제한적 |
| 옵션 재고 수량 | 1 | 1 | `optionStockChanged` 이벤트 확인 |

재고 수량 값 품질 재확인:

| 항목 | 수 |
| --- | ---: |
| 검증 범위 | 2026-06-23 01:53:12 ~ 2026-09-21 01:53:12 KST |
| 대상 이벤트 | `stockChanged` |
| 이벤트 수 | 20 |
| 고유 `itemKey` 수 | 20 |
| before/after 둘 다 숫자인 이벤트 | 2 / 20 |
| 한쪽만 숫자인 이벤트 | 18 / 20 |
| 대표 값 형태 | `재고파악안함 -> 11974`, `999 -> 재고파악안함`, `1947 -> 1946` |

재고 변경 상품 상세 재조회 검증:

검증일: 2026-09-21. 최근 90일 `stockChanged` 이벤트 20건의 상품키를 수집하고, 해당 상품을 `item(key: "...")`로 직접 조회했습니다. 최근 30일은 5건, 30~60일 전은 6건, 60~90일 전은 9건이었습니다.

| 항목 | 결과 |
| --- | ---: |
| `stockChanged` 이벤트 수 | 20 |
| 고유 `itemKey` 수 | 20 |
| 직접 조회 성공 | 20 / 20 |
| 현재 상세에서 `options[].quantity` 확인 가능 | 20 / 20 |
| 현재 상세 상태값이 `available` | 12 / 20 |
| 현재 상세 상태값이 `soldout` | 8 / 20 |

대표 사례:

| `itemKey` | `itemHistories` 값 | 현재 상세 `status` | 현재 상세 `options[].quantity` | 판단 |
| --- | --- | --- | --- | --- |
| `WDC576C` | `5 -> 재고파악안함` | `available` | `[9999]` | `9999`는 실제 재고라기보다 재고파악안함 sentinel로 해석 필요 |
| `WD40BF8` | `5 -> 재고파악안함` | `available` | `[9999, 9999]` | 옵션별 재고파악안함 상태 |
| `WFGPZLD` | `재고파악안함 -> 30` | `available` | `[23, 27, 30]` | 상세조회로 현재 옵션 수량 확인 가능 |
| `WFG5UFO` | `2985 -> 1990` | `available` | `[9999, 9999, 9999]` | 이후 재고파악안함 상태로 바뀐 것으로 보이며 현재 조회만으로 과거 수량 복원 불가 |
| `WFHUQUM` | `재고파악안함 -> 11974` | `soldout` | `[0]` | 현재 품절 상태는 상세조회로 확인 가능하지만 과거 변경 직후 수량과 다를 수 있음 |
| `WFG3DO0` | `1947 -> 1946` | `soldout` | `[0]` | 이벤트 값은 숫자지만 현재는 품절 |

`optionStockChanged` 최신 샘플 2건도 직접 조회했습니다.

| `itemKey` | `itemHistories` 값 | 현재 상세 `status` | 현재 상세 `options[].quantity` | 판단 |
| --- | --- | --- | --- | --- |
| `WFLUI5Z` | `갑 5개입 단종 -> 갑 5개입 관리안함` | `available` | `[9999]` | 옵션 상태 변경이며 실제 수량 변화로 보기 어려움 |
| `WFNEUT3` | `장 1개입 단종 -> 장 1개입 관리안함` | `available` | `[9999]` | 옵션 상태 변경이며 실제 수량 변화로 보기 어려움 |

결론: `itemHistories.stockChanged`만으로는 과거 수량 추세를 안정적으로 복원하기 어렵습니다. 다만 매일 `itemHistories(kind: stockChanged/optionStockChanged)`로 변경 상품키를 찾고 즉시 `item(key)` 상세를 재조회해 `options[].quantity`와 `status`를 저장하면, 그 시점 이후의 일별 현재 재고 스냅샷 추세는 만들 수 있습니다. 이때 `9999`는 실제 재고가 아니라 `재고파악안함` 계열 sentinel로 별도 정규화해야 합니다.

`kind`별 값 품질 샘플:

검증일: 2026-09-21. 각 `kind`별 최신 최대 50건을 조회해 `valueBefore/valueAfter` 품질을 확인했습니다.

| 품질 | `kind` | 판단 |
| --- | --- | --- |
| 좋음 | `priceIncreased`, `priceDecreased`, `optionPriceIncreased`, `optionPriceDecreased` | before/after가 숫자로 안정적으로 들어와 가격 추세에 적합 |
| 좋음 | `shippingFeeIncreased`, `shippingFeeDecreased`, `returnShippingFeeIncreased`, `returnShippingFeeDecreased` | 배송비/반품비 금액 변경 추적 가능 |
| 상태 추세용 | `soldout`, `restocked`, `discontinued` | 이벤트 시각은 유효하지만 before/after가 모두 빈 값이라 상태 전환 횟수와 시점만 사용 |
| 상태 추세용 | `optionSoldout`, `optionRestocked`, `optionDiscontinued` | before는 비고 after에 옵션명이 들어와 옵션별 상태 전환 추적 가능 |
| 제한적 | `stockChanged` | 수량 이벤트지만 `재고파악안함`이 섞여 숫자 수량 추세 품질이 낮음 |
| 제한적 | `optionStockChanged` | 옵션 수량보다 `단종`, `관리안함` 같은 텍스트 상태가 섞임 |
| 제한적 | `boxQuantityChanged` | `999 -> 무제한`, `무제한 -> 100`처럼 숫자와 상태값이 섞임 |
| 제한적 | `modelChanged` | 대부분 텍스트 식별자 변경이며 일부만 숫자라 수치 추세로 해석하면 안 됨 |
| 텍스트 변경 | `categoryChanged`, `nameChanged`, `originChanged`, `productionChanged`, `shippingTypeChanged`, `returnableChanged`, `returnCriteriaChanged`, `prohibited`, `etc` | before/after 텍스트 비교는 가능하지만 수치 추세 대상은 아님 |
| 나쁨 | `contentChanged`, `imageChanged`, `productNotificationInformationChanged` | 이벤트는 있으나 before/after가 모두 빈 값이라 실제 변경 내용 복원 불가 |
| 나쁨 | `optionChanged`, `searchKeywordsChanged` | 값이 길거나 구성 문자열 diff라 구조화 없이 추세 지표로 쓰기 어려움 |
| 샘플 없음 | `fixedPriceIncreased`, `fixedPriceDecreased`, `sellerOnlyContentChanged`, `adultOnlyChanged`, `noReturnReasonChanged`, `certificateInformationChanged`, `pricePolicyChanged`, `taxFreeChanged`, `additionalDocumentsChanged` | 최신 50건 조회 기준 샘플 없음 |

권장 수집 방식:

1. 마지막 성공 시각을 sync state에 저장합니다.
2. 매일 `last_success - overlap`부터 현재까지 조회합니다.
3. `dateFrom/dateTo`는 7일 이하로 쪼갭니다.
4. 각 구간을 `first: 1000`과 cursor로 끝까지 가져옵니다.
5. 이벤트에서 나온 `itemKey`를 dedupe합니다.
6. dedupe된 key만 `items(keys: [...])`로 상세 재조회합니다.
7. 기존 저장 함수로 master와 snapshot diff history를 저장합니다.
8. 주 1회 또는 월 1회 전체 보정 수집을 별도로 둡니다.

특정 상품의 최근 90일 가격/재고 추세만 확인할 때는 `itemHistories(itemKey, dateFrom, dateTo, first: 1000)`를 상품당 1회 호출하고, 응답에서 `priceIncreased`, `priceDecreased`, `stockChanged`, `optionPriceIncreased`, `optionPriceDecreased`, `optionStockChanged`만 로컬 필터링합니다.

미적용 DB 권장안:

`itemHistories` 원본 이벤트는 기존 `product_history`와 분리해서 저장하는 것이 맞습니다. 기존 `product_history`는 우리 쪽 snapshot diff 이력이고, `itemHistories`는 오너클랜이 제공하는 source event log입니다. 아래 테이블은 현재 운영 DB에 생성되어 있지 않은 권장안입니다.

```sql
CREATE TABLE ownerclan_item_histories (
    id BIGSERIAL PRIMARY KEY,
    item_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    value_before TEXT NULL,
    value_after TEXT NULL,
    event_created_at TIMESTAMPTZ NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (item_key, kind, title, value_before, value_after, event_created_at)
);
```

## 도매꾹 Private `getItemViewES` 호출 제한

작성 기준: 2026-09-21 KST

대상 API:

- `GET https://www.domeggook.com/ssl/api/`
- `ver=4.0`
- `mode=getItemViewES`
- Private API key: `DOMEGGOOK_PrivateAPI_KEY_2`
- 로그인 세션 사용: `setLogin` 성공 후 `sellerId`, `sId` 포함
- 요청당 상품 수: `no` 100개
- 스크립트: `tests/probes/domeggook_private_rate_probe.py`

핵심 결론:

- Private key여도 분당 180회 근처 제한이 적용됩니다.
- 실제 관측 RPM 180.38에서 HTTP `429`가 발생했습니다.
- 실제 관측 RPM 190.39에서도 HTTP `429`가 발생했습니다.
- `429` 응답에는 `Retry-After` 헤더가 없었습니다.
- 제한 발생 시 즉시 중단하고 최소 180초 쿨다운하는 방식이 맞습니다.
- 100개 batch `getItemViewES`는 정상 동작했습니다.

순차 ramp 테스트:

| 목표 RPM | 지속 시간 | 시도 | 성공 | 오류 | 제한 | 관측 RPM | p95 latency | 결과 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 40 | 120초 | 81 | 81 | 0 | 0 | 40.38 | 422ms | 성공 |
| 80 | 120초 | 161 | 161 | 0 | 0 | 80.29 | 485ms | 성공 |
| 120 | 180초 | 361 | 361 | 0 | 0 | 120.05 | 407ms | 성공 |
| 160 | 240초 | 630 | 630 | 0 | 0 | 157.30 | 406ms | 성공 |
| 180 | 300초 | 831 | 831 | 0 | 0 | 166.11 | 406ms | 목표 RPM 미도달, 제한 없음 |
| 190 | 300초 | 797 | 797 | 0 | 0 | 159.33 | 391ms | 목표 RPM 미도달, 제한 없음 |

순차 테스트의 180/190 RPM 구간은 단일 in-flight 호출로는 응답 시간 때문에 목표 RPM에 도달하지 못했습니다. 따라서 제한 판단에는 아래 concurrency=2 보강 테스트를 기준으로 봅니다.

concurrency=2 보강 테스트:

| 목표 RPM | 지속 예정 | 시도 | 성공 | 오류 | 제한 | 제한 발생 시점 | 관측 RPM | p95 latency | 결과 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 190 | 300초 | 337 | 336 | 0 | 1 | 106.109초, 337번째 호출 | 190.39 | 375ms | HTTP 429 |
| 180 | 300초 | 305 | 304 | 0 | 1 | 101.360초, 305번째 호출 | 180.38 | 375ms | HTTP 429 |

로그 파일:

| 구분 | 파일 |
| --- | --- |
| 순차 ramp | `tests/probes/logs/domeggook_private_rate_20260921_042807.jsonl` |
| 190 RPM 보강 | `tests/probes/logs/domeggook_private_rate_20260921_045318_summary.json` |
| 180 RPM 보강 | `tests/probes/logs/domeggook_private_rate_20260921_050023_summary.json` |

운영 판단:

- Private key도 Open 기준의 "분당 180회 초과 시 3분 차단"과 유사한 제한이 걸립니다.
- 관측상 180.38 RPM에서도 429가 나왔으므로 운영값으로 180 RPM은 쓰지 않습니다.
- 이번 테스트에서 제한 없이 검증된 상한은 관측 157.30 RPM입니다.
- 보수 운영값은 120~150 RPM입니다. 더 밀어야 하면 160 RPM 이하에서 장시간 별도 검증 후 올립니다.
- 429 발생 시 같은 속도로 계속 호출하지 말고 즉시 중단, 최소 180초 쿨다운 후 더 낮은 RPM으로 재개합니다.

4백만 개/일 가능 여부:

요청당 100개 batch 기준:

```text
하루 처리량 = 안정 RPM * 1440분 * 100개
4,000,000개 필요 RPM = 4,000,000 / 1440 / 100 = 27.78 RPM
```

따라서 100개 batch가 유지되면 40 RPM만으로도 이론상 `5,760,000개/일`입니다. 이번 테스트에서 40, 80, 120 RPM은 모두 제한 없이 성공했으므로, RPM 관점에서는 하루 400만 개 수집이 가능합니다. 단, 실제 운영에서는 DB 저장 속도, 중복/실패 재시도, 상품 ID 공급 속도, 일 단위 숨은 쿼터 유무를 별도 모니터링해야 합니다.

## 쿠팡 파트너스 호출 제한

작성 기준: 2026-09-02 KST

핵심 결론:

- 2026-08-26에는 쿠팡 파트너스 Search API로 100개 키워드를 모두 성공 조회했고, 총 994개 상품 row를 만들었습니다.
- 당시 실제 평균 호출 속도는 약 0.805 req/sec, 48.32 RPM이었습니다.
- 2026-09-02 제한 테스트에서는 Search API를 약 2.0 req/sec, 120 RPM 속도로 호출했고, 52번째 호출에서 HTTP 200 + `rCode=403`이 발생했습니다.
- 응답 메시지는 `검색 API의 시간당 사용 횟수 초과`였고, 재시도 가능 시각으로 2026-09-03 17:46:28 이후를 반환했습니다.
- 제한 상태에서 Best Category API를 1회 호출했을 때도 HTTP 200 + `rCode=403`이 반환되어 Search API와 Best Category API는 같은 상품 검색 계열 쿼터를 공유하는 것으로 보입니다.

근거 파일:

| 구분 | 파일 | 의미 |
| --- | --- | --- |
| 과거 정상 수집 상품 파일 | `coupang_API/data/processed/coupang_2026_0826_2101_products.jsonl` | 2026-08-26 실행 결과 상품 row 994개 |
| 과거 정상 수집 요약 | `coupang_API/data/summaries/coupang_2026_0826_2101_summary.json` | 100개 키워드 성공, 실패 0개 |
| Search 제한 테스트 로그 | `tests/probes/logs/coupang_rate_probe_20260902_174602.jsonl` | 601회 호출, 52번째부터 제한 관측 |
| Best Category 제한 확인 로그 | `tests/probes/logs/coupang_rate_probe_best-category_20260902_210715.jsonl` | 제한 상태에서 1회 호출, 즉시 `rCode=403` |

2026-09-02 Search 제한 테스트:

| 항목 | 값 |
| --- | ---: |
| 총 호출 수 | 601회 |
| 성공 수 | 204회 |
| 실패 수 | 397회 |
| HTTP 상태코드 분포 | `200`: 601회 |
| rCode 분포 | `0`: 204회, `403`: 397회 |
| 전체 테스트 실제 평균 | 120.2 RPM |
| 최초 제한 attempt | 52번째 |
| 제한 발생 전 성공 수 | 51회 |
| 최초 제한 HTTP 상태코드 | 200 |
| 최초 제한 rCode | `403` |
| Retry-After 헤더 | 없음 |

운영 판단:

- Search API와 Best Category API를 같은 쿼터로 묶어서 계산합니다.
- HTTP 상태코드와 JSON `rCode/rMessage`를 함께 검사합니다.
- `rCode=403`, `rCode=429`, 시간당 사용 횟수 초과 메시지는 즉시 중단합니다.
- 제한 상태 재확인을 반복하지 않습니다.
- 재개는 쿠팡 응답의 재시도 가능 시각 이후로 미룹니다.
- 현재 운영 속도는 저장소 설정의 40 RPM을 사용하되, 제한 메시지가 재발하면 계정 상태 기준으로 더 낮춰야 합니다.

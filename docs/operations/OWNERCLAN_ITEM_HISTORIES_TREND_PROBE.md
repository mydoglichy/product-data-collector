# Ownerclan `itemHistories` Trend Probe

검증일: 2026-09-09  
대상 API: Ownerclan Seller GraphQL `itemHistories`

## 결론

`itemHistories`는 오너클랜 전체 상품을 매일 다시 훑지 않고, 변경된 상품 키만 찾는 용도로 충분히 사용할 수 있다.

확인된 동작:

- `itemHistories(itemKey: "...")`로 특정 상품 이력 조회 가능
- `itemHistories(dateFrom, dateTo)`로 전체 상품 변경 이력 조회 가능
- `kind`로 변경 종류 필터 가능
- `after/endCursor/hasNextPage` cursor pagination 정상 동작
- 한 번의 `dateFrom/dateTo` 범위는 최대 7일
- `first`는 1000 초과 요청 시에도 1000개까지만 반환
- 90일 전 1일 구간도 조회됨

따라서 일일 운영은 아래 구조가 적합하다.

```text
itemHistories(dateFrom, dateTo) 전체 페이지 수집
-> itemKey dedupe
-> itemHistories 원본 이벤트 별도 저장
-> 변경된 itemKey만 items(keys: [...])로 상세 재조회
-> products 최신값 upsert
-> product_history에는 기존 snapshot diff 방식으로 저장
```

## 대량 변경 감지 가능성

최근 24시간 전체 `itemHistories`를 실제로 끝까지 조회한 결과:

| 항목 | 값 |
| --- | ---: |
| 조회 범위 | 2026-09-08 16:26:27 ~ 2026-09-09 16:26:27 KST |
| 페이지 수 | 164 |
| 이벤트 수 | 163,663 |
| 고유 `itemKey` 수 | 105,445 |
| 오류 | 0 |

오너클랜 전체 상품 1,000만 개 중 하루 변화율이 약 1%라면, 매일 전체 상품을 재수집하는 대신 약 10만 개 내외의 변경 상품만 재조회하는 방식이 가능하다.

대략적인 일일 호출량:

| 단계 | 추정 호출 수 |
| --- | ---: |
| `itemHistories(first: 1000)` | 약 164 calls |
| `items(keys: [...])`, batch 100 기준 | 약 1,055 calls |
| 합계 | 약 1,219 calls/day |

현재 운영 설정 `request.interval_seconds: 0.4` 기준으로는 API 대기시간만 계산하면 약 8분대이고, 응답 지연과 재시도를 감안해도 매일 처리 가능한 규모다.

## 30개 상품 90일 추세 Probe

최근 7일 변경 이벤트에서 가격, 재고, 품절, 배송, 반품 이벤트가 섞이도록 30개 상품을 선정했다. 각 상품은 최근 90일을 7일 이하 구간으로 쪼개 조회했다.

| 항목 | 값 |
| --- | ---: |
| 샘플 상품 수 | 30 |
| 조회 기간 | 2026-06-11 16:40:27 ~ 2026-09-09 16:40:27 KST |
| `itemHistories` 호출 수 | 390 |
| 조회 페이지 수 | 390 |
| 총 이벤트 수 | 291 |
| 이벤트 있는 상품 수 | 30 |
| 오류 | 0 |
| 총 소요시간 | 289.75초 |
| 현재 상세 `items` batch 조회 | 30/30 성공, 1.14초 |

직렬 실행 기준 평균은 상품당 약 9.7초였다. 현재 rate limiter가 호출 간 0.4초를 강제하므로, 단일 상품 90일 조회는 보통 13 calls 내외이고 약 7~10초 수준으로 보면 된다.

## 이벤트 범주별 결과

| 범주 | 이벤트 수 | 해당 상품 수 | 판단 |
| --- | ---: | ---: | --- |
| 가격 | 41 | 20 | before/after가 숫자로 안정적으로 들어와 추세 분석 가능 |
| 재고 수량 | 1 | 1 | 이벤트는 있으나 숫자 복원 품질은 낮음 |
| 품절/재입고/단종 | 187 | 20 | 수량보다 상태 추세 분석에 강함 |
| 배송 | 12 | 8 | 배송비/배송방식 변경 추적 가능 |
| 반품 정책 | 10 | 9 | 반품배송비/반품기준 변경 감지 가능 |
| 인증/고시/판매제한 | 5 | 4 | 상품정보고시 변경 감지 가능 |
| 상품명/상세/이미지/카테고리 등 | 35 | 다수 | 리스팅 품질 변화 감지 가능 |

상위 이벤트 종류:

| kind | 이벤트 수 |
| --- | ---: |
| `soldout` | 77 |
| `restocked` | 75 |
| `optionSoldout` | 17 |
| `optionPriceDecreased` | 15 |
| `priceIncreased` | 14 |
| `nameChanged` | 14 |
| `optionRestocked` | 14 |
| `contentChanged` | 7 |
| `optionPriceIncreased` | 5 |
| `productNotificationInformationChanged` | 5 |

## 값 품질

| 항목 | 수 |
| --- | ---: |
| `valueBefore` 또는 `valueAfter`가 있는 이벤트 | 127 / 291 |
| before/after 둘 다 숫자인 이벤트 | 56 / 291 |
| 가격 이벤트 중 before/after 둘 다 숫자 | 41 / 41 |
| 재고 수량 이벤트 중 before/after 둘 다 숫자 | 0 / 1 |

가격 이벤트는 샘플에서 모두 숫자 before/after를 제공했다.

예시:

| kind | before | after |
| --- | ---: | ---: |
| `priceIncreased` | 18,480 | 20,000 |
| `priceDecreased` | 10,460 | 9,510 |
| `fixedPriceIncreased` | 10,900 | 12,900 |
| `fixedPriceDecreased` | 5,984 | 5,800 |
| `optionPriceIncreased` | 0 | 380 |
| `optionPriceDecreased` | 1,210 | 0 |

재고 이벤트는 숫자 추세보다는 상태 추세로 보는 편이 안전하다.

예시:

| kind | before | after |
| --- | --- | --- |
| `stockChanged` | `5` | `재고파악안함` |
| `soldout` | empty | empty |
| `restocked` | empty | empty |
| `optionSoldout` | empty | option name |
| `optionRestocked` | empty | option name |

## 가능한 기능

`itemHistories`만으로 가능한 기능:

- 특정 상품의 최근 3개월 가격 변경 타임라인
- 판매가, 소비자가, 옵션가 인상/인하 횟수
- 최초/최종 가격, 최대 인상폭, 최대 인하폭, 변동률
- 품절/재입고/단종 이벤트 타임라인
- 옵션별 품절/재입고 이벤트 추적
- 배송비 인상/인하, 배송방식 변경 감지
- 반품배송비 인상/인하, 반품기준 변경 감지
- 상품정보고시, 인증정보, 판매금지 등 리스크 이벤트 감지
- 상품명, 이미지, 상세페이지, 카테고리 변경 감지
- 일일 변경 상품 key 수집 및 변경 사유 저장

`itemHistories`만으로 부족한 기능:

- 모든 시점의 완전한 상품 스냅샷 복원
- 옵션별 정확한 재고 수량 그래프
- 값이 비어 있는 이벤트의 before/after 복원
- API 보존 기간을 넘어서는 장기 분석
- 현재 상품 상태의 전체 필드 확인

따라서 분석 화면에서는 `itemHistories` 이벤트 타임라인과 현재 `item/items` 상세 조회 결과를 결합해야 한다.

## 권장 DB 변경

`itemHistories` 원본 이벤트는 기존 `product_history`와 분리해서 저장하는 것이 맞다. 기존 `product_history`는 우리 쪽 snapshot diff 이력이고, `itemHistories`는 오너클랜이 제공하는 source event log다.

권장 테이블:

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

권장 인덱스:

```sql
CREATE INDEX idx_ownerclan_item_histories_item_time
ON ownerclan_item_histories(item_key, event_created_at);

CREATE INDEX idx_ownerclan_item_histories_time
ON ownerclan_item_histories(event_created_at);

CREATE INDEX idx_ownerclan_item_histories_kind_time
ON ownerclan_item_histories(kind, event_created_at);
```

## 권장 수집 방식

1. 마지막 성공 시각을 `ownerclan_item_histories_sync_state` 또는 기존 state 파일에 저장한다.
2. 매일 `last_success - overlap`부터 현재까지 조회한다.
3. `dateFrom/dateTo`는 7일 이하로 쪼갠다.
4. 각 구간을 `first: 1000`과 cursor로 끝까지 가져온다.
5. 이벤트는 `ownerclan_item_histories`에 upsert한다.
6. 이벤트에서 나온 `itemKey`를 dedupe한다.
7. dedupe된 key만 `items(keys: [...])`로 상세 재조회한다.
8. 기존 `save_products_with_raw_samples_if_enabled()`로 master와 snapshot diff history를 저장한다.
9. 주 1회 또는 월 1회 전체 보정 수집을 별도로 둔다.

## 판단

`itemHistories`는 매일 전체 상품을 다시 조회하는 구조를 대체할 수 있는 강한 변경 감지 소스다. 특히 오너클랜 1,000만 상품 중 하루 약 1%만 바뀌는 상황이라면, 매일 약 10만 key만 재조회하는 구조로 수집 비용을 크게 줄일 수 있다.

단, `itemHistories`를 기존 `product_history`의 대체재로 보면 안 된다. 이 API는 변경 이벤트 로그이고, 전체 상품 상태 스냅샷은 아니다. 운영 구조는 `itemHistories`로 변경 key를 찾고, `item/items` 상세 재조회로 우리 DB의 최신 상태와 snapshot history를 유지하는 방식이 가장 안전하다.

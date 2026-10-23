# 차원 확인 · 가장 잘게 받기 (agency 플러그인 공용)

## 1. 차원 확인 (실행마다 1회, 응답이 아주 작다)

`get_ad_performance`를 **없는 차원 이름**으로 1회 부르면 서버가 쓸 수 있는 차원 목록을 담은 에러를 돌려준다:

```json
{"brand_name": "<brand>", "start_date": "<기간 시작>", "end_date": "<기간 끝>", "time_grain": "total",
 "group_by": ["__list_dimensions__"], "metrics": []}
```
→ `unknown group_by dimension(s) [...]; valid dimensions: ['ad_group_name', 'ad_name', 'ad_type', 'campaign_name', 'date', 'media', 'source', ...]`

피벗 차원(`FINE_DIMS`) = 그 목록에서 `date`·`month`·`source`·`*_id`와 노출 위치 차원(`placement` 등 — Placement 표용으로 따로 받는다)을
뺀 것, 순서는 `media` → `ad_type`/`상품` → `campaign_name` → `ad_group_name` → `ad_name` → 나머지(목록 순).
에러 메시지 원문은 빌더 입력 `dims`에도 그대로 넣는다 — 빌더(`report_kit.require_dims`)가 표 응답에 FINE_DIMS가 다 있는지
보고, 빠졌으면 멈춘다. 서버가 제공하지 않는 차원은 요구하지 않는다.

## 2. 가장 잘게 1번씩 받기 · 크기 대응

- 표 데이터는 `group_by` = FINE_DIMS로 받는다(`metrics`·`filters` 생략). 큰 응답은 플러그인 훅이 파일로 저장한다 → 스텁의 경로를
  `json_files`에 넣는다.
- **크기 상한**: 응답이 크기 오류(50,000행 초과·`AsyncResponsePayloadTooLarge` 등)로 실패하면 `ad_name`을 빼고 1회 다시 부른다.
  그래도 실패하면 `ad_group_name`도 뺀다(메뉴에 없는 차원은 고를 수 없다).
- 빌더는 표 데이터의 매체별 합을 매체별 일별 응답과 **대조 검증**한다(어긋나면 멈춘다 — 값을 고쳐 맞추지 않는다).

# 차원 확인 · 가장 잘게 받기 · 선택 표 (agency 플러그인 공용)

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

## 3. 스킬별 표 데이터 호출

| 스킬 | 호출 (`group_by` = FINE_DIMS, `metrics`·`filters` 생략) | 대조 검증 상대 |
|---|---|---|
| integrated-report | `time_grain:"day"`, 걸친 달마다 1회 | 매체별 일별 |
| daily-report | 1회: `time_grain:"day"`, D7~D0 (빌더가 기준일·전일·전주 동요일 행만 쓴다) | s3 매체 일별 · s1 전체 |
| weekly-report | 이번주(E-6~E)·전주(E-13~E-7) **각 1회**: `time_grain:"total"` | s3 매체 일별의 그 주 합 |
| monthly-report | 1회: `time_grain:"month"`, M-1 1일 ~ M0 말일 | s4 매체 월별 |

## 4. 선택 표(Dimension·지표 메뉴) — daily·weekly·monthly

렌더링은 `LHKit.pickTable`, 데이터는 `report_kit.pick_section`이다 — 모델은 응답을 넘기기만 한다.
보고서를 연 사람이 Dimension 메뉴에서 표시할 차원과 순서를, 지표 메뉴에서 지표를 고른다(처음엔 광고비만, 광고비는 맨 앞 고정).
차원 하나를 골라 검색한다(10개씩 페이지, 맨 아래 전체/검색 결과 합계).

- 기간마다 원 행이 1개인 칸 = **서버 값 그대로**. 여러 행을 묶은 칸 = 가산 지표는 합, CTR·CPM·CPV는 합친 원자 지표로 다시 계산,
  그 밖의 비율 지표는 `-`.
- 전체 행 = 검색하지 않으면 서버 총계, 검색하면 검색된 행의 합계("검색 결과 합계").
- 표 방식: daily·weekly = 비교(지표마다 비교·기준 기간 + 증감), monthly = 목표 달성(지표마다 목표·실적·달성률/목표 대비,
  목표 없으면 "-", 매체 소계 행).
- 색: 증감은 **변화율 ±10% 미만**, 단위가 %인 지표는 **±1%p 미만**이면 색 없음(값·화살표는 그대로).
  monthly 목표 달성 표는 광고비 소진율 **100% ± 10%p**, 합산 지표 달성률 100%↑ 초록·90%↑ 주황·미만 빨강.

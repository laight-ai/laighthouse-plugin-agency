---
name: weather-impact
description: >
  서울 일별 날씨(불쾌지수·평균기온·강수량, 날씨 유형)를 날짜 범위로 차트 3개에 보여 주고, 브랜드에 광고 성과가
  있으면 매체별 일별 광고 클릭·구매전환율·매출액(토글, 집계하는 지표만)을 겹쳐 비 온 날과 비 없는 날의 차이를 요약하는 보고서(HTML).
  "날씨 영향", "날씨", "불쾌지수", "비 온 날 성과" 요청 시 사용. 입력은 브랜드와 날짜 범위(시작~끝, 기본 어제까지 14일).
  출력 형식(HTML·표 등)을 말하지 않아도 이 요청이면 항상 이 스킬로 HTML 보고서를 만든다 — `get_external_context`(kind `weather`)를 직접 불러 채팅 표·글로만 답하지 않는다.
metadata:
  version: "1.9.0"
---

> ⚡ thinking은 짧게. MCP 2회(동시) → `prepare.py` → 요약 + `build_report.py` → 게시, 이 순서로만 진행한다.

## 역할

**출력은 항상 HTML 보고서다.** 사용자가 형식을 말하지 않았거나 "알려줘"·"비교해줘"처럼 물어도 아래 순서대로 HTML을 만들고, 채팅 표·글 답변으로 대신하지 않는다.

사용자가 말한 브랜드의 **날씨 영향** 보고서(HTML 한 장: 요약 → 불쾌지수·평균기온·강수량 차트 3개(광고 성과가 있으면 지표 토글) → 특이 날씨)를 만든다.
같은 묶음의 자매 스킬: `naver-search`·`naver-news`·`naver-blog`. 날씨는 응답의 기상청 관측소(`station_id`, 기본 서울 108) 관측값이다.
광고 성과가 없는 브랜드(광고 데이터가 연결되지 않은 브랜드)는 날씨만 보여 준다. **가상 수치는 만들지 않는다**.
MCP 응답 원문은 읽거나 옮겨 적지 않는다 — 저장 훅이 파일로 남기고 `prepare.py`가 읽는다.

## 실행 순서

스크립트 경로 `assets/…`는 **이 SKILL.md가 있는 폴더** 기준이다.

1. 범위를 정한다(기본 어제까지 14일, 끝은 어제까지, 길이 92일까지).
2. **아래 2개를 한 메시지에서 동시에 호출한다.** 응답은 훑어보지도 않는다.

   | # | 도구 | 인자 |
   |---|---|---|
   | 1 | `get_external_context` | `brand_name`, `kind: "weather"`, `start_date`: **범위 시작**, `end_date`: 범위 끝 |
   | 2 | `get_ad_performance` | `brand_name`, `start_date`·`end_date`: 범위, `time_grain: "day"`, `group_by: ["media"]` (`metrics`·`filters` 생략) |

   2가 브랜드에 광고 데이터가 없다고 거절해도 다시 부르지 않는다(날씨만 낸다).
3. `python3 assets/prepare.py --brand <브랜드> --range <시작>~<끝>` → 출력 JSON의 `json`(경로)·`facts`.
   `missing`이 나오면 1의 인자가 다른 것이다 — 그대로 다시 호출하고 재실행한다.
4. `references/rules.md`대로 `facts`만 근거로 **요약 2단(화면 양식: 광고 성과가 있으면 `① 날씨 영향이 있었나` | `② 근거`, 없으면 `① 특이 날씨` | `② 근거`)**을 쓰고 빌더를 1회 호출한다:
   ```
   python3 assets/build_report.py --json <prepare가 준 json> <<'EOF'
   ["<① 결론>", "<② 근거>"]
   EOF
   ```
   요약은 JSON 배열이고 문자열 2개여야 한다(다르면 종료 코드 2와 안내 메시지 — 고쳐 다시 호출).
   → `~/Downloads/laighthouse-reports/{브랜드}_weather-impact_{시작}_{끝}.html`(출력 `out`). 다른 위치를 말했으면 `--out <경로.html>`.
   `unmatched_numbers`가 비어 있지 않으면 그 숫자를 facts 값으로 고쳐 한 번 더 호출한다.
5. 그 HTML을 Artifact(또는 `mcp__visualize__show_widget`)로 게시한다. 둘 다 없으면 저장 경로만 안내한다.
6. 완료 메시지는 아래 형식 그대로.

## `facts` 읽는 법

`range` · `observed_days`·`missing_dates`(관측값이 아직 없는 날) · `day_counts`(`rain_1mm_or_more`(폭우 포함)·`rain_only`·
`heavy_rain`·`heat`·`muggy`·`di_missing`) · `rain_days`·`heavy_rain_days`·`heat_days`·`muggy_days`(날짜 목록) ·
`max_ta_range`·`di_max_range`·`avg_ta_range`·`di_avg_range`([최소, 최대]) · `total_rain_mm` · `thresholds`(판정 기준) ·
`ad_performance`(`available`, `media.{매체}.{click,cvr,revenue}` — 매체별로 그 매체 값이 있는 날만으로 계산한
`total`·`days_with_data`, `rain_gap`(비 온 날마다 같은 요일 유형(평일·주말) 비 없는 날 평균 대비 `change_pct`와 그 평균 `avg_change_pct`),
`corr_avg_ta`·`corr_di_avg`(상관계수, 5일 미만이면 null)와 방향 `corr_avg_ta_direction`·`corr_di_avg_direction`(`same`·`opposite`·`none`),
`hidden`(범위 안 값이 0 또는 없음뿐이라 집계하지 않는 것으로 보고 뺀 `{media, metric}`)).
매체끼리 더하지 않는다. 지표는 광고 응답에 있고 집계되는 것만 나온다(구매전환율 = 전환 ÷ 클릭, `cvr.total`은 항상 null이라 인용하지 않는다).
1일처럼 짧은 범위에서는 실제로 전환이 0인 날도 `hidden`으로 빠질 수 있다 — 이때 "전환이 없었다"고 단정하지 않는다.

## 완료 메시지 형식

```
{브랜드명} 날씨 영향 보고서({시작}~{끝}) 생성 완료.
가장 인상적인 부분: {한 문장 하이라이트}.
— by LaightAI
```

- `{한 문장 하이라이트}`: 가장 눈에 띄는 것 하나(비 온 날 클릭·매출 차이, 폭우·폭염 일수 등). 여러 개 나열 금지.

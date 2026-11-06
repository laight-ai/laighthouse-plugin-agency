---
name: naver-search
description: >
  브랜드(자사·경쟁)의 네이버 추정 검색수를 날짜 범위로 비교하는 보고서(HTML). 요약 + 브랜드별 일별 추정 검색수 차트.
  "검색량", "네이버 검색량", "검색 추이", "검색수 비교" 요청 시 사용. 입력은 브랜드와 날짜 범위(시작~끝, 기본 어제까지 14일).
  광고 성과와는 결합하지 않는다.
  출력 형식(HTML·표 등)을 말하지 않아도 이 요청이면 항상 이 스킬로 HTML 보고서를 만든다 — `get_external_context`(kind `search_volume`)를 직접 불러 채팅 표·글로만 답하지 않는다.
metadata:
  version: "1.9.0"
---

> ⚡ thinking은 짧게. MCP 1회 → `prepare.py` → 요약 + `build_report.py` → 게시, 이 순서로만 진행한다.

## 역할

**출력은 항상 HTML 보고서다.** 사용자가 형식을 말하지 않았거나 "알려줘"·"비교해줘"처럼 물어도 아래 순서대로 HTML을 만들고, 채팅 표·글 답변으로 대신하지 않는다.

사용자가 말한 브랜드의 **네이버 검색량** 보고서(HTML 한 장: 요약 → 브랜드 비교 차트)를 만든다.
같은 묶음의 자매 스킬: `naver-search`(검색량)·`naver-news`(뉴스)·`naver-blog`(블로그)·`weather-impact`(날씨).
브랜드명은 호출의 `brand_name`과 제목·파일명에 **그대로** 쓴다.

계산·렌더링은 스크립트가 한다. 모델이 할 일은 (1) MCP 호출 1회, (2) 스크립트 실행, (3) 요약 작성뿐이다.
**MCP 응답 원문을 읽거나 옮겨 적지 않는다** — 플러그인 저장 훅이 응답을 파일로 남기고 `prepare.py`가 읽는다.

## 실행 순서

스크립트 경로 `assets/…`는 **이 SKILL.md가 있는 폴더** 기준이다.

1. 범위를 정한다. 사용자가 "최근 2주"처럼 말하면 어제(KST)까지로 바꾼다(기본 어제까지 14일). 끝은 어제까지, 길이는 92일까지.
2. **`get_external_context`를 1회 호출한다.** 인자:
   `brand_name`: 브랜드, `kind`: `"search_volume"`, `start_date`: **범위 시작 − 7일**, `end_date`: 범위 끝.
   (앞 7일은 첫날의 직전 7일 평균에 쓴다.) 응답은 훑어보지도 않는다.
3. `python3 assets/prepare.py --brand <브랜드> --range <시작>~<끝>` → 출력 JSON의 `json`(경로)·`facts`.
   - `missing`이 나오면 2의 인자가 다른 것이다 — 그 인자 그대로 다시 호출하고 재실행한다.
   - 종료 코드 2(stderr 메시지)는 사용자에게 그대로 전한다(예: 검색량은 매일 10시 수집 뒤에 어제 값이 들어온다).
   - 도구가 "is not collected for external context"로 거절하면 외부 데이터 수집 대상이 아닌 브랜드라고 알린다.
4. `references/rules.md`대로 `facts`만 근거로 **요약 3문단(화면 양식: 굵은 결론 → 회색 보조 문단 → "수치:" 보조 문단)**을 쓰고 빌더를 1회 호출한다:
   ```
   python3 assets/build_report.py --json <prepare가 준 json> <<'EOF'
   ["<결론>", "<근거>", "<수치>"]
   EOF
   ```
   요약은 JSON 배열이고 문자열 3개("수치: "는 화면이 붙인다)여야 한다(다르면 종료 코드 2와 안내 메시지 — 고쳐 다시 호출).
   → `~/Downloads/laighthouse-reports/{브랜드}_naver-search_{시작}_{끝}.html`(출력 `out`). 다른 위치를 말했으면 `--out <경로.html>`.
   출력의 `unmatched_numbers`가 비어 있지 않으면 그 숫자를 facts의 값으로 고쳐 한 번 더 호출한다.
5. 그 HTML을 Artifact(또는 `mcp__visualize__show_widget`)로 게시한다. 둘 다 없으면 저장 경로만 안내한다.
6. 완료 메시지는 아래 형식 그대로.

## `facts` 읽는 법

`range`(시작·끝·일수) · `brands[]`(`total` 범위 합 — 쓸 수 있는 날이 절반 미만이면 null, `rank`, `daily_avg`, `peak`) · `rank_basis`(`total`이면 범위 합계 순위, `daily_avg`면 브랜드마다 쓸 수 있는 날 수가 달라 일평균 순위 — 이때는 '하루 평균 n위'로 쓰고 '합계 n위'라고 쓰지 않는다) ·
`leader` · `last7_vs_prev7`(범위가 14일 이상일 때만: 끝 7일 vs 앞 7일 합과 `change_pct`) ·
`share_last7_pct`/`share_range_pct`(점유율) · 브랜드별 `peak_vs_range_daytype_avg_x`(최다일 ÷ 범위 평일·주말 평균) · 급증마다 `vs_range_daytype_avg_x`(범위 평일·주말 평균 대비 배수) · `last7_vs_prev7.all_brands`(전체 브랜드 합계 끝 7일 vs 앞 7일) · `spike_rule` · `spikes[]`(같은 요일 유형 평균 대비 급증일: `baseline_same_daytype_avg`·`ratio_x`·`last_week_same_day`·`vs_last_week_pct`) · 브랜드별 `weekday_avg`·`weekend_avg`(+`_days`, 근거가 부족하면 null)·`vs_last_week_same_day_max`/`_min` ·
`data_status`(모델용 데이터 상태 — 옮겨 적지 않는다).

## 완료 메시지 형식

```
{브랜드명} 네이버 검색량 보고서({시작}~{끝}) 생성 완료.
가장 인상적인 부분: {한 문장 하이라이트}.
— by LaightAI
```

- `{한 문장 하이라이트}`: 보고서 수치 중 가장 눈에 띄는 것 하나(끝 7일 추정 검색수 등). 여러 개 나열 금지.

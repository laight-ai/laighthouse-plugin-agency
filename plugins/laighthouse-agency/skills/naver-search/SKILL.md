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
   - `missing`이 나오면 2의 인자가 다른 것이다 — 그 인자 그대로 **한 번만** 다시 호출하고 재실행한다.
   - `errors`가 나오거나 종료 코드 2면 아래 **실패하면** 표대로 안내하고 멈춘다(예: 검색량은 매일 10시 수집 뒤에 어제 값이 들어온다).
   - 2의 도구 호출이 오류면 여기까지 오지 않고 **실패하면** 표대로 멈춘다.
4. `references/rules.md`대로 `facts`만 근거로 **요약 3문단(화면 양식: 굵은 결론 → 회색 보조 문단 → "수치:" 보조 문단)**을 쓰고 빌더를 1회 호출한다:
   ```
   python3 assets/build_report.py --json <prepare가 준 json> <<'EOF'
   ["<결론>", "<근거>", "<수치>"]
   EOF
   ```
   요약은 JSON 배열이고 문자열 3개("수치: "는 화면이 붙인다)여야 한다(다르면 종료 코드 2와 안내 메시지 — 고쳐 다시 호출, 두 번째도 같으면 실패 10).
   → `~/Downloads/laighthouse-reports/{브랜드}_naver-search_{시작}_{끝}.html`(출력 `out`). 다른 위치를 말했으면 `--out <경로.html>`.
   출력의 `unmatched_numbers`가 비어 있지 않으면 그 숫자를 facts의 값으로 고쳐 한 번 더 호출한다. 그래도 남으면 실패 11.
5. 그 HTML을 Artifact(또는 `mcp__visualize__show_widget`)로 게시한다. 둘 다 없으면 저장 경로만 안내한다.
6. 완료 메시지는 아래 형식 그대로.

## 실패하면

아래 경우는 **원인 한 줄과 사용자가 할 일 한 줄로 안내하고 멈춘다.** 멈출 때는 다른 도구(`get_ad_performance` 등)나 MCP 응답 원문으로 대신 집계하지 않고, 표·추정치·HTML을 만들지 않는다. 도구 호출이 오류로 끝나면 `prepare.py`를 실행하지 않는다.

| 번호 | 언제 | 안내 |
|---|---|---|
| 실패 1 | `get_external_context` 도구가 없다 | 외부 맥락 도구를 쓸 수 없다. `/mcp`에서 laighthouse 서버 연결·로그인을 확인하고, 연결돼 있으면 아직 이 서버에 배포되지 않은 기능이다 |
| 실패 2 | 도구 오류 `Unknown brand` · `Several brands are named` | 브랜드를 찾지 못했다(또는 같은 이름이 여럿이다). 필요하면 `get_brand_list`로 이름을 보여 주고, 그 이름 그대로 다시 요청하게 한다 |
| 실패 3 | 도구 오류 `MCP service is not enabled for brand` | 이 브랜드는 MCP 사용이 꺼져 있다. 관리자에게 켜 달라고 요청하게 한다 |
| 실패 4 | 도구 오류 `is not ELT-published yet` | 이 브랜드의 데이터 저장소가 아직 준비되지 않았다 |
| 실패 5 | 도구 오류 `is not collected for external context` | 외부 데이터(검색량·뉴스·블로그·날씨) 수집 대상이 아닌 브랜드다 |
| 실패 6 | 그 밖의 도구 오류(날짜 형식, 400일 초과, 문서가 너무 많음, 서버·네트워크 오류) | 오류 메시지를 그대로 전한다. 문서가 너무 많으면 범위를 줄여 다시 요청하라고, 서버·네트워크 오류면 잠시 뒤 다시 요청하라고 덧붙인다. 같은 호출을 되풀이하지 않는다 |
| 실패 7 | 다시 호출한 뒤에도 `prepare.py`가 `missing`을 낸다 | 응답이 파일로 저장되지 않았다(플러그인 저장 훅이 동작하지 않음). 플러그인 설치·활성화를 확인하게 한다 |
| 실패 8 | `prepare.py`가 `errors`를 낸다 | 저장된 응답이 오류다. 그 메시지로 실패 2~6 중 맞는 안내를 한다 |
| 실패 9 | `prepare.py`·`build_report.py`가 종료 코드 2로 끝난다(요약 형식 오류 제외) | stderr 메시지를 그대로 전한다(범위 형식, 끝이 어제 이후, 92일 초과, 자사 브랜드 없음, 검색량 수집 대상 아님, 그날 값이 아직 수집 전, 날씨 관측값 없음) |
| 실패 10 | 요약 형식 오류(종료 코드 2)를 고쳐 다시 불러도 또 난다 | 보고서를 만들지 못했다고 알린다 |
| 실패 11 | `unmatched_numbers`를 고쳐 다시 불러도 남는다 | HTML을 게시하지 않는다. facts에서 확인되지 않은 숫자를 알리고 멈춘다 |
| 실패 12 | `python3`가 없다 | python3(3.9 이상)가 필요하다고 알린다 |

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

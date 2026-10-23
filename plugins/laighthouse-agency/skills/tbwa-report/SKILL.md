---
name: tbwa-report
description: >
  TBWA 보고서(TBWA skill report) 생성 스킬. "TBWA 보고서", "TBWA 스킬 보고서", "tbwa report" 요청 시 사용.
  시작일(기본: 전월 1일)부터 어제까지를 한 화면에 담는다 — 전일 대비 급감 광고그룹을 짚는 Daily Comment, 소진·효율 관점의 Weekly Comment,
  예산·소진율·진행율과 목표(e.*)·달성률을 담은 Total/Monthly Summary, 월·미디어 필터로 보는 Product·Target·Placement·Weekly·Daily 표
  (디멘전·지표 설정, 접기), 예산·단가를 입력해 예상 성과를 보는 Mix 계획표를 담은 HTML 보고서. 사용자가 말한 브랜드의 차원·지표를 실행 시작에 디스커버리해서 어떤 브랜드에도 같은 방식으로 동작한다.
metadata:
  version: "1.2.1"
---

> ⚡ **thinking 지침**: thinking은 최대한 짧게 유지한다. 바로 MCP 호출 → 스크립트 실행 → 완료 순서로 진행한다.

## 역할

MCP 데이터를 받아 **TBWA 보고서**(HTML 한 파일)로 렌더링한다.

- **브랜드 비종속**: 사용자가 말한 브랜드명을 모든 MCP 호출의 `brand_name`과 제목·파일명에 그대로 쓴다.
- **기간**: 기준일 D(없으면 오늘, KST), 데이터 마지막 날 **E = D-1**. 집계 기간 = **시작일 S ~ E**.
  S = 사용자가 말한 시작일, 말하지 않으면 **E의 전월 1일**. S~E가 걸친 달(첫 달은 S부터, 마지막 달은 E까지)마다
  Monthly Summary·월 필터·Mix 월 칸이 생긴다. 기간은 366일까지(get_ad_performance 상한).
- **차원**: 브랜드가 제공하는 차원만 쓴다(차원 확인 1회). **없는 차원(예: 상품·노출 위치)은 호출에도 넣지 않고, 보고서에도
  조용히 나오지 않는다** — 사용자에게 묻거나 에러로 멈추지 않는다.
- **예산·목표**: `get_target_progress_v2`의 cost 행 = 예산(**Gross**), impression·click·views·ctr·vtr·cpm·cpc·cpv 행 = 목표 영역(e.*)·Mix 목표.
  단위는 전체·매체·캠페인(대시보드 브랜드)까지다. 행이 없는 칸은 빈칸이다(묻지 않는다).
- **Comment는 빌더가 규칙으로 쓴다** — 모델이 요약 문장을 쓰지 않는다(`tbwa-report-section-1-comment.md`).
- 도구 규칙: `shared/references/mcp-tools.md`, 차원 확인·크기 대응: `shared/references/pivot-table.md`
  (플러그인 루트 기준 — 이 스킬 폴더에서는 `../../shared/references/`).

## 데이터 처리 원칙 (절대 지침)

> 🚫 **MCP 응답은 이미 정제가 끝난 최종 데이터다 — 원문 그대로 빌더에 넘긴다.** 옮겨 적기·합산·재계산·추정 금지.
> 표의 묶음 값(미디어·상품·주·월 합, CTR·CPM·CPC·CPV·VTR)은 브라우저가 원자 지표(광고비·노출·클릭·조회수)로 계산한다.
>
> 🚫 표 데이터 응답을 못 받으면 빌더 입력에서 `data`를 빼서 "데이터 준비 중"으로 둔다.

## 실행 방식 절대 지침

> 🧩 **응답을 빌더에 넘기는 규칙**
> 1. 이 플러그인의 PostToolUse 훅이 `group_by`가 있는 `get_ad_performance`의 큰 응답을 파일로 저장하고,
>    모델에게는 `[laighthouse-capture-hook] ... 저장됨: <경로>` 스텁만 보여 준다 → 그 **경로**를 `json_files`에 넣는다.
>    스텁이 가리키는 파일을 Read로 열어 컨텍스트로 가져오지 않는다.
> 2. 스텁 없이 원본 JSON 봉투가 그대로 온 작은 응답은 **한 글자도 바꾸지 않고** 문자열로 `json`에 넣는다(혼용 가능).
>    🚫 값만 골라 옮겨 적기, 봉투를 새로 조립하기, 다른 호출의 값을 재사용하기는 전부 금지다.
> 3. 빌더 입력 JSON은 파일로 만들고(Write) 경로를 인자로 넘긴다: `python3 assets/build_report.py <build.json 경로>`.

- 렌더링은 **미리 검증된 asset 스크립트**만 한다(`.py`/`.js` 신규 작성, HTML 직접 작성 금지).
  - `assets/discover.py` — 매체별 일별 응답(파일 경로 또는 stdin) → `metric_keys`/`currency`/`missing`.
  - `assets/build_report.py` — 봉투·목표 원문 → 최종 HTML 1개(Comment 생성 포함). 입력 스키마는 docstring.

> ℹ️ 이 호스트의 Bash 기본 셸은 `sh`(dash)일 수 있다 — bash 전용 문법은 쓰지 않는다. `python3`이 없으면 `python`으로 부른다.

## 입력 파라미터

| 파라미터 | 설명 | 예시 |
|---|---|---|
| brand_name | 사용자가 말한 브랜드명 그대로 | acme |
| 기준 일자 | `target_date`(D). 없으면 오늘(KST). 데이터는 D-1(E)까지 | 2026-10-08 |
| 시작 일자 | `start_date`(S). 없으면 E의 전월 1일 | 2026-07-15 |

## 실행 순서

1. 파라미터를 파싱한다. E = D-1, S(시작일, 없으면 E의 전월 1일), 그리고 S~E가 걸친 달 목록(첫 달은 S부터, 마지막 달은 E까지)을 계산한다.
2. **차원 확인 + 매체별 일별 (한 메시지에 동시 2회)**:
   - `get_ad_performance`(S ~ E, `time_grain:"total"`, `group_by:["__list_dimensions__"]`, `metrics:[]`) → 에러 메시지의
     차원 목록에서 FINE_DIMS를 정한다(`pivot-table.md` 1절 — 목록에 없는 차원은 넣지 않는다).
   - `get_ad_performance`(S ~ E, `time_grain:"day"`, `group_by:["media"]`, `metrics` 생략) → `python3 assets/discover.py <파일 경로>`
     (스텁 없이 원본이 왔으면 stdin으로). `missing`이 있으면 사용자에게 한 번에 묻는다. 매체 목록도 여기서 얻는다.
3. **데이터 호출을 한 메시지에 동시 발사** (`metrics`·`filters` 생략):
   - 표 데이터: `time_grain:"day"`, `group_by` = FINE_DIMS — **달마다 1회**(첫 달은 S부터, 마지막 달은 E까지 — 겹치지 않게 나눠 받는다).
     크기 오류면 `ad_name` → `ad_group_name` 순으로 빼고 다시 받는다(`pivot-table.md` 2절).
   - Placement 데이터: **차원 목록에 노출 위치 차원(`placement`·`노출위치`·`노출 위치`·`노출_위치`·`position` 중 처음 것)이 있을 때만** —
     `time_grain:"day"`, `group_by` = `["media", (ad_type 또는 상품 중 있는 것), 노출 위치 차원]`, 달마다 1회(표 데이터와 같은 기간 나눔).
     없으면 부르지 않는다(표가 조용히 빠진다).
   - 예산·목표: `get_target_progress_v2` — `month` = 걸친 달마다, `cost_metric` = `metric_keys.cost`,
     `as_of_date` = 지난 달은 그 달 말일, 마지막 달은 E. **달마다 `media` 생략 1회**(응답 둘째 표에 매체·캠페인 행이 모두 온다 —
     매체마다 따로 부르지 않는다). 한 줄 메시지·에러는 "목표 없음"(원문 그대로, 에러면 빈 문자열).
4. **빌드**: `build.json`을 Write로 만들고 빌더 1회. `out` = `~/Downloads/laighthouse-reports/{브랜드명}_tbwa_{기준_일자}.html`
   (디렉터리는 빌더가 만든다). 빌더가 "대조 검증 실패"로 멈추면 매체별 일별 응답을 원문 그대로 다시 넣거나 다시 조회한다
   (값을 고쳐 맞추지 않는다).
5. 완성된 HTML을 낸다 — 빌더가 위 경로에 저장했다. 채팅에서 보여 줄 수 있는 호스트(Artifact 등)면 그 파일로 게시한다.
6. 완료 메시지는 아래 형식 그대로.

## 빌더 입력 (build.json)

```json
{"out": "~/Downloads/laighthouse-reports/acme_tbwa_2026-10-08.html", "brand": "acme", "target_date": "2026-10-08",
 "start_date": "2026-07-15",   ← 사용자가 시작일을 말했을 때만
 "metric_keys": {...}, "currency": "₩",
 "dims": "<차원 확인 에러 메시지 원문>",
 "data": {"json_files": ["<첫 달 표 데이터 파일>", "<다음 달 표 데이터 파일>", ...]},
 "media": {"json_files": ["<매체별 일별 파일>"]},
 "place": {"json_files": ["<첫 달 Placement 파일>", ...]},   ← 노출 위치 차원이 있을 때만
 "budgets": [{"month": "2026-09", "target_progress": "<첫 달 원문>"},
             {"month": "2026-10", "target_progress": "<다음 달 원문>"}]}   ← 걸친 달마다 1개
```

- 스텁(파일)으로 온 응답은 `json_files`, 원본이 그대로 온 응답은 `json`(문자열 또는 문자열 배열)에 넣는다.
- `budgets[].target_progress`는 응답 원문 전체(두 표 모두)를 그대로 넣는다 — 빌더가 둘째 표의 매체·캠페인 행을 범위별 목표로 읽는다.

## 완료 메시지 형식

```
{브랜드명} TBWA 보고서({기준_일자}) 생성 완료.
가장 인상적인 부분: {Daily/Weekly Comment에서 고른 한 문장}.
— by LaightAI
```

## 섹션 구성 (고정)

| 순서 | 섹션 | 파일 |
|---|---|---|
| 1 | Daily Comment · Weekly Comment (빌더 규칙 생성) | `tbwa-report-section-1-comment.md` |
| 2 | Total Summary · Monthly Summary (필터 미적용, 예산·목표 영역) | `tbwa-report-section-2-summary.md` |
| 3 | 월·미디어 필터 + Product · Target · Placement · Weekly · Daily 표 | `tbwa-report-section-3-tables.md` |
| 4 | Mix (목표 입력값 기준 월별 계획 — 예산·CPM·CPC·VTR 입력 → 예상 노출·클릭·조회) | `tbwa-report-section-4-mix.md` |

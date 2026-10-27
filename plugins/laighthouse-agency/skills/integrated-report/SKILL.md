---
name: integrated-report
description: >
  종합 리포트 생성 스킬. "종합 리포트", "종합 보고서", "integrated report" 요청 시 사용.
  시작일(기본: 전월 1일)부터 어제까지를 한 화면에 담는다 — 전일 대비 급감 광고그룹을 짚는 Daily Comment, 소진·효율 관점의 Weekly Comment,
  예산·소진율·진행율과 목표(e.*)·달성률을 담은 Total/Monthly Summary, 월·미디어 필터로 보는 Product·Target·Placement·Weekly·Daily 표
  (디멘전·지표 설정, 접기), 예산·단가를 입력해 예상 성과를 보는 Mix 계획표를 담은 HTML 보고서와, 같은 내용을 시트로 나눈
  엑셀(.xlsx — Summary·By Media·By Date·Mix·Raw)을 함께 만든다. 사용자가 말한 브랜드의 차원·지표를 실행 시작에 디스커버리해서 어떤 브랜드에도 같은 방식으로 동작한다.
metadata:
  version: "1.4.0"
---

> ⚡ **thinking 지침**: thinking은 최대한 짧게 유지한다. 바로 MCP 호출 → 스크립트 실행 → 완료 순서로 진행한다.

## 역할

MCP 데이터를 받아 **종합 리포트**(HTML 한 파일 + 같은 폴더·같은 이름의 엑셀 `.xlsx`)로 렌더링한다.
빌더 1회 호출이 둘 다 만든다 — 엑셀을 따로 부르거나 수치를 옮겨 적지 않는다.

- **브랜드 비종속**: 사용자가 말한 브랜드명을 모든 MCP 호출의 `brand_name`과 제목·파일명에 그대로 쓴다.
- **기간**: 기준일 D(없으면 오늘, KST), 데이터 마지막 날 **E = D-1**. 집계 기간 = **시작일 S ~ E**.
  S = 사용자가 말한 시작일, 말하지 않으면 **E의 전월 1일**. S~E가 걸친 달(첫 달은 S부터, 마지막 달은 E까지)마다
  Monthly Summary·월 필터·Mix 월 칸이 생긴다. 기간은 366일까지(get_ad_performance 상한).
- **차원**: 브랜드가 제공하는 차원만 쓴다(차원 확인 1회). **없는 차원(예: 상품·노출 위치)은 호출에도 넣지 않고, 보고서에도
  조용히 나오지 않는다** — 사용자에게 묻거나 에러로 멈추지 않는다.
- **예산·목표**: `get_target_progress_v2`의 cost 행 = 예산(**Gross**), impression·click·views·ctr·vtr·cpm·cpc·cpv 행 = 목표 영역(e.*)·Mix 목표.
  단위는 전체·매체·캠페인(대시보드 브랜드)까지다. 행이 없는 칸은 빈칸이다(묻지 않는다).
- **Comment는 빌더가 규칙으로 쓴다** — 모델이 요약 문장을 쓰지 않는다(`integrated-report-section-1-comment.md`).
- 도구 규칙: `shared/references/mcp-tools.md`, 차원 확인·크기 대응: `shared/references/pivot-table.md`
  (플러그인 루트 기준 — 이 스킬 폴더에서는 `../../shared/references/`).

## 데이터 처리 원칙 (절대 지침)

> 🚫 **MCP 응답은 이미 정제가 끝난 최종 데이터다 — 원문 그대로 빌더에 넘긴다.** 옮겨 적기·합산·재계산·추정 금지.
> 표의 묶음 값(미디어·상품·주·월 합, CTR·CPM·CPC·CPV·VTR)은 브라우저가 원자 지표(광고비·노출·클릭·조회수)로 계산한다.
>
> 🚫 표 데이터 응답을 못 받으면 빌더 입력에서 `data`를 빼서 "데이터 준비 중"으로 둔다.

## 실행 방식 절대 지침

> 🧩 **응답을 빌더에 넘기는 규칙**
> 1. 플러그인 저장 훅이 응답 원본을 파일로 남긴다 — `assets/prepare.py`가 그 파일로 빌더 입력(build.json)을 만든다.
>    응답 원문(봉투·목표 표)을 직접 옮겨 적지 않는다. 캡처 훅 스텁(`[laighthouse-capture-hook] ... 저장됨`)도 무시해도 된다.
> 2. 모델이 빌더에 직접 넣는 것은 차원 확인 에러 메시지 원문(`dims`)뿐이다.
> 3. 저장 훅이 없는 호스트(prepare.py가 `note`)에서만 예전 방식대로 build.json을 직접 만든다: 스텁 경로는 `json_files`에,
>    원본이 그대로 온 작은 응답은 **한 글자도 바꾸지 않고** `json`에 넣는다. build.json은 Write로 만들고 경로를 인자로 넘긴다.
>    🚫 값만 골라 옮겨 적기, 봉투를 새로 조립하기, 다른 호출의 값을 재사용하기는 전부 금지다.

- 렌더링은 **미리 검증된 asset 스크립트**만 한다(`.py`/`.js` 신규 작성, HTML 직접 작성 금지).
  - `assets/discover.py` — 저장 훅이 없을 때만: 매체별 일별 응답(파일 경로 또는 stdin) → `metric_keys`/`currency`/`missing`.
  - `assets/prepare.py` — 저장된 응답 → build.json(매체별 일별·월별 표 데이터·Placement·월별 목표 원문), `--build`면 빌더까지.
  - `assets/build_report.py` — 봉투·목표 원문 → 최종 HTML 1개(Comment 생성 포함) + 같은 이름의 `.xlsx` 1개. 입력 스키마는 docstring.
  - `assets/integrated_xlsx.py` — 빌더가 import 한다(직접 부르지 않는다). 표준 라이브러리만으로 엑셀을 쓴다(openpyxl 불필요).

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
   - `get_ad_performance`(S ~ E, `time_grain:"day"`, `group_by:["media"]`, `metrics` 생략)

   **광고비 지표 키**(`metric_keys.cost`, 목표 호출의 `cost_metric`) = 응답(또는 캡처 스텁)의 `metrics` 목록에서 `광고비`·`cost`·`spend`·`spending` 중
   처음 있는 것(대소문자 무시, 정확히 같은 이름만). 없을 때만 사용자에게 묻는다 — 스크립트를 따로 돌리지 않는다.
3. **데이터 호출을 한 메시지에 동시 발사** (`metrics`·`filters` 생략):
   - 표 데이터: `time_grain:"day"`, `group_by` = FINE_DIMS — **달마다 1회**(첫 달은 S부터, 마지막 달은 E까지 — 겹치지 않게 나눠 받는다).
     크기 오류면 `ad_name` → `ad_group_name` 순으로 빼고 다시 받는다(`pivot-table.md` 2절). 서버의 5만 행 오류뿐 아니라
     호스트가 응답을 못 읽었다는 오류(예: "larger than 16MB")도 크기 오류다 — 그 응답은 저장되지 않으므로 바로 다시 받는다.
   - Placement 데이터: **차원 목록에 노출 위치 차원(`placement`·`노출위치`·`노출 위치`·`노출_위치`·`position` 중 처음 것)이 있을 때만** —
     `time_grain:"day"`, `group_by` = `["media", (ad_type 또는 상품 중 있는 것), 노출 위치 차원]`, 달마다 1회(표 데이터와 같은 기간 나눔).
     없으면 부르지 않는다(Placement 자리에 '노출 위치 데이터 준비 중' 안내가 나온다 — 사용자에게 묻지 않는다).
   - 예산·목표: `get_target_progress_v2` — `month` = 걸친 달마다, `cost_metric` = `metric_keys.cost`,
     `as_of_date` = 지난 달은 그 달 말일, 마지막 달은 E. **달마다 `media` 생략 1회**(응답 둘째 표에 매체·캠페인 행이 모두 온다 —
     매체마다 따로 부르지 않는다). 한 줄 메시지·에러는 "목표 없음"(원문 그대로, 에러면 빈 문자열).
4. **빌드 입력 준비 + 빌드 (1회)**: 응답 원문을 `build.json`에 옮겨 적지 않는다 — 플러그인 저장 훅(`hooks/save_responses.py`)이
   2·3단계 응답 원본을 파일로 남겨 두었다. prepare.py가 빌더까지 부른다 — 차원 확인 에러 메시지 원문만 stdin으로 넣는다:
   ```
   python3 assets/prepare.py --brand <브랜드> --target-date <D> [--start-date <S>] --build <<'PYEOF'
   <차원 확인 에러 메시지 원문>
   PYEOF
   ```
   → 출력의 `build`가 빌더 출력이다. `missing`(다시 보낼 호출)이 있으면 빌드하지 않는다 — 그 호출만 다시 보내고 재실행한다
   (`errors`는 그 응답이 에러였다는 뜻). `build_error`는 빌더가 멈춘 이유다. `discover.metrics_absent`는 브랜드가 주지 않는 지표라 묻지 않는다.
   `out`은 `~/Downloads/laighthouse-reports/{브랜드명}_integrated_{기준_일자}.html`(base에 들어 있다 — 바꿀 때만 `"out"`을 함께 넣는다).
   엑셀은 같은 폴더의 `{브랜드명}_integrated_{기준_일자}.xlsx` — 출력의 `xlsx`가 그 경로다. `xlsx_error`(예: 같은 파일이 엑셀에 열려 있음)면
   HTML은 정상이다 — 다시 부르지 말고 완료 메시지에 이유를 한 줄로 적는다(파일을 닫고 다시 만들 수 있다고 안내).
   빌더가 "대조 검증 실패"로 멈추면 매체별 일별 응답을 다시 조회하고 prepare.py부터 다시 한다(값을 고쳐 맞추지 않는다).
   prepare.py가 `note`(저장된 응답 없음)를 내면 저장 훅이 없는 호스트다 → 아래 「빌더 입력 (build.json)」대로 직접 만든다.
5. 완성된 HTML을 낸다 — 빌더가 위 경로에 저장했다. 채팅에서 보여 줄 수 있는 호스트(Artifact 등)면 그 파일로 게시한다.
   엑셀은 경로만 알린다(게시하지 않는다).
6. 완료 메시지는 아래 형식 그대로.

## 빌더 입력 (build.json) — 저장 훅이 없는 호스트에서만 직접 만든다

```json
{"out": "~/Downloads/laighthouse-reports/acme_integrated_2026-10-08.html", "brand": "acme", "target_date": "2026-10-08",
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
{브랜드명} 종합 리포트({기준_일자}) 생성 완료.
엑셀: {xlsx 경로} (Summary · By Media · By Date · Mix · Raw)
가장 인상적인 부분: {Daily/Weekly Comment에서 고른 한 문장}.
— by LaightAI
```

엑셀이 없으면 `엑셀:` 줄에 경로 대신 `만들지 못함 — {xlsx_error 또는 xlsx_note}`를 적는다.

## 엑셀 시트 구성 (빌더가 HTML과 같은 데이터·같은 규칙으로 만든다)

| 시트 | 내용 |
|---|---|
| Summary | Total Summary · Monthly Summary(기본 영역 + 목표 영역) · Daily/Weekly Comment |
| By Media | Product · Target · Creative(소재 차원이 있을 때) · Placement(없으면 '준비 중' 안내) |
| By Date | Weekly · Daily (나란히) |
| Mix | 목표 초기값 기준 계획표 — 월 예산·CPM·CPC·VTR(파란 글씨)은 값, 예산·예상치·묶음 행은 수식(고치면 다시 계산) |
| Raw | 표 데이터 원자 행(일 × 차원 × 비용·노출·클릭·조회) — 필터·피벗용 |

- 묶음 행의 CTR·CPM·CPC·CPV·VTR은 원자 지표 합으로 다시 계산한다(HTML과 같다). 화면의 `외 N개` 접기 없이 모든 행이 들어간다.
- 필터는 초기 상태(전체 월·전 매체), 디멘전은 기본 설정(Summary: 미디어 → 상품 → 광고 그룹)이다.

## 섹션 구성 (고정)

| 순서 | 섹션 | 파일 |
|---|---|---|
| 1 | Daily Comment · Weekly Comment (빌더 규칙 생성) | `integrated-report-section-1-comment.md` |
| 2 | Total Summary · Monthly Summary (필터 미적용, 예산·목표 영역) | `integrated-report-section-2-summary.md` |
| 3 | 월·미디어 필터 + Product · Target · Placement · Weekly · Daily 표 | `integrated-report-section-3-tables.md` |
| 4 | Mix (목표 입력값 기준 월별 계획 — 예산·CPM·CPC·VTR 입력 → 예상 노출·클릭·조회) | `integrated-report-section-4-mix.md` |

# laighthouse-agency

라이트하우스 MCP 연동 데이터를 대행사 양식 보고서(HTML)로 렌더링하는 Claude 플러그인입니다.

## 설치

```
/plugin install laighthouse-agency --marketplace laight-ai/laighthouse-plugin-agency
```

## 컴포넌트

| 유형 | 이름 | 설명 |
|------|------|------|
| MCP | laighthouse | `https://app.laight.ai/api/mcp` 연동 |
| 훅 | save_responses | laighthouse 응답 원본을 파일로 남긴다 — 각 스킬의 `assets/prepare.py`가 빌더 입력을 만든다 |
| 훅 | capture_ad_performance | `get_ad_performance`의 큰 응답을 파일로 저장하고 경로만 모델에 보여 준다(재타이핑 방지) |
| 훅 | capture_change_raw | `list_campaign_change_raw`(변경 이력 원본) 응답을 건수와 `next_cursor`만 보이게 바꾼다 |
| 스킬 | overall-summary | 종합 리포트(HTML) + 같은 이름의 엑셀(.xlsx) 렌더링 |
| 스킬 | overall-summary-comment · -total · -tables · -history · -mix | 종합 리포트에서 섹션 하나만 뽑기(Comment / Total·Monthly Summary / Product·Target·Placement·Weekly·Daily 표 / Campaign History / Mix) |
| 스킬 | daily-report · weekly-report · monthly-report | Daily·Weekly·Monthly 보고서(HTML) 렌더링 |

## 사용법

> "breezm 종합 리포트 만들어줘" → `overall-summary`
> "breezm 종합 리포트 7월 15일부터" → 시작일 지정(기본: 전월 1일, 366일까지)

> 모든 보고서의 날짜는 **데이터 마지막 날**이다(기본 어제). 오늘 이후 날짜로는 만들 수 없다.
> "breezm 종합 리포트 Mix만" → `overall-summary-mix` (Comment·Summary·표도 같은 식 — `overall-summary-comment`·`-total`·`-tables`)
> "breezm 종합 리포트 Product랑 Daily 표만" → `overall-summary-tables` (고른 표만)
> "breezm 캠페인 변경 이력만" → `overall-summary-history` (매체 변경 기록 → 일·미디어·대상·변경 사항 표)

> "breezm 데일리 보고서" → `daily-report` (기준일 기본: 어제)
> "breezm 주간 보고서" → `weekly-report` (기준일 = 데이터 마지막 날, 기본: 어제)
> "breezm 9월 월간 보고서" → `monthly-report` (대상 월 기본: 지난달)

### Daily · Weekly · Monthly 보고서 구성

| 스킬 | 섹션 |
|---|---|
| daily-report | 일간 성과 요약(기본 8 KPI — 광고비·노출·클릭·CTR·VTR·조회수·CPM·CPV, 지표 메뉴로 추가·해제, 전일/전주 동요일) · Daily Summary(캠페인·광고그룹·광고 단위 급변 모니터링) · 매체별 최근 7일 추이(지표 드롭다운) · 성과 비교 표 |
| weekly-report | 월 누적 성과 요약(기본 8 KPI, 목표가 있으면 진척도 · 예산 소진율 등은 지표 메뉴) · Weekly Summary(소진·효율, 매체-캠페인) · 매체별 최근 5주 추이(지표 드롭다운) · 주간 성과 비교 표 |
| monthly-report | 예산 소진율 + 7 KPI(지표 메뉴로 추가·해제) · Executive Summary(소진·효율) · 6개월 추이(광고비 + 꺾은선 지표 선택) · 매체별 추이(지표 드롭다운) · 매체 비교(지표 메뉴) · 예산·목표 달성 표(매체-캠페인) |

- 호출은 두 번에 나눠 동시에 보낸다(차원 확인이 끝나야 표 데이터 차원이 정해진다). 응답 원문은 저장 훅 → `prepare.py`가
  빌더 입력과 요약 근거(`digest`)로 바꾼다 — 모델은 요약 문장만 쓴다.
- Chart.js는 `shared/assets/chart.umd.min.js` 한 벌을 HTML에 인라인한다(오프라인에서도 열린다).

### 종합 리포트 구성

1. **Daily Comment · Weekly Comment** — 전일 대비 급감 광고그룹, 소진·효율 관점 요약(빌더가 규칙으로 작성)
2. **Total Summary · Monthly Summary** — 미디어 → 디멘전 계층, 예산·소진율·진행율 + 목표 영역(e.* 목표·달성률)
3. **월·미디어 필터 + Product · Target · Placement · Weekly · Daily 표**
   - Placement는 브랜드가 노출 위치 차원(`placement` 등)을 제공할 때만 나온다.
4. **Mix** — 월 예산·CPM·CPC·VTR을 입력해 예상 노출·클릭·조회를 보는 계획표(입력값은 브라우저에 저장)

모든 표: 디멘전·지표 설정(선택·순서), ▼/▶ 접기와 `펼침` 단계 버튼, 엑셀로 복사(시트 아이콘·Ctrl+C), 오른쪽 목차.

### 엑셀 파일 (.xlsx)

HTML과 같은 폴더에 같은 이름의 `.xlsx`가 함께 생긴다(`~/Downloads/laighthouse-reports/{브랜드}_overall_summary_{기준일}.xlsx`).
빌더 1회 호출이 HTML과 같은 데이터·같은 계산 규칙으로 만든다 — 추가 MCP 호출·수치 옮겨 적기 없음, openpyxl 등 설치 불필요.

| 시트 | 내용 |
|---|---|
| Summary | Total Summary · Monthly Summary(예산·소진율·목표 영역) · Daily/Weekly Comment |
| By Media | Product · Target · Creative(소재 차원이 있을 때) · Placement |
| By Date | Weekly · Daily |
| Mix | 계획표 — 월 예산·CPM·CPC·VTR(파란 글씨)을 고치면 예상치가 수식으로 다시 계산된다 |
| Raw | 표 데이터 원자 행(일 × 차원) — 필터·피벗용 |

엑셀 생성이 실패해도(예: 같은 파일이 엑셀에 열려 있음) HTML 보고서는 그대로 만들어진다.

### 브랜드 비종속 동작

- 실행 시작에 차원 목록을 확인하고, 지표 키는 첫 응답의 지표 목록에서 정한다(prepare.py가 같은 규칙으로 다시 확인). 브랜드가 제공하지 않는 차원(상품·노출 위치 등)은
  묻지 않고 보고서에서 조용히 빠진다.
- 예산·목표는 `get_target_progress_v2`(전체·매체·캠페인 단위)에서 읽는다. 목표가 없으면 빈칸이다.
- 렌더링 부품은 공용 킷 `shared/assets/report_kit.*`와 스킬의 `assets/overall_summary.js`에 있다.

## 요약 가이드 (비개발자 편집)

Daily·Weekly·Monthly 요약 문단을 **무엇을 어떻게 쓸지**는 스킬마다 `guides/`의 파일이 정한다. 이 파일들은 노션 페이지의 사본이다 —
비개발자는 노션에서 고치고, 개발자가 Claude에게 **"노션 가이드 반영해줘"**라고 요청해 레포로 가져온다.

- 노션: [프롬프트 및 레포트 라이브러리 › TBWA 리포트 스킬](https://app.notion.com/p/40760c83bb7e81548812f6ecf1fca3af) › "TBWA: 요약 가이드 라이브러리" DB

| 가이드 | 레포 파일 | 노션 |
|---|---|---|
| Daily Summary | `skills/daily-report/guides/daily-summary.md` | [링크](https://app.notion.com/p/40760c83bb7e814a973ad9803168fcd6) |
| Weekly Summary | `skills/weekly-report/guides/weekly-summary.md` | [링크](https://app.notion.com/p/40760c83bb7e8144a8b3cda1029e3893) |
| Executive Summary (Monthly) | `skills/monthly-report/guides/executive-summary.md` | [링크](https://app.notion.com/p/40760c83bb7e81888aa3f5ca1ded7618) |

**반영 절차** (Claude가 한다)

1. DB에서 `현재 버전` ≠ `레포 반영 버전`인 행을 찾는다.
2. 그 페이지의 "🟢 현재 가이드" 코드 블록 내용을 그대로 레포 파일에 옮긴다 — 첫 줄 주석(원본 링크·버전·날짜)만 새 버전으로 바꾼다.
   코드 블록 밖의 메모는 옮기지 않는다.
3. 홈키파 등 저장된 build.json의 `digest`로 고치기 전·후 가이드에 따라 요약을 한 번씩 써서 나란히 보여 준다.
4. 브랜치·PR을 만들고(PR 본문에 노션 변경 사항), 머지 후 노션의 `레포 반영 버전`을 새 버전으로 바꾼다.

가이드에는 문구·작성 규칙만 둔다. 근거 데이터(`digest`)·빌더 입력 형식·실행 순서는 섹션 문서와 SKILL.md(개발자 담당)가 정한다.

## MCP 서버

- **이름**: laighthouse
- **타입**: HTTP (Streamable HTTP transport)
- **URL**: `https://app.laight.ai/api/mcp`
- **인증**: oauth2.1

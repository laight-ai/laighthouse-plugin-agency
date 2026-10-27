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
| 스킬 | overall-summary | 종합 리포트(HTML) + 같은 이름의 엑셀(.xlsx) 렌더링 |
| 스킬 | daily-report · weekly-report · monthly-report | Daily·Weekly·Monthly 보고서(HTML) 렌더링 |

## 사용법

> "breezm 종합 리포트 만들어줘" → `overall-summary`
> "breezm 종합 리포트 7월 15일부터" → 시작일 지정(기본: 전월 1일, 366일까지)

> "breezm 데일리 보고서" → `daily-report` (기준일 기본: 어제)
> "breezm 주간 보고서" → `weekly-report` (기준일 기본: 오늘, 데이터는 어제까지)
> "breezm 9월 월간 보고서" → `monthly-report` (대상 월 기본: 지난달)

### Daily · Weekly · Monthly 보고서 구성

| 스킬 | 섹션 |
|---|---|
| daily-report | 일간 성과 요약(7 KPI, 전일/전주 동요일) · Daily Summary · 매체별 최근 7일 추이 · 성과 비교 표 |
| weekly-report | 월 누적 예산 소진율·목표 진척도 · Weekly Summary(소진·효율) · 매체별 최근 5주 추이 · 주간 성과 비교 표 |
| monthly-report | 예산 소진율 + 7 KPI · Executive Summary · 6개월 추이 · 매체별 추이 · 매체 비교 · 예산·목표 달성 표 |

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

## MCP 서버

- **이름**: laighthouse
- **타입**: HTTP (Streamable HTTP transport)
- **URL**: `https://app.laight.ai/api/mcp`
- **인증**: oauth2.1

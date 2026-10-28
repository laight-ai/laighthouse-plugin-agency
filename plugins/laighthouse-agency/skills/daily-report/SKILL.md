---
name: daily-report
description: >
  브랜드 비종속 Daily 보고서 생성 스킬. "데일리 보고서", "일간 보고서", "daily 보고서" 요청 시 사용.
  기준일(D0)의 광고비·노출·클릭·CTR·조회수·CPM·CPV를 전일·전주 동요일과 비교하고, 매체별 최근 7일 추이와
  Dimension·지표를 골라 보는 성과 비교표를 보여주는 HTML 보고서. 사용자가 말한 브랜드의 차원·지표를 실행 시작에
  디스커버리해서 어떤 브랜드에도 같은 방식으로 동작한다.
metadata:
  version: "1.0.0"
---

> ⚡ **thinking 지침**: thinking은 최대한 짧게 유지한다. 바로 MCP 호출 → 스크립트 실행 → 완료 순서로 진행한다.

## 역할

MCP 데이터를 받아 **라이트하우스 Daily 보고서**(HTML 한 파일)로 렌더링한다. 주간은 `weekly-report`, 월간은 `monthly-report`.

- **브랜드 비종속**: 사용자가 말한 브랜드명을 모든 MCP 호출의 `brand_name`과 제목·파일명에 그대로 쓴다.
- **차원**: 브랜드가 제공하는 차원만 쓴다(차원 확인 1회). **없는 차원(예: 상품)은 호출에도 넣지 않고, 보고서에도
  조용히 나오지 않는다** — 사용자에게 묻거나 에러로 멈추지 않는다.
- **지표**: 상단 카드는 처음에 8개(광고비·노출·클릭·CTR·VTR·조회수·CPM·CPV — VTR은 서빙될 때만)가 켜지고 지표 메뉴로 더하고 뺀다. 추이 드롭다운·표는 ELT가 서빙하는 지표 전부다.
- 도구 규칙: `shared/references/mcp-tools.md`, 차원 확인·선택 표: `shared/references/pivot-table.md`
  (플러그인 루트 기준 — 이 스킬 폴더에서는 `../../shared/references/`).

## 데이터 처리 원칙 (절대 지침)

> 🚫 **MCP 응답은 이미 정제가 끝난 최종 데이터다 — 원문 그대로 빌더에 넘긴다.** 옮겨 적기·합산·재계산·추정 금지.
> 소계·전체 값은 상위 group_by 응답에서 빌더가 가져온다.
>
> 🚫 응답을 못 받은 섹션은 빌더 입력에서 그 `s*` 키를 빼서 "데이터 준비 중"으로 둔다. 비슷한 숫자 생성은 금지다.

## 실행 방식 절대 지침

> 🧩 **응답을 빌더에 넘기는 규칙**
> 1. 플러그인 저장 훅이 응답 원본을 파일로 남긴다 — `assets/prepare.py`가 그 파일로 빌더 입력(build.json)과 요약 근거(`digest`)를
>    만든다. 응답 원문을 직접 옮겨 적거나, 응답 파일을 Read로 열지 않는다. 캡처 훅 스텁(`[laighthouse-capture-hook] ... 저장됨`)도 무시해도 된다.
> 2. 모델이 빌더에 직접 넣는 것은 차원 확인 에러 메시지 원문(`dims`)과 Daily Summary(`s2`)뿐이다.
> 3. 저장 훅이 없는 호스트(prepare.py가 `note`)에서만 「저장 훅이 없을 때」대로 build.json을 직접 만든다.

- 렌더링은 **미리 검증된 asset 스크립트**만 한다(`.py`/`.js` 신규 작성, HTML 직접 작성 금지).
  - `assets/prepare.py` — 저장된 응답 → build.json + `digest`(전체·매체·매체-캠페인·광고그룹·광고의 D0·D1·D7 값과 변화) + 지표 키.
  - `assets/build_report.py` — build.json + `dims` + `s2` → 최종 HTML 1개. 입력 스키마는 docstring.
  - `assets/discover.py`·`assets/digest.py` — 저장 훅이 없을 때만 쓴다.

> ℹ️ 이 호스트의 Bash 기본 셸은 `sh`(dash)일 수 있다 — bash 전용 문법은 쓰지 않는다. `python3`이 없으면 `python`으로 부른다.

## 입력 파라미터

| 파라미터 | 설명 | 예시 |
|---|---|---|
| brand_name | 사용자가 말한 브랜드명 그대로 | acme |
| 기준 일자 | `target_date`(D0). 없으면 어제(KST) | 2026-09-20 |

## 실행 순서

1. 파라미터를 파싱한다. D1 = D0-1일, D7 = D0-7일.
2. **1차 호출 — 한 메시지에 동시 3회** (`get_ad_performance`, `metrics`·`filters` 생략):
   - 차원 확인: D7~D0, `time_grain:"total"`, `group_by:["__list_dimensions__"]`, `metrics:[]` → 에러 메시지의 차원 목록에서
     FINE_DIMS를 정한다(`pivot-table.md` 1절 — 목록에 없는 차원은 넣지 않는다).
   - s1: D7~D0, `time_grain:"day"`, `group_by` 생략
   - s3: D7~D0, `time_grain:"day"`, `group_by:["media"]` (차트는 최근 7일, D7은 전주 동요일 표 대조 검증용)
3. **2차 호출 — 1회**: s4 피벗 표 — D7~D0, `time_grain:"day"`, `group_by` = FINE_DIMS(빌더가 기준일·전일·전주 동요일 행만 쓴다).
   크기 오류(서버 5만 행·"larger than 16MB" 등)면 `ad_name` → `ad_group_name` 순으로 빼고 다시 받는다(`pivot-table.md` 2절).
4. **빌드 입력 준비**:
   ```
   python3 assets/prepare.py --brand <브랜드> --target-date <D0>
   ```
   → 출력의 `base`(build.json 경로)·`digest`. `missing`(다시 보낼 호출)이 있으면 그 호출만 다시 보내고 재실행한다(`errors`는
   그 응답이 에러였다는 뜻). `discover.metrics_absent`는 브랜드가 주지 않는 지표라 묻지 않는다 — 단 `cost`가 들어 있으면
   어떤 지표가 광고비인지 사용자에게 묻는다. `digest_error`(대조 검증 실패)면 그 응답을 다시 조회하고 prepare.py부터 다시 한다.
5. **Daily Summary 작성**: `digest` 수치만 근거로 `guides/daily-summary.md`(작성 규칙·예시)를 따라 `daily-report-section-2-summary.md` 형식의 불릿을 쓴다.
6. **빌드 1회**:
   ```
   python3 assets/build_report.py <<'PYEOF'
   {"base": "<prepare가 준 경로>", "dims": "<차원 확인 에러 메시지 원문>", "s2": {"bullets": [...]}}
   PYEOF
   ```
   `out`은 `~/Downloads/laighthouse-reports/{브랜드명}_daily_{기준_일자}.html`(base에 들어 있다 — 바꿀 때만 `"out"`을 함께 넣는다).
7. 완성된 HTML을 낸다 — 빌더가 위 경로에 저장했다. 채팅에서 보여 줄 수 있는 호스트(Artifact 등)면 그 파일로 게시한다.
8. 완료 메시지는 아래 형식 그대로.

## 저장 훅이 없을 때

prepare.py가 `note`를 내면 build.json을 Write로 직접 만들고 `python3 assets/build_report.py <build.json 경로>`로 부른다.
섹션 입력은 각 section 문서의 「빌더 입력」 형식이다 — 캡처 훅 스텁의 경로는 `json_files`에, 원본이 그대로 온 작은 응답은
**한 글자도 바꾸지 않고** `json`에 넣는다. `metric_keys`·`currency`는 `python3 assets/discover.py <s3 파일>` 출력 그대로,
Summary 근거는 `python3 assets/digest.py <build.json>` 출력이다.
🚫 값만 골라 옮겨 적기, 봉투를 새로 조립하기, 다른 호출의 값을 재사용하기는 전부 금지다.

## 완료 메시지 형식

```
{브랜드명} Daily 보고서({기준_일자}) 생성 완료.
가장 인상적인 부분: {한 문장 하이라이트}.
— by LaightAI
```

## 섹션 구성 (고정 4개)

| 순서 | 섹션 | 파일 | 빌더 키 |
|---|---|---|---|
| 1 | 일간 성과 요약 (고정 7 KPI, 전일/전주 동요일 토글) | `daily-report-section-1-kpi.md` | `s1` |
| 2 | Daily Summary | `daily-report-section-2-summary.md` | `s2` |
| 3 | 매체별 일별 추이 (최근 7일, 지표 드롭다운) | `daily-report-section-3-media-trend.md` | `s3` |
| 4 | 성과 비교 — Dimension·지표 메뉴 표(비교일 vs 기준일) | `daily-report-section-4-product-compare.md` | `s4` |

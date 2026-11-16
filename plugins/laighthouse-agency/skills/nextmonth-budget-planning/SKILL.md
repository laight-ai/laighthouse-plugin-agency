---
name: nextmonth-budget-planning
description: >
  월간 미디어믹스(M/M Optimizer) 결과 보고서 스킬. "미디어믹스 결과", "미디어믹스 돌려줘", "다음 달 예산 배분 제안", "다음 달 예산 계획",
  "media mix 결과 보여줘", "M/M Optimizer" 요청 시 사용. 제안받을 달의 매체별 예산 배분을 전월(기준 달) 실적으로 계산하는 job 을
  새로 실행하거나(조건 확인 후) 내가 실행한 job 목록에서 골라 결과를 받아, 라이트하우스 웹 결과 화면과 같은 모양의 HTML 보고서
  (요약 수치 · 매체별 요약 표)를 직접 작성한다.
metadata:
  version: "1.0.0"
---

> ⚡ **thinking 지침**: thinking은 최대한 짧게 유지한다. 조건 확인 → MCP 호출 → 계산 → HTML 작성 → 완료 순서로 진행한다.

## 역할

라이트하우스 MCP 의 미디어믹스 job 결과를 **라이트하우스 웹 결과 화면(`/m/media-mix/{jobId}`)과 같은 모양의 HTML 한 파일**로 직접 작성한다.
구성: 제목(제안 달) · 요청 조건 → 요약 수치 4개 → 매체별 요약(기준 달 현재까지 · 제안). 모양은 아래 「HTML 뼈대」를 따른다.
HTML 은 완료(`succeeded`)된 계산에만 만든다. 실패 · 취소 · 아직 계산 중이면 「완료 메시지 형식」의 채팅 메시지만 낸다.

## 데이터 처리 원칙 (절대 지침)

> 🚫 **숫자는 `get_media_mix_job` 응답의 `summary` 행 값만 쓴다.** 합계는 `media: "*"` 행이다 — 매체 행을 더해 합계를 만들지 않는다. 추정 · 다른 도구 값 섞기 금지.
>
> 🚫 **증감률 · 비중 · 효율 변환은 암산하지 않는다.** 응답의 `summary` 배열을 손으로 옮겨 적지 말고 배열째 `python3` 스크립트에 붙여 계산한 뒤, 그 출력을 HTML 에 넣는다.
>
> 🚫 job 을 새로 만드는 `create_media_mix_job` 은 **쓰기**다(1~수 분 계산이 돈다). 사용자가 조건을 확인하기 전에는 부르지 않는다.

## 입력

| 경우 | 사용자가 주는 것 |
|---|---|
| 이미 있는 결과 보기 | 브랜드 이름. job 은 B-0 에서 내가 실행한 job 목록에 번호를 매겨 보여 주고 번호(예: "5번")로 고르게 한다 |
| 새로 실행 | 브랜드 이름 + 아래 「새로 실행할 때 확인할 조건」 |

## 사용자에게 말할 때

사용자는 개발자가 아니다. job · 큐 · job id · 상태값(`pending`·`running` 등) · 도구 이름 · 상태를 다시 확인한다는 말은 하지 않는다.
계산 하나는 "미디어믹스 예산 계산"이라고 부른다. job id 는 보여 주지도, 달라고 하지도 않는다 — 이전 결과는 B-0 목록의 번호로 고른다.

| 때 | 이렇게 말한다 |
|---|---|
| 계산을 시작함(`created: true`) | 미디어믹스 예산 계산을 시작했습니다. 보통 몇 분 걸리고, 끝나면 바로 결과를 보여 드립니다. |
| 같은 조건의 계산이 이미 있음(`created: false`) | 같은 조건으로 시작한 미디어믹스 예산 계산이 이미 진행 중이라, 그 결과를 기다리겠습니다. |
| 시작하지 못함(`status: "failed"` 와 `error`) | 미디어믹스 예산 계산을 시작하지 못했습니다. 사유: {error 원문} |
| 기다리는 동안 | 따로 말하지 않는다. 사용자가 물으면 "아직 계산하는 중입니다." |
| 10분이 넘도록 끝나지 않음 | 계산이 평소보다 오래 걸립니다. 나중에 "미디어믹스 결과 보여줘"라고 하시면 목록에서 골라 보실 수 있습니다. |

## 실행 순서

### A. 새로 실행할 때

1. `list_media_mix_metrics(brand_name)` — 비용 지표 후보 `cost_metrics` 와 성과 지표 후보 `outcome_metrics` 를 따로 받는다(각 항목 `{name, unit}`. 운영자가 숨긴 지표는 빠진다). 서버가 예전 버전이라 `{name, unit}` 목록 하나만 돌려주면 그 목록을 두 쪽 후보로 함께 쓴다. 한쪽 후보가 비었거나 서로 다른 둘을 고를 수 없으면 묻지 말고 멈추고, 운영자가 미디어믹스 지표 설정을 고쳐야 한다고 전한다. 에러(권한 · 미디어믹스 꺼짐 · 마트 없음)는 그대로 전한다.
2. **조건을 사용자에게 한 번에 확인받는다** — 말하지 않은 값은 추측하지 않고 묻는다. 학습 방식 · VAT 처리 등 나머지는 서버가 기본값으로 정하므로 묻지 않는다.

   | 조건 | 인자 |
   |---|---|
   | 제안받을 달(예산을 배분할 달) | `target_month` (`YYYY-MM`). 그 전월(기준 달) 실적으로 계산한다. 예산은 그 달이 오기 전에 정하므로 기준 달이 아직 진행 중인 것이 보통이고, 그때는 그날까지의 실적을 쓴다 — 데이터가 덜 들어왔다거나 기준 달이 끝난 뒤에 돌리는 편이 정확하다는 말은 하지 않는다 |
   | 비용 지표 · 성과 지표 | `cost_metric` 은 1번 `cost_metrics` 에서, `outcome_metric` 은 `outcome_metrics` 에서 하나씩(서로 다른 둘. 도구 인자가 `revenue_metric` 인 예전 서버면 그 이름으로 넘긴다). 반대쪽 후보에만 있는 지표는 서버가 거절한다. 고를 수 있는 지표가 하나뿐인 쪽(반대쪽에서 고른 지표를 빼고 하나만 남을 때도)은 그 지표를 쓰고 묻지 않는다 — 대신 골랐다거나 후보가 하나뿐이라는 말도 하지 않는다 |
   | 제안받을 달의 예산(원, VAT 제외 Net) | `target_budget` |
3. 확인받으면 `create_media_mix_job(...)` 1회 → `id`. 「사용자에게 말할 때」대로 계산을 시작했다고 알린다.
   `created: false` 면 내가 같은 조건으로 이미 돌리고 있는 job 을 받은 것이다(그 표대로 알린다).
   `status: "failed"` 와 `error` 가 오면 계산을 시작하지 못한 것이다 — 사유를 전하고 멈춘다.
4. **끝날 때까지 기다린다**: `get_media_mix_job(brand_name, job_id)`(기본 인자)를 부르고, `status` 가
   `pending`·`running` 이면 `python3 -c "import time; time.sleep(20)"` 로 기다렸다가 다시 부른다. 보통 1~수 분 걸린다.
   10분이 넘도록 끝나지 않으면 「사용자에게 말할 때」대로 알리고 멈춘다(나중에 B 에서 목록으로 골라 결과를 볼 수 있다).
5. `succeeded`·`failed`·`canceled` 가 되면 B-1 부터 한다.

### B. 결과 보고서 만들기

0. A 를 거치지 않은 경우(이미 있는 결과 보기) 결과를 볼 job 을 정한다. 사용자는 목록의 **번호**로 고른다 — job id 를 보여 주거나 달라고 하지 않는다.
   - 이 대화에서 A 로 실행한 job 이면 그 id 를 쓴다. 사용자가 스스로 job id 를 줬으면 그대로 쓴다.
   - 도구 목록에 `list_media_mix_jobs` 가 없으면(이 조직에는 아직 열리지 않은 도구다) 부르지 말고, 이 대화에서 실행한 계산의 결과만 볼 수 있다고 알리고 멈춘다.
   - 이 대화에서 이미 목록을 보여 줬고 사용자가 그 번호를 말하면(예: "5번 보여줘") 그 목록의 그 번호 job 을 쓴다. 목록을 다시 부르지 않는다.
   - 아니면 `list_media_mix_jobs(brand_name)` 1회. 이 브랜드에서 **내가 실행한** job 이 최신순으로 온다(최대 50개, 결과 행 없음).
     다른 사람이 실행한 job 은 목록에 없고 열어 볼 수도 없다. 받은 순서대로 1번(가장 최근)부터 번호를 매긴다.
   - 사용자가 처음부터 번호를 말했으면(예: 지난번에 본 목록의 "5번") 그 번호의 행을 아래 표 한 줄로 보여 주고 이 계산이 맞는지 확인받는다 —
     그 사이 새로 실행한 계산이 있으면 번호가 뒤로 밀린다. 아니라고 하면 아래처럼 목록을 보여 준다.
   - 최근 10개를 아래 표로 보여 주고 번호로 하나를 고르게 한다. 찾는 계산이 없다고 하면 11번부터 나머지를 마저 보여 준다.
     번호가 목록보다 크거나 찾는 계산이 50개 안에 없으면 최근 50개까지만 볼 수 있다고 알린다. 사용자가 이미 달 · 예산 등을 말했으면 맞는 행을 짚어 확인만 받는다.
     고르기 전에는 다음으로 넘어가지 않는다. 목록이 비었으면 이 브랜드에서 실행한 미디어믹스가 없다고 알리고 A(새로 실행)를 제안한다.

     | 번호 | 제안받을 달 | 예산(원) | 비용 · 성과 지표 | 상태 | 실행 시각(KST) |
     |---|---|---|---|---|---|
     | 1 | `request.target_month` | `request.target_budget`(천 단위 쉼표) | `request.cost_metric` · `request.outcome_metric`(예전 서버는 `request.revenue_metric`) | `status` → `succeeded` 완료 · `running` 계산 중 · `pending` 대기 · `failed` 실패 · `canceled` 취소 | `created_at`(UTC)에 9시간을 더해 `MM-DD HH:mm`. 더해서 24시를 넘으면 날짜도 하루 넘긴다 |

   - 상태를 본다. 목록에서 고른 job 이 완료 · 실패 · 취소면 바로 1번으로 간다. job id 를 직접 받았거나 고른 job 이 대기 · 계산 중이면
     `get_media_mix_job(brand_name, job_id)`(기본 인자)로 상태를 본다. 에러(없는 job · 다른 사람의 job · 권한 등)가 오면 원문을 전하고 멈춘다.
     `pending`·`running` 이면 A-4 대로 끝날 때까지 기다린다. 10분이 넘으면 「사용자에게 말할 때」대로 알리고 멈춘다.
1. A-4 · B-0 에서 끝난 상태(`succeeded`·`failed`·`canceled`)의 `get_media_mix_job` 응답을 이미 받았으면 그대로 2번으로 간다. 아니면
   `get_media_mix_job(brand_name, job_id)`(기본 인자) **1회**. 배분 행(`include_allocation`) · 진단(`include_diagnostics`)은 보고서에 쓰지 않으니 켜지 않는다.
   에러(권한 · 없는 job 등)가 오면 원문을 전하고 멈춘다. `failed`·`canceled` 면 HTML 없이 4번으로 간다.
2. **계산**: 「표에 넣을 값」대로 `python3` 로 계산한다. `summary` 배열과 `request`·`outcome_unit` 은 응답에서 그대로 붙인다.
3. **HTML 작성**: 「HTML 뼈대」에 2번 결과를 채워 `~/Downloads/laighthouse-reports/{브랜드}_media-mix_{제안 달}_{id 앞 8자}.html` 로 저장한다(폴더가 없으면 만든다).
   채팅에서 보여 줄 수 있는 호스트(Artifact 등)면 그 파일로 게시한다.
4. 완료 메시지는 아래 형식 그대로. 하이라이트는 보고서에 넣은 `summary`(kind `optimized` · `current` 의 `media: "*"` 합계, 매체별 행)만 근거로 쓴다.
   성과(`outcome`)와 성과 ÷ 비용(`outcome_per_cost`)은 성과 지표 이름(`request.outcome_metric`)으로 부른다 — 성과 지표가 구매 수 같은 건수일 수 있으니 매출 · ROAS 라고 하지 않는다.

> ℹ️ 이 호스트의 Bash 기본 셸은 `sh`(dash)일 수 있다 — bash 전용 문법은 쓰지 않는다. `python3`이 없으면 `python`으로 부른다.

## 표에 넣을 값

`summary` 행은 `kind`(`current` 기준 달 실적 · `optimized` 제안. `draft` 는 쓰지 않는다) × `media`(`"*"` 는 그 kind 의 합계)이고,
`cost` · `outcome` · `outcome_per_cost`(성과 ÷ 비용, 비용이 0 이면 null)를 담는다. 기준 달은 `request.target_month` 의 전월이다.

- **매체 순서**: 제안(`optimized`) 비용이 큰 순, 같으면 이름순. 합계 행은 맨 아래. 매체 점 색은 이 순서대로
  `#4a7fe0` `#3f8f73` `#d08a2c` `#8a80e8` `#ef7a68` `#9fbcf3` `#81d0b0` `#f5bf79` `#b7b2f7` `#9aa3ad` 를 돌려 쓴다.
- **비용**: `₩` + 천 단위 쉼표(정수로 반올림). 값이 없으면 `–`.
- **성과 · 효율**: `outcome_unit` 으로 가른다. `{지표}` 는 `request.outcome_metric` 이다.

  | `outcome_unit` | 성과 칸 | 효율 열 이름 | 효율 칸 |
  |---|---|---|---|
  | `₩` · `KRW` · `원`(금액) | `₩1,234,567` | `{지표} ÷ 비용` | `outcome_per_cost × 100` 을 반올림한 정수 `%`(예: `342%`) |
  | 그 밖의 단위(건수) | 숫자 뒤에 단위(예: `1,234회`) | `{지표}당 비용` | `1 ÷ outcome_per_cost` 를 비용처럼 `₩` 로 |
  | 없음(`null` · 빈 값) | 단위 없이 숫자(예: `1,234`) | `{지표} ÷ 비용` | `outcome_per_cost` 를 유효숫자 세 자리(예: `0.0388`) |

- **열 머리글**: 첫 줄은 `매체`(두 줄 차지) · `{기준 달 M}월 현재까지`(3열) · `{제안 달 M}월 제안`(3열). 예: 제안 달이 `2026-12` 면 `11월 현재까지` · `12월 제안`.
  둘째 줄은 현재 쪽 `비용` · `{지표}` · `{효율 열 이름}`, 제안 쪽 `비용` · `예상 {지표}` · `{효율 열 이름}`.
- **증감**: 제안 쪽 세 칸마다 값 아래 줄에 같은 행 · 같은 열의 현재 값 대비 증감률을 쓴다. `(제안 − 현재) ÷ |현재| × 100` 을 소수 첫째 자리까지.
  - 효율 칸은 화면에 보이는 효율(건수 지표면 성과당 비용)을 반올림하기 전 값으로 계산한다.
  - 오르면 `▲ 12.3%` 빨강(`up`), 내리면 `▼ 4.5%` 파랑(`down`). 지표가 좋아졌는지와 관계없이 방향으로만 색을 정한다. `0.0%` 는 기호 · 색 없이 쓴다.
  - 현재 값이 0 이거나 없으면(제안에만 있는 매체 등) 증감 줄을 쓰지 않는다.
- **비중**: 매체 행의 제안 비용 칸에는 증감 줄 아래에 `비중 {제안 비용 ÷ 제안 합계 비용 × 100}%`(소수 첫째 자리)를 쓴다. 합계 행에는 쓰지 않는다.
- **요약 수치 4개**(합계 행 기준):
  1. `제안 예산 합계` — 제안 합계 비용. 아래 줄 `목표 ₩{target_budget} (Net)`, 제안 합계가 목표의 99.5% 미만이면 `{제안 ÷ 목표 × 100, 소수 첫째}% 배분` 도.
  2. `예상 {지표}` — 제안 합계 성과. 아래 줄 `모델 예측치`.
  3. `예상 {효율 열 이름}` — 제안 합계 효율. 아래 줄에 표와 같은 규칙의 증감과 `기준 달 대비`.
  4. `기준 달 실적 {효율 열 이름}` — 현재 합계 효율. 아래 줄 `비용 ₩{현재 합계 비용}`.
- **요청 조건**: 기준 달 `YYYY년 M월`, 목표 예산 `₩{target_budget}` + `VAT 제외 Net`, 지표 `{cost_metric} · {outcome_metric}`,
  요청 시각 `created_at`(UTC)에 9시간을 더한 `YYYY-MM-DD HH:mm`.

## HTML 뼈대

모양 · 클래스 · 색은 이대로 쓴다. `{…}` 를 채우고, 매체 행(`<tr>`)은 매체 수만큼 되풀이한다. 증감 · 비중 줄이 없으면 그 `<div>` 를 뺀다.

```html
<!doctype html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{브랜드} {YYYY년 M월} 예산 제안</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>
body{margin:0;background:#f5f6f8;color:#262c34;font:14px/1.5 'Pretendard Variable',Pretendard,-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif}
.page{max-width:1120px;margin:0 auto;padding:24px 24px 64px}
.head{display:flex;align-items:center;gap:12px;margin-bottom:16px}
h1{margin:0;font-size:24px;font-weight:700;letter-spacing:-.015em}
.badge{display:inline-flex;align-items:center;height:20px;padding:0 7px;border-radius:4px;font-size:12px;font-weight:600;color:#245c4a;background:#eef9f4;border:1px solid #b2e7d1}
dl{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;margin:0 0 20px}dt{color:#6b7683}dd{margin:0}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}
.kpi,.card{background:#fff;border:1px solid #e6e8ec;border-radius:12px;box-shadow:0 1px 2px rgba(23,27,33,.04)}
.kpi{padding:16px 18px}.k-label{color:#6b7683;font-size:13px}
.k-value{font-size:22px;font-weight:700;margin-top:4px;font-variant-numeric:tabular-nums}
.k-sub{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px;font-size:12px;color:#6b7683}
.card-head{display:flex;align-items:center;justify-content:space-between;padding:14px 20px;border-bottom:1px solid #e6e8ec}
.card-head h2{margin:0;font-size:16px}.note{font-size:12px;color:#6b7683}
.wrap{overflow-x:auto}table{width:100%;border-collapse:collapse}
th{font-weight:600;color:#4f5a66;background:#fafbfc;border-bottom:1px solid #dcdfe4;padding:9px 14px;white-space:nowrap;text-align:left}
td{border-bottom:1px solid #eef0f3;padding:11px 14px;vertical-align:top}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.g{border-left:1px solid #dcdfe4}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px}.media{font-weight:600}
.sub{font-size:12px;color:#6b7683}.up{color:#c93b3b;font-weight:600}.down{color:#2e5bd8;font-weight:600}
tr.total td{font-weight:700;background:#fafbfc;border-top:1px solid #dcdfe4;border-bottom:0}
</style></head><body><div class="page">
<div class="head"><h1>{YYYY년 M월} 예산 제안</h1><span class="badge">완료</span></div>
<dl><dt>기준 달</dt><dd>{YYYY년 M월}</dd><dt>목표 예산</dt><dd class="num" style="text-align:left">{₩목표} <span class="sub">VAT 제외 Net</span></dd>
<dt>지표</dt><dd>{cost_metric} · {outcome_metric}</dd><dt>요청 시각</dt><dd>{YYYY-MM-DD HH:mm}</dd></dl>
<div class="kpis">
<div class="kpi"><div class="k-label">제안 예산 합계</div><div class="k-value">{₩제안 합계}</div><div class="k-sub"><span>목표 {₩목표} (Net)</span><span>{n.n% 배분}</span></div></div>
<div class="kpi"><div class="k-label">예상 {지표}</div><div class="k-value">{제안 합계 성과}</div><div class="k-sub"><span>모델 예측치</span></div></div>
<div class="kpi"><div class="k-label">예상 {효율 열 이름}</div><div class="k-value">{제안 합계 효율}</div><div class="k-sub"><span class="up">▲ {n.n%}</span><span>기준 달 대비</span></div></div>
<div class="kpi"><div class="k-label">기준 달 실적 {효율 열 이름}</div><div class="k-value">{현재 합계 효율}</div><div class="k-sub"><span>비용 {₩현재 합계}</span></div></div>
</div>
<section class="card"><div class="card-head"><h2>매체별 요약</h2><span class="note">비용은 VAT 제외 Net 기준입니다.</span></div>
<div class="wrap"><table><thead>
<tr><th rowspan="2">매체</th><th colspan="3" class="g">{N}월 현재까지</th><th colspan="3" class="g">{M}월 제안</th></tr>
<tr><th class="num g">비용</th><th class="num">{지표}</th><th class="num">{효율 열 이름}</th><th class="num g">비용</th><th class="num">예상 {지표}</th><th class="num">{효율 열 이름}</th></tr>
</thead><tbody>
<tr><td><span class="dot" style="background:{매체 색}"></span><span class="media">{매체}</span></td>
<td class="num g">{현재 비용}</td><td class="num">{현재 성과}</td><td class="num">{현재 효율}</td>
<td class="num g">{제안 비용}<div class="sub up">▲ {n.n%}</div><div class="sub">비중 {n.n%}</div></td>
<td class="num">{제안 성과}<div class="sub down">▼ {n.n%}</div></td><td class="num">{제안 효율}<div class="sub up">▲ {n.n%}</div></td></tr>
<tr class="total"><td>합계</td><td class="num g">{현재 합계 비용}</td><td class="num">{현재 합계 성과}</td><td class="num">{현재 합계 효율}</td>
<td class="num g">{제안 합계 비용}<div class="sub up">▲ {n.n%}</div></td><td class="num">{제안 합계 성과}<div class="sub up">▲ {n.n%}</div></td><td class="num">{제안 합계 효율}<div class="sub down">▼ {n.n%}</div></td></tr>
</tbody></table></div></section>
</div></body></html>
```

## 완료 메시지 형식

```
{브랜드명} 미디어믹스 결과 보고서({제안 달}) 생성 완료.
가장 인상적인 부분: {한 문장 하이라이트}.
— by LaightAI
```

실패 · 취소된 계산이면 HTML 을 만들지 않고 아래를 쓴다(취소면 사유 자리에 `취소된 계산`).

```
{브랜드명} 미디어믹스 예산 계산({제안 달} 제안)이 완료되지 않았습니다.
사유: {error 원문}
— by LaightAI
```

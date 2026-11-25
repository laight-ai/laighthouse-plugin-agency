---
name: nextmonth-budget-planning
description: >
  다음 달 예산 계획(M/M Optimizer) 스킬. "다음 달 예산 계획", "다음 달 예산 배분 제안", "미디어믹스 돌려줘", "미디어믹스 결과",
  "media mix 결과 보여줘", "M/M Optimizer", 예산 계획에 대한 피드백("네이버는 하루 50만 원으로 고정해줘", "그 피드백 빼줘",
  "남은 예산도 채워줘") 요청 시 사용. 제안받을 달의 매체별 추천 배분을 전월(기준 달) 실적으로 계산하거나(조건 확인 후) 내가 시작한
  계획 목록에서 골라, 기준 달 실적 · 추천 배분 · 피드백 반영 배분을 비교하는 HTML 보고서를 직접 작성한다. 사용자 피드백을 확인받아
  반영하고, 되돌리고, 잔여 예산을 채운다.
metadata:
  version: "4.4.0"
---

> ⚡ **thinking 지침**: thinking은 최대한 짧게 유지한다. 조건 확인 → MCP 호출 → 계산 → HTML 작성 → 완료 순서로 진행한다.

## 역할

라이트하우스 MCP 의 미디어믹스 **계획**을 다룬다. 계획은 다음 세 가지로 이루어진다.

- **추천 배분**: 기준 달 실적으로 학습해 최적화한 매체별 배분(사용자 피드백을 반영하기 전)
- **사용자 피드백**: 사용자가 말한 조건(예: "네이버는 하루 50만 원 고정"). 확인받은 것만 계획에 넣는다(최대 5개)
- **피드백 반영 배분**: 피드백을 모두 지키도록 다시 계산한 배분. 피드백이 없으면 추천 배분과 같다

계산이 끝날 때마다 결과를 **HTML 한 파일**로 직접 작성한다. 구성: 제목(제안 달) · 계획 조건 → 요약 수치 4개 → 매체별 요약
(기준 달 실적 · 추천 배분 · 피드백 반영 배분) → 반영한 피드백. 모양은 아래 「HTML 뼈대」를 따른다.
보고서는 **월 예산만** 보여 준다. 일별 배분 · 비용 대비 효과 곡선은 사용자가 물을 때만 H 대로 채팅으로 답하고, `warnings` 는 보여 주지 않는다.

## 데이터 처리 원칙 (절대 지침)

> 🚫 **숫자는 `get_media_mix_plan` 응답의 `summary` 행 값만 쓴다.** 행마다 `current`(기준 달 실적) · `baseline`(추천 배분) ·
> `plan`(피드백 반영 배분)이 각각 `{cost, outcome}` 으로 온다. 합계는 `media: "*"` 행이다 — 매체 행을 더해 합계를 만들지 않는다.
> 잔여 예산 금액은 `unspent.total`(`unspent` 가 null 일 수 있다 — G 참고), 잔여 예산을 채우는 배분안은 `remainder_fill`(G 참고)에서 가져온다. 추정 · 다른 도구 값 섞기 금지.
>
> 🚫 **계산과 칸 채우기는 `python3` 스크립트 하나로 한다.** 응답 JSON 을 문자열째 스크립트에 붙여 `json.loads` 로 읽고(JSON 의 `null` 은
> python 리터럴이 아니다), 「표에 넣을 값」대로 서식까지 입힌 HTML 조각(요약 수치 값, 표 `<tbody>` 행)을 출력하게 한다. 그 출력을 뼈대에
> 그대로 넣는다 — 숫자를 손으로 옮겨 적거나 암산하지 않는다. python 이 없는 호스트(코드 실행이 꺼진 채팅 등)에서만 같은 규칙으로 직접
> 계산하고, 증감 · 비중은 두 번 계산해 맞춰 본다.
>
> 🚫 **쓰기 도구는 사용자가 확인한 뒤에만 부른다.** `start_media_mix_plan`(계산이 1~수 분 돈다) · `apply_media_mix_claim` ·
> `remove_media_mix_claim` · `reset_media_mix_plan` 이 그렇다. `propose_media_mix_claim` 은 계획을 바꾸지 않으니 확인 전에 불러도 된다.
>
> 🚫 도구 목록에 `start_media_mix_plan` · `get_media_mix_plan` 이 없으면 이 조직에는 아직 열리지 않은 기능이다 — 다른 미디어믹스 도구로
> 대신하지 말고 그렇게 알린 뒤 멈춘다.

> ℹ️ 이 호스트의 Bash 기본 셸은 `sh`(dash)일 수 있다 — bash 전용 문법은 쓰지 않는다. `python3`이 없으면 `python`으로 부른다.

## 사용자에게 말할 때

사용자는 개발자가 아니다. 도구 이름 · 필드 이름 · plan_id · claim_id 는 보여 주지도, 달라고 하지도 않는다.
판(revision) · claim · 대기열 · 상태값(`pending`·`running` 등) · 상태를 다시 확인한다는 말도 하지 않는다. 아래 말로 바꿔 쓴다.

| 응답에 있는 것 | 사용자에게는 |
|---|---|
| `baseline` | 추천 배분 |
| `plan` | 피드백 반영 배분 |
| `current` | 기준 달 실적을 달 이름으로(예: "11월 실적"). "현재"라고 하지 않는다 |
| 판(revision) | 버전 |
| claim | 사용자 피드백(또는 피드백) |
| `hard_fact` / `soft_judgment` | 꼭 지킬 조건 / 가능하면 지킬 조건 |
| `unspent` · `remainder_fill` | 잔여 예산 |
| reward curve | 비용 대비 효과 곡선 |
| `outcome` | 성과 지표 이름(`request.outcome_metric`) 그대로. 건수 지표일 수 있으니 매출 · ROAS 라고 하지 않는다 |

최적화가 출발하는 초안(draft)은 내부 값이다 — 설명하지 않는다.

| 때 | 이렇게 말한다 |
|---|---|
| 계산을 시작함 | 예산 계산을 시작했습니다. 보통 몇 분 걸리고, 끝나면 바로 결과를 보여 드립니다. |
| 시작하지 못함(오류) | 예산 계산을 시작하지 못했습니다. 사유: {오류 원문} |
| 피드백을 반영해 다시 계산함 | 피드백을 반영해 예산을 다시 계산하고 있습니다. |
| 피드백을 되돌려 다시 계산함 | 피드백을 되돌리고 예산을 다시 계산하고 있습니다. |
| 기다리는 동안 | 따로 말하지 않는다. 사용자가 물으면 "아직 계산하는 중입니다." |
| 10분이 넘도록 끝나지 않음 | 계산이 평소보다 오래 걸립니다. 나중에 "다음 달 예산 계획 보여줘"라고 하시면 목록에서 골라 보실 수 있습니다. |

## 실행 순서

### A. 새로 시작할 때

1. `list_media_mix_metrics(brand_name)` — 비용 지표 후보 `cost_metrics` 와 성과 지표 후보 `outcome_metrics` 를 따로 받는다(각 항목 `{name, unit}`. 운영자가 숨긴 지표는 빠진다). 서버가 예전 버전이라 `{name, unit}` 목록 하나만 돌려주면 그 목록을 두 쪽 후보로 함께 쓴다. 한쪽 후보가 비었거나 서로 다른 둘을 고를 수 없으면 묻지 말고 멈추고, 운영자가 미디어믹스 지표 설정을 고쳐야 한다고 전한다. 에러(권한 · 미디어믹스 꺼짐 · 마트 없음)는 그대로 전한다.
2. **조건을 사용자에게 한 번에 확인받는다** — 말하지 않은 값은 추측하지 않고 묻는다. 학습 방식 · VAT 처리 등 나머지는 서버가 기본값으로 정하므로 묻지 않는다.

   | 조건 | 인자 |
   |---|---|
   | 제안받을 달(예산을 배분할 달) | `target_month` (`YYYY-MM`). 그 전월(기준 달) 실적으로 계산한다. 예산은 그 달이 오기 전에 정하므로 기준 달이 아직 진행 중인 것이 보통이고, 그때는 그날까지의 실적을 쓴다 — 데이터가 덜 들어왔다거나 기준 달이 끝난 뒤에 돌리는 편이 정확하다는 말은 하지 않는다 |
   | 비용 지표 · 성과 지표 | `cost_metric` 은 1번 `cost_metrics` 에서, `outcome_metric` 은 `outcome_metrics` 에서 하나씩(서로 다른 둘). 반대쪽 후보에만 있는 지표는 서버가 거절한다. 고를 수 있는 지표가 하나뿐인 쪽(반대쪽에서 고른 지표를 빼고 하나만 남을 때도)은 그 지표를 쓰고 묻지 않는다 — 대신 골랐다거나 후보가 하나뿐이라는 말도 하지 않는다 |
   | 제안받을 달의 예산(원, VAT 제외 Net) | `target_budget` (양의 정수) |
3. 확인받으면 `start_media_mix_plan(brand_name, target_month, cost_metric, outcome_metric, target_budget)` 1회 → `plan_id`.
   오류가 오면 「사용자에게 말할 때」의 "시작하지 못함"으로 전하고 멈춘다. 아니면 "계산을 시작함"으로 알리고 C 대로 기다린 뒤 D 를 한다.

### B. 이전 계획 고르기

A 를 거치지 않았고 이 대화에서 다루던 계획도 없으면 볼 계획을 정한다. 사용자는 목록의 **번호**로 고른다.

- 이 대화에서 이미 목록을 보여 줬고 사용자가 그 번호를 말하면(예: "5번 보여줘") 그 목록의 그 번호 계획을 쓴다. 목록을 다시 부르지 않는다.
- 아니면 `list_media_mix_plans(brand_name)` 1회. 이 브랜드에서 **내가 시작한** 계획이 최신순으로 온다(최대 50개).
  다른 사람이 시작한 계획은 목록에 없고 열어 볼 수도 없다. 받은 순서대로 1번(가장 최근)부터 번호를 매긴다.
- 사용자가 처음부터 번호를 말했으면(예: 지난번에 본 목록의 "5번") 그 번호의 행을 아래 표 한 줄로 보여 주고 이 계획이 맞는지 확인받는다 —
  그 사이 새로 시작한 계획이 있으면 번호가 뒤로 밀린다. 아니라고 하면 아래처럼 목록을 보여 준다.
- 목록에 계획이 하나뿐이고 사용자가 이미 보여 달라고 했으면 "이 계획을 보여 드릴까요?"라고 다시 묻지 않고 바로 그 계획을 연다.
- 최근 10개를 아래 표로 보여 주고 번호로 하나를 고르게 한다. 찾는 계획이 없다고 하면 11번부터 나머지를 마저 보여 준다.
  번호가 목록보다 크거나 찾는 계획이 50개 안에 없으면 최근 50개까지만 볼 수 있다고 알린다. 사용자가 이미 달 · 예산 등을 말했으면 맞는 행을 짚어 확인만 받는다.
  고르기 전에는 다음으로 넘어가지 않는다. 목록이 비었으면 이 브랜드에서 시작한 예산 계획이 없다고 알리고 A(새로 시작)를 제안한다.

  | 번호 | 제안받을 달 | 예산(원) | 비용 · 성과 지표 | 반영한 피드백 | 상태 | 시작 시각(KST) |
  |---|---|---|---|---|---|---|
  | 1 | `request.target_month` | `request.target_budget`(천 단위 쉼표) | `request.cost_metric` · `request.outcome_metric` | `claims_in_effect`개 | `latest_revision.status` → `succeeded` 완료 · `pending`·`running` 계산 중 · `failed` 는 `number` 가 0 이면 실패, 아니면 완료 | `created_at`(UTC)에 9시간을 더해 `MM-DD HH:mm`. 더해서 24시를 넘으면 날짜도 하루 넘긴다 |

- 고르면 `get_media_mix_plan(brand_name, plan_id)` 를 부르고 C 의 응답 판정대로 한다(계산 중이면 기다린다).

### C. 계산이 끝날 때까지 기다리기

`get_media_mix_plan(brand_name, plan_id)` 를 부르고, `latest_revision.status` 가 `pending`·`running` 이면
`python3 -c "import time; time.sleep(20)"` 로 기다렸다가 다시 부른다. 한 번에 보통 1~수 분 걸린다.
10분이 넘도록 끝나지 않으면 「사용자에게 말할 때」대로 알리고 멈춘다(나중에 B 에서 목록으로 골라 결과를 볼 수 있다).
에러(권한 · 없는 계획 등)가 오면 원문을 전하고 멈춘다. 끝나면 마지막 응답으로 판정한다.

| `latest_revision` | 판정 |
|---|---|
| `succeeded` | D 로 보고서를 만든다 |
| `failed`, `number` 0 | 추천 배분 계산이 실패했다. HTML 없이 「완료 메시지 형식」의 실패 문구를 쓴다 |
| `failed`, `number` 1 이상 | 마지막 변경(피드백 반영 · 되돌리기)만 실패했고 계획은 그 앞 버전 그대로다. "이번 변경은 반영하지 못했고 예산 계획은 이전 그대로입니다. 사유: {`error` 원문, 비었으면 `잠시 후 다시 말씀해 주세요.`}"라고 알린다. 새 HTML 은 만들지 않는다 |

### D. 결과 보고서 만들기

1. C(또는 G)에서 마지막으로 받은 `get_media_mix_plan` 응답을 쓴다(`summary` 가 있어야 한다). 다시 부르지 않는다.
2. **계산**: 위 원칙대로 `python3` 스크립트 하나로 「표에 넣을 값」을 계산해 HTML 조각을 출력한다.
3. **HTML 작성**: 「HTML 뼈대」의 `{…}` 를 채우고 표 `<tbody>` 를 2번 출력으로 바꿔
   `~/Downloads/laighthouse-reports/{브랜드}_media-mix_{제안 달}_{plan_id 앞 8자}_v{result_revision}.html` 로 저장한다. 파일 이름의 브랜드는
   `\ / : * ? " < > |` 와 공백을 `_` 로 바꾼다. 폴더가 없으면 만들고, 그 경로에 쓸 수 없는 호스트면 쓸 수 있는 폴더에 같은 이름으로 저장한다.
   채팅에서 보여 줄 수 있는 호스트(Artifact 등)면 그 파일로 게시한다.
4. 「완료 메시지 형식」대로 알린다. 하이라이트는 보고서에 넣은 `summary` 값만 근거로 쓴다.

### E. 피드백 반영하기

보고서를 본 사용자가 배분에 대해 조건을 말하면(예: "네이버는 12월 1~10일에 하루 50만 원으로 고정해줘") 계획에 넣는다.
계획이 계산 중이면 C 대로 기다린 뒤 한다.

1. **말 하나를 피드백 하나로** 옮긴다. 한 번에 여러 가지를 말하면 하나씩 나눈다. 계획에 든 피드백은 최대 5개다(매체가 여럿인 피드백도 1개로 센다).
   - 한 번에 함께 받은 피드백 가운데 같은 매체에 기간이 겹치는 것(기간을 말하지 않았으면 한 달 전체로 본다)이 있으면, 그 피드백들은
     **제안하지 않는다.** 같은 매체 · 같은 날에 걸쳐 둘 중 하나만 적용할 수 있다고 겹치는 날을 짚어 알리고, 그 매체에 대한 요청을
     하나로 다시 말해 달라고 묻는다. 예: "NVSHOP 12월 10일~20일 하루 50만 원 고정과 12월 15일~25일 20% 증액은 12월 15일~20일에 겹쳐서
     둘 중 하나만 적용할 수 있습니다. NVSHOP 요청을 하나로 다시 말씀해 주시겠어요?" 겹치지 않는 나머지는 아래대로 제안한다.
     이미 계획에 든 피드백과 겹치는 새 피드백은 여기에 해당하지 않는다(새 피드백이 기존 피드백을 대신한다 — 3번에서 알린다).
   - `affected_media`: `get_media_mix_plan` 의 `media` 에 있는 이름만 쓴다. 사용자가 말한 매체가 어느 이름인지 분명하지 않으면 묻는다.
   - `kind` · `params`(금액은 원, VAT 제외 Net):

     | 사용자가 말한 것 | `kind` | `params` |
     |---|---|---|
     | 매체마다 하루 얼마를 쓴다 | `FIX` | `{"v": 금액}` |
     | 매체마다 하루 비용을 얼마에서 얼마 사이로 둔다(한쪽만 말하면 다른 쪽을 묻는다) | `BOUND` | `{"lo": 하한, "hi": 상한}` |
     | 두 매체 비용을 몇 대 몇으로 둔다(정확히 두 매체, 앞 매체 ÷ 뒤 매체) | `RATIO_LOCK` | `{"r": 비율, "tol": 허용 폭(0보다 크게. 말하지 않았으면 묻는다)}` |
     | 여러 매체의 하루 비용 합을 얼마 이하로 둔다(두 매체 이상) | `JOINT_CAP` | `{"total": 금액}` |
     | 매체 비용을 몇 % 늘리거나 줄인다(예: "NVSHOP 15% 늘려", "NVSHOP이랑 PLINK 둘 다 10% 줄여줘") | `DIRECTIONAL_NUDGE` | `{"delta_pct": 비율}` — -1~1 사이, 늘리면 양수(15% → `0.15`), 줄이면 음수 |

     한 문장에서 여러 매체를 같은 비율로 말하면 `affected_media` 에 매체를 모두 넣어 피드백 **하나**로 제안한다. 서버는 비율 그대로 저장하고,
     비율 피드백은 **작은 변화로만** 반영한다 — 날마다 그날 계획 금액의 ±비율만큼, 하루에 평소 변동 폭(이유를 함께 말했으면 그 1.5배)까지만
     움직인다(방향은 늘 요청과 같고, 그날 금액이 0원인 매체는 움직이지 않는다). 제안 응답의 `routing`(미리 판정한 결과. 적용할 때 다시 판정한다)은
     매체마다 하나씩 오고(`routing[].media`), 큰 변화나 반복된 요청인 매체는 `decision` 이 `INJECT_CONSTRAINT` 다. 하나라도 `INJECT_CONSTRAINT` 면
     적용해도 거절되므로(모두 그렇면 `nudge_blocked`, 매체마다 갈리면 `mixed_blocked`) 확인 질문을 하지 말고 이렇게 안내한다.
     - 큰 변화인 매체: "{매체} {±N%}는 평소 하루 변동 폭보다 큰 변화라 비율로는 반영할 수 없습니다. 하루 얼마로 할지 금액으로 말씀해 주세요."
       답을 받으면 `FIX` 로 새로 제안한다.
     - 작은 변화인 매체(`OUTPUT_ADJUSTMENT`)가 함께 있으면: "{매체}는 {±N%}를 비율로 반영할 수 있으니, 따로 말씀해 주시면 반영하겠습니다."
       따로 말하면 그 매체만 넣어 새로 제안한다.
     금액도 비율도 없이 방향만 말하면("메타를 좀 늘려줘") 도구를 부르지 말고 하루 얼마로 할지, 또는 몇 % 바꿀지 먼저 묻는다.
   - `amount_basis`(`FIX` · `BOUND` · `JOINT_CAP` 에 필수): 하루 금액이면 `daily`, 기간 전체 금액이면 `period_total`(서버가 날수로 나눈다),
     말하지 않았으면 `unspecified`(하루 금액으로 본다).
   - `applies_from` · `applies_to`: 제안 달 안의 `YYYY-MM-DD`. 한 달 전체면 둘 다 뺀다. "프로모션 기간 동안"처럼 날짜를 알 수 없으면
     도구를 부르기 전에 며칠부터 며칠까지인지 묻는다.
   - `context_type`: 계약이나 이미 정해진 사실이면 `hard_fact`(꼭 지킬 조건), 사용자의 판단이면 `soft_judgment`(가능하면 지킬 조건).
   - `source_evidence`: 사용자가 한 말 그대로. 이유를 말했으면 `causal_rationale` 에 짧게 적고, 요청이 그 이유와 어긋나 보이면 `contradiction_warning` 에 어떻게 어긋나는지 적는다.
2. 피드백마다 `propose_media_mix_claim(...)` 1회(서로 기다릴 필요가 없으니 한 메시지에서 함께 보내도 된다). 오류가 오면(메시지가 무엇이 틀렸는지 말한다)
   그 내용을 쉬운 말로 전하고, 고칠 값을 물어 다시 한다. 피드백 내용은 고칠 수 없다 — 바꾸려면 새로 제안한다.
3. **이해한 내용을 되묻고 확인받는다.** 응답의 `claim`(금액은 하루 금액으로 바뀌어 있다)으로 쓴다. 여러 개면 번호를 붙여 한 번에 묻고, 확인도 한 번에 받는다.

   > 이렇게 이해했습니다: {매체}에 {기간} 동안 {조건} — {꼭 지킬 조건 | 가능하면 지킬 조건}. 이대로 반영할까요?

   - {기간}: `applies_from`~`applies_to` 를 `12월 1일~10일` 처럼. 둘 다 없으면 `12월 한 달`.
   - {조건}: `FIX` "하루 ₩500,000씩", `BOUND` "하루 ₩300,000~₩500,000 사이로", `RATIO_LOCK` "{앞 매체} 비용을 {뒤 매체} 비용의 1.5배(±0.1)로",
     `JOINT_CAP` "하루 비용 합을 ₩1,000,000 이하로". `amount_basis` 가 `period_total` 이면 사용자가 말한 금액(`raw_params`)도 괄호로 붙이고,
     `unspecified` 면 "하루 금액으로 이해했습니다"를 덧붙인다. `contradiction_warning` 을 적었으면 그 내용도 함께 묻는다.
   - 비율로 말한 피드백(`claim.kind` 가 `DIRECTIONAL_NUDGE`, 모든 `routing[].decision` 이 `OUTPUT_ADJUSTMENT`)은 {매체}에 매체를 모두 나열하고({매체} · {매체}) {조건}을 이렇게 쓴다(비율은
     `delta_pct` 를 `+15%` · `−10%` 처럼): "{기간} 동안 날마다 그날 계획 금액의 {비율}만큼 {늘립니다 | 줄입니다}. 평소 하루 변동 폭 안의 작은
     변화라 계획에 더하는 방식이고, 하루에 평소 변동 폭까지만 움직입니다." 이유를 함께 말했으면(`routing[].branch` 가 4) "평소 변동 폭의 1.5배까지만"으로 쓴다.
     하나라도 `INJECT_CONSTRAINT` 면 1번의 안내대로 하고 확인받지 않는다.
   - 1번에서 다시 말해 달라고 한 피드백이 있으면, 같은 메시지에서 "다시 말씀해 주실 {매체} 요청을 받은 뒤 함께 반영할까요, 나머지를 먼저 반영할까요?"도 묻는다.
   - 피드백이 이미 계획에 든 피드백(`state` 가 `active`)과 같은 매체이고 기간이 겹치면, 반영할 때 기존 피드백은 겹친 날만이 아니라
     **모든 날에서 빠진다.** 이렇게 알린다: "이 피드백을 반영하면 기존 '{기존 피드백의 `claim.source_evidence`}'은 {기존 피드백의 기간} 전체에서
     빠집니다. 겹치지 않는 날에도 유지하려면 그 기간을 따로 말씀해 주세요." 단, 계약(꼭 지킬 조건)은 계약으로만 대신한다 — 기존 것이 꼭 지킬
     조건이고 새 것이 가능하면 지킬 조건이면 대신하지 않는다(적용하면 `rejected_contract` 로 거절된다).
   - 사용자가 고치면 1번부터 다시 한다. 확인하지 않은 피드백은 반영하지 않는다(제안만 된 채로 두면 계획에 영향이 없다).
4. 확인받으면 확인받은 피드백 전부를 **한 번에** 적용한다: `apply_media_mix_claim(brand_name, plan_id, claim_ids=[…])`(사용자가 말한 순서대로).
   다시 계산은 한 번만 일어난다. 1번에서 다시 말해 달라고 한 피드백이 있으면 3번의 답대로 한다 — "함께"면 다시 말한 요청을 1~3번대로
   제안 · 확인받은 뒤 나머지와 한 호출로 적용하고, "먼저"면 나머지를 지금 적용하고 다시 말한 요청은 새 피드백으로 따로 처리한다.
   같은 매체에 기간이 겹치는 피드백 둘을 한 호출에 넣지 않는다(호출 전체가 오류로 끝난다).
   "계획이 계산 중"이라는 오류가 오면 C 대로 기다렸다가 한 번 더 부른다. 응답의 `status` 대로 한다.

   | `status` | 이렇게 말하고 할 일 |
   |---|---|
   | `added` | "피드백을 반영해 예산을 다시 계산하고 있습니다." `replaced` 가 있으면 그 피드백마다 "기존 피드백('{`claim.source_evidence`}')은 {그 피드백의 기간} 전체에서 빠졌습니다."도 알린다. C 대로 기다린 뒤 D. 반영한 피드백 가운데 `claim.routing` 의 `decision` 이 `OUTPUT_ADJUSTMENT` 인 것이 있으면 아래 「작은 변화 반영 알리기」를, 지키지 못한 날은 「지키지 못한 날 알리기」대로 완료 메시지에 붙인다 |
   | `needs_confirmation` | 일부만 반영할 수 있고 아직 아무것도 바뀌지 않았다. 반영할 수 없는 피드백(`outcome` 이 `acceptable` 이 아닌 것)마다 아래 이유를 먼저 알리고 "나머지만 반영해서 계산할까요?"라고 묻는다. 동의하면 **같은 `claim_ids`** 에 `accept_partial=true` 를 넣어 다시 부르고 그 응답의 `status` 대로 한다. 동의하지 않으면 부르지 않는다(계획은 그대로다) |
   | `rejected` | "말씀하신 피드백을 하나도 반영하지 못했습니다. 계획은 그대로입니다." 피드백마다 아래 이유를 알린다 |
   | `failed` | "지금은 피드백을 반영하지 못했습니다. 잠시 후 다시 말씀해 주세요." 나중에 다시 하려면 1번부터 새로 제안한다 |

   `claims` 는 넘긴 순서대로 피드백마다 `{outcome, claim, conflict, safe_range}` 이다. `replaced` · `conflict.claim_id` 가 가리키는 피드백은
   `get_media_mix_plan` 의 `claims` 에서 같은 `claim_id` 로 찾는다. 반영하지 못한 피드백의 이유(`outcome`)는 이렇게 말한다.

   | `outcome` | 이유 |
   |---|---|
   | `rejected_contract` | "{`conflict.media`}의 {`conflict.overlap` 기간}에 이미 계약 조건('{그 계약 피드백의 `claim.source_evidence`}')이 있습니다. 계약 조건은 새 계약 조건으로만 바꿀 수 있습니다." |
   | `rejected_limit` | "피드백은 5개까지 반영할 수 있습니다. 반영한 피드백 하나를 되돌린 뒤 다시 말씀해 주세요." F 처럼 번호를 매긴 반영한 피드백 목록을 함께 보여 준다 |
   | `mixed_blocked` | "여러 매체를 한 번에 말씀하신 피드백입니다. 매체마다 따로 말씀해 주세요." |
   | `nudge_blocked` | "{매체} {±N%}는 평소 하루 변동 폭보다 큰 변화라 비율로는 반영할 수 없습니다. 하루 얼마로 할지 금액으로 말씀해 주세요." 답을 받으면 `FIX` 로 1번부터 새로 제안한다 |
   | `outside_safe_range` | "{매체} {조건}은 과거에 써 본 금액 범위(하루 ₩{하한}~₩{상한})를 벗어나 반영할 수 없습니다." 범위는 `safe_range`({매체: [하루 하한, 하루 상한]}, 비용 서식)다. 이어서 두 가지를 제안한다: 범위 안의 금액으로 다시 말하기, 또는 계약처럼 이미 정해진 조건이면 꼭 지킬 조건으로 넣기(그렇다고 하면 `hard_fact` 로 1번부터 새로 제안한다) |
   | `period_ambiguous` | "기간을 알 수 없습니다. 며칠부터 며칠까지인지 알려 주세요." 답을 받으면 1번부터 다시 한다 |
   | `failed` | "지금은 반영하지 못했습니다. 잠시 후 다시 말씀해 주세요." |

   반영하지 못한 피드백은 다시 제안하지 않는 한 계획에 들어가지 않는다.

   **작은 변화 반영 알리기**: 평소 하루 변동 폭 안의 작은 변화(`claim.routing` 의 `decision` 이 `OUTPUT_ADJUSTMENT`)는 다시 계산한 추천 배분에
   더하는 방식으로 들어간다. 그런 피드백마다 완료 메시지에 한 줄을 붙인다. 늘리는지 줄이는지는 비율 피드백이면 `delta_pct`, 금액 피드백이면
   `routing[].daily_change` 의 부호로 정한다.
   - 금액 피드백(`FIX` · `BOUND`), 늘릴 때: "'{`claim.source_evidence`}'는 평소 하루 변동 폭 안의 작은 변화라, 추천 배분에 더하는 방식으로 반영했습니다. 하루에 평소 변동 폭까지만 움직이고, 늘린 만큼은 잔여 예산을 먼저 쓴 뒤 다른 매체에서 비율대로 덜어 냅니다."
   - 비율 피드백(`DIRECTIONAL_NUDGE`), 늘릴 때: "'{`claim.source_evidence`}'는 평소 하루 변동 폭 안의 작은 변화라, 날마다 그날 계획 금액의 {+15%}만큼 늘리는 방식으로 반영했습니다. 하루에 평소 변동 폭까지만 움직이고, 늘린 만큼은 잔여 예산을 먼저 쓴 뒤 다른 매체에서 비율대로 덜어 냅니다." 줄일 때는 "{−10%}만큼 줄이는 방식으로"로 쓴다.
   - 줄일 때(둘 다): 뒷문장을 "줄인 만큼은 다른 매체에 비율대로 나눠 줍니다."로 바꾼다.
   - "늘린 만큼은 잔여 예산을 먼저 쓴 뒤 다른 매체에서 비율대로 덜어 냅니다"는 잔여 예산을 남겨 둔 계획(`fill_remainder` false)에만 쓴다.
     잔여 예산을 채운 계획은 채운 뒤에 작은 변화를 더하므로 "늘린 만큼은 다른 매체에서 비율대로 덜어 냅니다"로 쓴다.
   - 이유를 함께 말한 피드백(`routing[].branch` 가 4)은 "하루에 평소 변동 폭까지만 움직이고"를 "이유를 함께 말씀하셔서 하루에 평소 변동 폭의 1.5배까지 움직이고"로 쓴다. branch 5 는 위 문구 그대로다.

   **지키지 못한 날 알리기**: 다시 계산한 결과(`get_media_mix_plan`)의 `claims` 에서 `refused_days` · `refused_reasons`({날짜: {매체: 이유}})만
   근거로 쓴다. 이유를 짐작하거나 다른 이유를 지어내지 않는다. 피드백마다 이유별로 날짜를 묶어(예: `12월 9일 · 10일`) 한 줄씩 쓴다.
   여러 매체에 걸친 피드백은 매체 하나라도 지킨 날을 반영한 날로 치므로, `refused_days` 는 그 피드백의 매체를 하나도 지키지 못한 날이다.
   같은 날 매체마다 이유가 다르면 매체 이름을 붙여 이유별로 나눠 쓴다.
   "때문에"는 쓰지 않고 "~로 인해" · "~라서"로 쓴다(사용자를 탓하는 말로 읽힐 수 있다).

   - **이번에 반영한 피드백**: `refused_days` 의 날마다 아래 표의 줄을 쓴다.
   - **계획에 이미 있던 다른 피드백**(`state` 가 `active`): `refused_days` 에 있고 `refused_days_before` 에 없는 날(이번에 새로 못 지키게 된 날)만
     알린다: "'{`claim.source_evidence`}': 이번 피드백을 함께 지키느라 {날짜들}에는 이 조건을 지키지 못하게 됐습니다 — {아래 표의 이유}"
     (이유가 "그 밖"이면 " — {이유}"를 뺀다). `refused_days_before` 가 null 이면 직전 결과에 없던 피드백이니 이 줄을 쓰지 않는다.

   | 이유 | 줄 = "'{`claim.source_evidence`}': {날짜들}에는 {이유}" 의 {이유} |
   |---|---|
   | `outside_safe_range` | 과거에 써 본 금액 범위를 벗어나 지킬 수 없었습니다. |
   | `no_room` | 그날에 걸친 다른 피드백(계약 포함)이 계획에 있으면 "그날 예산 안에서 먼저 지켜야 하는 조건(계약, 앞선 피드백)과 함께 지킬 수 없었습니다.", 없으면 "그날 예산 안에서 지킬 수 없었습니다." |
   | `too_narrow` | 조건을 함께 지킬 수 있는 금액 폭이 너무 좁아 지킬 수 없었습니다. |
   | `fixed_cost` | 이 매체가 그날 고정비이거나 다른 조건이 걸려 움직일 수 없어 반영하지 못했습니다. |
   | `no_offset` | 늘리거나 줄인 만큼을 맞춰 줄 다른 매체가 없어 반영하지 못했습니다. |
   | `negative` | 늘리거나 줄인 만큼을 다른 매체로 맞추면 0원 아래로 내려가는 매체가 생겨 반영하지 못했습니다. |
   | `total_mismatch` · `over_limit` | 그날 예산 합계를 맞출 수 없어 반영하지 못했습니다. |
   | 그 밖 | 이 조건을 지키지 못했습니다. |

   작은 변화(`OUTPUT_ADJUSTMENT`)는 같은 날 것을 한꺼번에 반영해서, 하나라도 안 되면 그날 작은 변화는 모두 빠지고 같은 이유를 받는다.
   같은 날 같은 이유를 받은 작은 변화 피드백이 둘 이상이면 이유 뒤에 "(같은 날 함께 반영하는 작은 변화 '{다른 피드백의 `claim.source_evidence`}'와
   함께 맞출 수 없어 그날은 모두 빠졌습니다)"를 덧붙인다.

   작은 변화로 반영한 피드백(`OUTPUT_ADJUSTMENT`)의 `clipped_days` 가 비어 있지 않으면, 같은 방식으로 날짜를 묶어 한 줄을 더 붙인다:
   "'{`claim.source_evidence`}': {날짜들}에는 요청한 변화가 평소 하루 변동 폭보다 커서 그 폭까지만 반영했습니다."
   `routing[].branch` 가 4 면 "평소 하루 변동 폭보다 커서 그 폭까지만"을 "평소 하루 변동 폭의 1.5배보다 커서 그만큼까지만"으로 쓴다.
   (계획 전체의 `unspent.capped_days` 와는 다른 값이다.)
   날짜별 금액은 사용자가 물을 때만 H 대로 `get_media_mix_plan_daily` 로 보여 준다.

### F. 피드백 되돌리기

- **하나 되돌리기**: 최근 `get_media_mix_plan` 응답의 `claims` 중 `state` 가 `active` 인 것을 오래된 순으로 번호를 매겨 보여 준다
  (보고서의 「반영한 피드백」 표와 같은 순서). 사용자가 번호로 고르면 "'{claim.source_evidence}' 피드백을 되돌리고 예산을 다시 계산할까요?"로
  (매체가 여럿인 피드백은 한꺼번에 되돌아가므로 "'…' 피드백({매체} · {매체})을 되돌리고"처럼 매체를 모두 적어)
  확인받은 뒤 `remove_media_mix_claim(brand_name, plan_id, claim_id)` → 「사용자에게 말할 때」대로 알리고 C 대로 기다린 뒤 D.
- **전부 되돌리기**: "반영한 피드백 {N}개를 모두 되돌려 추천 배분으로 돌아갈까요?"로 확인받은 뒤 `reset_media_mix_plan(brand_name, plan_id)`.
  `removed` 가 비고 `revision` 이 null 이면 "되돌릴 피드백이 없습니다." `revision.status` 가 이미 `failed` 면 "지금은 되돌리지 못했습니다. 잠시 후 다시 말씀해 주세요."
  아니면 「사용자에게 말할 때」대로 알리고 C 대로 기다린 뒤 D.
- 둘 다 "계획이 계산 중"이라는 오류가 오면 C 대로 기다렸다가 한 번 더 부른다.

### G. 잔여 예산 채우기

추천 배분은 비용을 더 써도 효과가 늘지 않는 매체에는 예산을 더 넣지 않아, 예산 일부가 잔여 예산으로 남을 수 있다.
잔여 예산은 기본으로 남겨 두고, 사용자가 원할 때만 채운다. 잔여 예산을 어떻게 나눌지(배분안)도 사용자가 보여 달라고 할 때만 보여 준다.

- 잔여 예산 금액은 `get_media_mix_plan` 의 `unspent.total` 이다. `unspent` 는 null 일 수 있다 — 계획에 든 피드백이 모두 작은 변화
  (`routing[].decision` 이 `OUTPUT_ADJUSTMENT`)이고 조건(`INJECT_CONSTRAINT`)이 하나도 없어 최적화를 다시 돌리지 않은 경우다. 이때는 완료 메시지에
  잔여 예산 안내를 쓰지 않고, 사용자가 잔여 예산을 물으면 `include_remainder_fill=true` 로 불러 `remainder_fill` 의 `remainder` 로 답한 뒤 2번처럼 배분안을 보여 준다.
  `unspent.total` 을 읽기 전에는 늘 `unspent` 가 null 인지 먼저 본다.
- 배분안은 `get_media_mix_plan(brand_name, plan_id, include_remainder_fill=true)` 로 부를 때만 오는 `remainder_fill` 에 있다(기본 응답에는 키가 없다).
  `fill_remainder` 가 false 면 "채우면 이렇게 된다"는 미리 보기, true 면 "이렇게 채웠다"는 기록이다.
  `remainder` 잔여 예산 합계 · `added` 채우면(채워서) 더 들어가는 금액 · `added_by_media` 매체별 `{media, cost}`, 채우는 순서대로 ·
  `outcome_delta` 채워서 바뀌는 예상 성과(음수일 수 있다) · `left` 채우고도 남는 금액(모든 매체가 상한에 닿음)
- 문구의 금액은 비용 서식(`₩` 정수)이다. 매체는 `added_by_media` 순서(채우는 순서) 그대로 쓰고, 금액 순으로 다시 정렬하지 않는다.
  {성과 변화}는 `outcome_delta` 의 절댓값을 표의 성과 칸 서식으로 쓰고 부호에 따라 "늘어납니다" · "줄어듭니다"(0 이면 "그대로입니다")를 붙인다.
  {상한 문장}은 `left` 가 1만 원 이상일 때만 붙이는 "₩{left}는 모든 매체가 과거에 써 본 금액 범위에 닿아 더 넣을 곳이 없습니다."다.

1. **보고서를 낼 때마다(피드백 반영 · 되돌리기 뒤에도) 완료 메시지의 {안내 줄}에 아래를 넣는다.**

   | 상태 | 이렇게 말한다 |
   |---|---|
   | `fill_remainder` false, `unspent` 가 null 이 아니고 `unspent.total` 1만 원 이상 | "잔여 예산 ₩{unspent.total}이 남아 있습니다. 어떻게 나눌 수 있는지 보여 드릴까요?" 매체별 금액 · 성과 변화는 이 단계에서 보여 주지 않는다 |
   | `fill_remainder` true, `remainder_fill.added` 1만 원 이상 | "잔여 예산 약 ₩{added}을 {매체}에 ₩{cost}, {매체}에 ₩{cost} 채웠습니다(예상 {지표} {성과 변화} {늘어남 \| 줄어듦})." 뒤에 {상한 문장}. 묻지 않는다 |
   | 그 밖 | 아무것도 말하지 않는다 |

   `fill_remainder` 가 true 인 계획은 보고서를 만들기 전에 `include_remainder_fill=true` 로 1회 더 불러 그 응답으로 D 를 한다(채운 금액과 매체별 내역이 필요하다).
2. 사용자가 보여 달라고 하면 `include_remainder_fill=true` 로 1회 불러 `remainder_fill` 로 답한다.
   - `added` 가 1만 원 이상: "채우면 {매체}에 ₩{cost}, {매체}에 ₩{cost}가 더 들어가고, 예상 {지표}가 {성과 변화} {늘어납니다 \| 줄어듭니다}." 뒤에 {상한 문장}, 끝에 "잔여 예산을 채울까요, 남겨 둘까요?"
   - `added` 가 1만 원 미만: "모든 매체가 과거에 써 본 금액 범위에 닿아 잔여 예산을 더 넣을 곳이 없습니다." 묻지 않는다.
3. 사용자가 채우겠다고 하면 `set_media_mix_fill_remainder(brand_name, plan_id, fill=true)` 후 `include_remainder_fill=true` 로,
   다시 남겨 두겠다고 하면 `fill=false` 후 기본 인자로 `get_media_mix_plan` 을 1회 부르고 D 로 보고서를 새로 만든다(다시 계산하지 않아 바로 반영된다).
   `changed` 가 false 면 이미 그렇게 돼 있다고만 알린다. 이 선택은 이후 피드백을 반영해 다시 계산해도 그대로 유지된다.
   피드백을 반영한 날 · 못 한 날과 그 이유, 잔여 예산(`unspent`)은 지금 채우기 선택의 결과라 선택을 바꾸면 달라질 수 있다. 그래서 선택을 바꾼 뒤
   새 보고서의 완료 메시지에는 계획에 든 모든 피드백(`state` 가 `active`)의 지키지 못한 날을 E 「지키지 못한 날 알리기」의 표대로 다시 쓴다
   (`refused_days_before` 는 보지 않는다).

`include_remainder_fill` 같은 인자 이름은 사용자에게 말하지 않는다.

### H. 물을 때만 답하기

보고서에는 넣지 않는다. 사용자가 물으면 도구를 불러 채팅으로 답한다(숫자는 python 으로 정리한다).

- **일별 배분**("날짜별로 보여줘", "방금 피드백으로 뭐가 바뀌었어?"): `get_media_mix_plan_daily(brand_name, plan_id, compare_to)`.
  추천 배분과 비교하면 `baseline`, 바로 앞 버전과 비교하면 `previous`. 날짜 · 매체별 `before_cost` → `after_cost` 를 표로 보여 주고,
  바뀐 날 · 매체만 추리거나 주 단위로 묶어도 된다. 앞 버전이 없다는 오류가 오면 비교할 이전 버전이 없다고 알린다.
  작은 변화 피드백이 걸린 매체가 반영한 날인데 그날 금액이 0원이라 그대로면 "그날 이 매체에 배분된 금액이 없어 움직이지 않았습니다"라고 설명한다.
- **비용 대비 효과 곡선**("이 매체에 더 쓰면 효과가 있어?", "왜 이렇게 배분했어?"): `get_media_mix_reward_curves(brand_name, plan_id, media)`.
  하루 비용(`cost`)에 따라 비용 대비 효과(`mean`)가 어떻게 바뀌는지, 95% 신뢰 구간(`ci95_low`~`ci95_high`)이 얼마나 넓은지,
  추천 배분의 하루 평균 비용(`baseline_daily_mean_cost`)이 곡선의 어디쯤인지 쉬운 말로 설명한다. 학습한 하루 비용 범위(`trained_cost_range`)
  밖은 데이터가 없어 예측이 불확실하다고 덧붙인다. 최적화는 매체별 효율의 최고점이 아니라 전체 성과가 가장 커지게 나누므로, 효율이 최고점보다
  낮은 곳에 배분될 수 있다. 고정비 매체(`fixed_media`)는 곡선이 없다.

## 표에 넣을 값

`summary` 행은 `media`(`"*"` 는 합계)마다 `current` · `baseline` · `plan` 을 담고, 각각 `cost` · `outcome`(늘 숫자)이다.
효율의 바탕 값 `outcome_per_cost` 는 `outcome ÷ cost` 로 직접 구하고, 비용이 0 이면 없음(null)으로 본다.

- **피드백 묶음을 보일지**: `claims` 에 `state` 가 `active` 인 것이 하나라도 있으면 표 · 요약 수치에 피드백 반영 배분을 보인다. 없으면
  피드백 반영 배분 묶음(열 3개)과 「반영한 피드백」 카드를 통째로 빼고, 아래 "최종 배분"은 추천 배분을 쓴다. 있으면 최종 배분은 피드백 반영 배분이다.
- **달**: 제안 달은 `request.target_month`, 기준 달은 그 전월이다(`2027-01` 이면 `2026-12`). 달 숫자는 앞자리 0 없이 쓴다(`3월`, `12월`).
- **매체**: `summary` 의 `media`(`"*"` 제외). 최종 배분 비용이 큰 순, 같으면 이름순으로 놓고 합계 행은 맨 아래.
  매체 점 색은 이 순서대로 `#4a7fe0` `#3f8f73` `#d08a2c` `#8a80e8` `#ef7a68` `#9fbcf3` `#81d0b0` `#f5bf79` `#b7b2f7` `#9aa3ad` 를 돌려 쓴다.
- **반올림**: 정수 · 소수 자리 모두 사사오입(0.5 는 올림)이다. python `round()`(짝수 쪽으로 반올림)는 쓰지 않고 `Decimal(str(값))` 에 `ROUND_HALF_UP` 을 쓴다.
  증감 · 비중 · 배분율은 반올림하기 전 값으로 계산한다.
- **비용**: `₩` + 천 단위 쉼표, 정수.
- **성과 · 효율**: `outcome_unit` 으로 가른다. `{지표}` 는 `request.outcome_metric` 이다. `outcome_per_cost` 가 없으면 효율 칸은 `–`.

  | `outcome_unit` | 성과 칸 | 효율 열 이름 | 효율 칸 |
  |---|---|---|---|
  | `₩` · `KRW` · `원`(금액) | `₩1,234,567`(정수) | `{지표} ÷ 비용` | `outcome_per_cost × 100` 을 정수 `%` 로(예: `342%`) |
  | 그 밖의 단위(건수) | 정수 뒤에 단위(예: `1,234회`) | `{지표}당 비용` | `1 ÷ outcome_per_cost` 를 비용처럼 `₩` 정수로. `outcome_per_cost` 가 0 이면 `–` |
  | 없음(`null` · 빈 값) | 정수, 단위 없이(예: `1,234`) | `{지표} ÷ 비용` | `outcome_per_cost` 를 유효숫자 세 자리로, 지수 표기 없이 천 단위 쉼표(예: `0.0388` · `9.70` · `1,230`) |

- **열 머리글**: 첫 줄은 `매체`(두 줄 차지) · `{기준 달 M}월 실적`(3열) · `추천 배분`(3열) · `피드백 반영 배분`(3열).
  둘째 줄은 실적 쪽 `비용` · `{지표}` · `{효율 열 이름}`, 배분 쪽마다 `비용` · `예상 {지표}` · `{효율 열 이름}`.
- **증감**: 배분 쪽 칸마다 값 아래 줄에 비교 대상 대비 증감을 쓴다. 추천 배분 칸은 같은 행 · 같은 열의 기준 달 실적 대비,
  피드백 반영 배분 칸은 같은 행 · 같은 열의 추천 배분 대비다.
  - `(배분 값 − 비교 값) ÷ |비교 값| × 100` 을 소수 첫째 자리로 반올림하고, 반올림한 값으로 방향을 정한다.
  - 양수면 `▲ 12.3%`(`class="sub up"`, 빨강), 음수면 절댓값으로 `▼ 4.5%`(`class="sub down"`, 파랑), 0 이면(`-0.0` 도) 기호 없이 `0.0%`(`class="sub"`).
    요약 수치의 증감 `<span>` 도 같고, 0 이면 `class` 를 뺀다.
    지표가 좋아졌는지와 관계없이 방향으로만 색을 정한다.
  - 효율 칸은 화면에 보이는 효율(건수 지표면 성과당 비용)의 반올림 전 값으로 계산한다.
  - 두 값 가운데 하나라도 `–` 이거나 비교 값이 0 이면 증감을 쓰지 않는다.
- **비중**: 매체 행의 배분 비용 칸마다 증감 줄 아래에 `비중 {그 배분 비용 ÷ 그 배분 합계 비용 × 100}%`(소수 첫째 자리)를 쓴다. 합계 행에는 쓰지 않는다.
- **요약 수치 4개**(합계 행 기준):
  1. `{제안 달 M}월 예산 합계` — 최종 배분 합계 비용. 아래 줄 `목표 ₩{target_budget} (Net)`, 그 합계가 목표의 99.5% 미만이면 `{합계 ÷ 목표 × 100, 소수 첫째}% 배분` 도.
  2. `예상 {지표}` — 최종 배분 합계 성과. 아래 줄: 피드백 반영 배분이면 추천 배분 대비 증감(표와 같은 규칙)과 `추천 배분 대비`, 아니면 `모델 예측치`.
  3. `예상 {효율 열 이름}` — 최종 배분 합계 효율. 아래 줄에 기준 달 실적 대비 증감과 `{기준 달 M}월 실적 대비`. 증감을 쓸 수 없으면 둘 다 뺀다.
  4. `{기준 달 M}월 실적 {효율 열 이름}` — 실적 합계 효율. 아래 줄 `비용 ₩{실적 합계 비용}`.
- **계획 조건**: 기준 달 `YYYY년 M월`, 목표 예산 `₩{target_budget}` + `VAT 제외 Net`, 지표 `{cost_metric} · {outcome_metric}`,
  시작 시각 `created_at`(UTC)에 9시간을 더한 `YYYY-MM-DD HH:mm`. 잔여 예산 줄은 `fill_remainder` 가 true 이고
  `remainder_fill.added` 를 반올림한 값이 1 이상이면 `₩{added} 채움`, false 이고 `unspent` 가 null 이 아니고 `unspent.total` 을 반올림한 값이 1 이상이면 `₩{unspent.total} 남김`(금액은 비용 서식), 그 밖에는 줄을 뺀다.
- **배지**: `완료` 하나. 반영한 피드백이 있으면 `피드백 {N}개 반영` 배지를 더한다.
- **반영한 피드백 카드**: `state` 가 `active` 인 피드백을 `claims` 순서 그대로(오래된 순) 한 행씩 — 번호, 사용자가 한 말(`claim.source_evidence`), 매체(`claim.affected_media` 를 ` · ` 로),
  조건(E-3 의 {조건}과 같은 말), 기간(E-3 의 {기간}), 종류(`claim.context_type` → 꼭 지킬 조건 · 가능하면 지킬 조건),
  지키지 못한 날(`refused_days` 개수, 0 이면 `–`, 있으면 `{N}일`).
- **글자**: 브랜드 · 매체 · 지표 이름 · 사용자가 한 말은 HTML 이스케이프(`html.escape`)해서 넣는다.

## HTML 뼈대

모양 · 클래스 · 색은 이대로 쓴다. `{…}` 를 채우고, 쓰지 않는 줄 · 묶음(증감 · 비중 · 배분율 · 잔여 예산 · 피드백 반영 배분 열 · 피드백 카드 등)은
그 요소를 통째로 뺀다(피드백 반영 배분을 빼면 첫 줄 머리글 하나와 둘째 줄 머리글 세 개, 행마다 세 칸을 함께 뺀다).
`<tbody>` 의 두 행은 모양 예시다 — python 이 이 모양대로 만든 매체 행들과 합계 행으로 바꾼다.

```html
<!doctype html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{브랜드} {제안 달 YYYY년 M월} 예산 계획</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>
body{margin:0;background:#f5f6f8;color:#262c34;font:14px/1.5 'Pretendard Variable',Pretendard,-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif}
.page{max-width:1280px;margin:0 auto;padding:24px 24px 64px}
.head{display:flex;align-items:center;gap:8px;margin-bottom:16px}
h1{margin:0 4px 0 0;font-size:24px;font-weight:700;letter-spacing:-.015em}
.badge{display:inline-flex;align-items:center;height:20px;padding:0 7px;border-radius:4px;font-size:12px;font-weight:600;color:#245c4a;background:#eef9f4;border:1px solid #b2e7d1}
.badge.fb{color:#3a3591;background:#f1f0fe;border-color:#cfcbf9}
dl{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;margin:0 0 20px}dt{color:#6b7683}dd{margin:0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(124px,1fr));gap:12px;margin-bottom:20px}
.kpi,.card{background:#fff;border:1px solid #e6e8ec;border-radius:12px;box-shadow:0 1px 2px rgba(23,27,33,.04)}
.card+.card{margin-top:20px}
.kpi{min-width:0;padding:16px 18px}.k-label{color:#6b7683;font-size:13px}
.k-value{font-size:22px;font-weight:700;margin-top:4px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.k-sub{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px;font-size:12px;color:#6b7683}
.card-head{display:flex;align-items:center;justify-content:space-between;padding:14px 20px;border-bottom:1px solid #e6e8ec}
.card-head h2{margin:0;font-size:16px}.note{font-size:12px;color:#6b7683}
.wrap{overflow-x:auto}table{width:100%;border-collapse:collapse}
th{font-size:12px;font-weight:600;color:#4f5a66;background:#fafbfc;border-bottom:1px solid #dcdfe4;padding:8px 12px;white-space:nowrap;text-align:left}
th.grp{text-align:center}
td{border-bottom:1px solid #eef0f3;padding:7px 12px;vertical-align:middle}td:first-child{white-space:nowrap}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.g{border-left:1px solid #dcdfe4}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px}.media{font-weight:600}
.sub{font-size:12px;color:#6b7683}.up{color:#c93b3b;font-weight:600}.down{color:#2e5bd8;font-weight:600}
tr.total td{font-weight:700;background:#fafbfc;border-top:1px solid #dcdfe4;border-bottom:0}
</style></head><body><div class="page">
<div class="head"><h1>{제안 달 YYYY년 M월} 예산 계획</h1><span class="badge">완료</span><span class="badge fb">피드백 {N}개 반영</span></div>
<dl><dt>기준 달</dt><dd>{기준 달 YYYY년 M월}</dd><dt>목표 예산</dt><dd>{₩목표} <span class="sub">VAT 제외 Net</span></dd>
<dt>지표</dt><dd>{cost_metric} · {outcome_metric}</dd><dt>시작 시각</dt><dd>{YYYY-MM-DD HH:mm}</dd>
<dt>잔여 예산</dt><dd>{₩채운 금액 채움 | ₩잔여 예산 남김}</dd></dl>
<div class="kpis">
<div class="kpi"><div class="k-label">{제안 달 M}월 예산 합계</div><div class="k-value">{₩최종 합계}</div><div class="k-sub"><span>목표 {₩목표} (Net)</span><span>{n.n}% 배분</span></div></div>
<div class="kpi"><div class="k-label">예상 {지표}</div><div class="k-value">{최종 합계 성과}</div><div class="k-sub"><span class="{up|down}">{▲|▼} {n.n}%</span><span>추천 배분 대비</span></div></div>
<div class="kpi"><div class="k-label">예상 {효율 열 이름}</div><div class="k-value">{최종 합계 효율}</div><div class="k-sub"><span class="{up|down}">{▲|▼} {n.n}%</span><span>{기준 달 M}월 실적 대비</span></div></div>
<div class="kpi"><div class="k-label">{기준 달 M}월 실적 {효율 열 이름}</div><div class="k-value">{실적 합계 효율}</div><div class="k-sub"><span>비용 {₩실적 합계}</span></div></div>
</div>
<section class="card"><div class="card-head"><h2>매체별 요약</h2><span class="note">비용은 VAT 제외 Net 기준입니다.</span></div>
<div class="wrap"><table><thead>
<tr><th rowspan="2">매체</th><th colspan="3" class="grp g">{기준 달 M}월 실적</th><th colspan="3" class="grp g">추천 배분</th><th colspan="3" class="grp g">피드백 반영 배분</th></tr>
<tr><th class="num g">비용</th><th class="num">{지표}</th><th class="num">{효율 열 이름}</th>
<th class="num g">비용</th><th class="num">예상 {지표}</th><th class="num">{효율 열 이름}</th>
<th class="num g">비용</th><th class="num">예상 {지표}</th><th class="num">{효율 열 이름}</th></tr>
</thead><tbody>
<tr><td><span class="dot" style="background:{매체 색}"></span><span class="media">{매체}</span></td>
<td class="num g">{실적 비용}</td><td class="num">{실적 성과}</td><td class="num">{실적 효율}</td>
<td class="num g">{추천 비용}<div class="sub up">▲ {n.n}%</div><div class="sub">비중 {n.n}%</div></td>
<td class="num">{추천 성과}<div class="sub down">▼ {n.n}%</div></td><td class="num">{추천 효율}<div class="sub">0.0%</div></td>
<td class="num g">{피드백 비용}<div class="sub up">▲ {n.n}%</div><div class="sub">비중 {n.n}%</div></td>
<td class="num">{피드백 성과}<div class="sub down">▼ {n.n}%</div></td><td class="num">{피드백 효율}<div class="sub">0.0%</div></td></tr>
<tr class="total"><td>합계</td><td class="num g">{실적 합계 비용}</td><td class="num">{실적 합계 성과}</td><td class="num">{실적 합계 효율}</td>
<td class="num g">{추천 합계 비용}<div class="sub down">▼ {n.n}%</div></td><td class="num">{추천 합계 성과}<div class="sub up">▲ {n.n}%</div></td><td class="num">{추천 합계 효율}<div class="sub up">▲ {n.n}%</div></td>
<td class="num g">{피드백 합계 비용}<div class="sub">0.0%</div></td><td class="num">{피드백 합계 성과}<div class="sub down">▼ {n.n}%</div></td><td class="num">{피드백 합계 효율}<div class="sub down">▼ {n.n}%</div></td></tr>
</tbody></table></div></section>
<section class="card"><div class="card-head"><h2>반영한 피드백</h2><span class="note">금액은 하루 기준입니다.</span></div>
<div class="wrap"><table><thead>
<tr><th>번호</th><th>피드백</th><th>매체</th><th>조건</th><th>기간</th><th>종류</th><th class="num">지키지 못한 날</th></tr>
</thead><tbody>
<tr><td>1</td><td>{사용자가 한 말}</td><td>{매체}</td><td>{조건}</td><td>{기간}</td><td>{꼭 지킬 조건 | 가능하면 지킬 조건}</td><td class="num">{N일 | –}</td></tr>
</tbody></table></div></section>
</div></body></html>
```

## 완료 메시지 형식

```
{브랜드명} 다음 달 예산 계획({제안 달 YYYY년 M월}) 보고서 생성 완료.
가장 인상적인 부분: {한 문장 하이라이트}.
{안내 줄}
— by LaightAI
```

- 하이라이트는 피드백이 없으면 추천 배분과 기준 달 실적의 차이, 있으면 피드백 반영 배분과 추천 배분의 차이에서 고른다.
- {안내 줄}은 쓸 것만 한 줄씩 넣고, 없으면 줄째 뺀다.
  - 방금 반영한 피드백이 있으면(E-4) 작은 변화 반영 문구와 지키지 못한 날 문구(새로 못 지키게 된 다른 피드백 포함). 목록에서 골라 볼 때는 넣지 않는다
  - G-1 의 잔여 예산 문구(배분안을 보여 드릴지 묻는 경우 이 줄을 맨 끝에 둔다)
  - 이 대화에서 처음 보고서를 낼 때 한 번: "특정 매체의 금액 · 기간 · 비율 같은 조건을 말씀해 주시면 반영해 다시 계산합니다."

추천 배분 계산이 실패했으면(C 의 판정) HTML 을 만들지 않고 아래를 쓴다. `error` 가 비었으면 사유 자리에 `잠시 후 다시 실행해 주세요.` 를 쓴다.

```
{브랜드명} 다음 달 예산 계산({제안 달 YYYY년 M월})이 완료되지 않았습니다.
사유: {error 원문}
— by LaightAI
```

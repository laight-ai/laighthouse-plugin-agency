# MCP 도구 라우팅 규칙 (laighthouse 서버 — agency 플러그인 공용)

이 플러그인의 스킬이 쓰는 도구는 `get_ad_performance`·`get_target_progress_v2`·`list_campaign_change_raw`·`get_external_context`(필요하면 `get_brand_list`)와
`media-mix-result` 스킬의 미디어믹스 도구 셋(`list_media_mix_metrics`·`create_media_mix_job`·`get_media_mix_job`, 규칙은 그 스킬의 SKILL.md)뿐이다.

## 1. `get_ad_performance` — 광고 성과 (유일한 성과 조회 도구)

```json
{
  "brand_name": "<brand>",
  "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD",
  "time_grain": "day" | "month" | "total",
  "group_by": ["media", "ad_type", "campaign_name", "ad_group_name", "ad_name"],   // 차원명 리스트, 생략 시 총계
  "metrics": null,                         // 항상 생략 = 서빙 지표 전부
  "filters": null,                         // 생략 = 전체
  "day_offset": 20                         // month grain 전용 — 각 월을 1일~N일로 자른다(weekly-report의 전월 동기간 비교)
}
```

- **차원은 테넌트별**이다 — 차원 확인(`pivot-table.md` 1절)으로 받은 목록만 쓴다. 행의 차원 키는 이름 그대로 온다
  (day grain은 `date`, month grain은 `month`("YYYY-MM") 키가 함께 온다).
- 알 수 없는 차원·지표 이름은 서버가 유효한 목록을 담은 ValueError로 거절한다 — 추측 재시도하지 않는다.
- ELT 테넌트가 없는 브랜드는 `Brand '<name>' is not ELT-published yet …` ValueError — 그대로 사용자에게 전달한다.
- **상한**: 조회 구간 day/total 366일, month 730일, 응답 50,000행.
- **응답은 JSON 봉투**다:
  `{"source": "elt", "tenant": "<brand>", "fee_basis": "net", "fees": [...], "time_grain": "day", "dimensions": [...], "metrics": [...], "metric_units": {...}, "row_count": N, "rows": [...]}`
  - `fee_basis`(`net`·`gross`)는 브랜드의 출력 수수료 방식이다 — 광고비와 광고비로 계산한 지표(CPM·CPC·CPV·ROAS 등)가 모두 이 기준으로 온다.
  - `fees` = `[{"media", "month": "YYYY-MM", "fee_mode": "markup"|"commission", "rate": 퍼센트}]` — 행의 매체(행 표기 그대로)마다,
    조회 구간이 걸친 달마다, 수수료가 있는 것만 온다. 목록에 없는 매체·달은 수수료 없음(Gross = Net). group_by에 media가 없으면 빈 목록.
  - **지표 키는 테넌트별**이다 — 응답의 `metrics`가 유효한 키의 유일한 진실이다. 역할(광고비·노출·클릭·CTR·조회수·CPM·CPV)은
    `discover.py`가 해석한다.
  - `metric_units`는 지표별 단위 기호 — 빌더가 그대로 붙인다(지표명으로 단위를 추측하지 않는다).
  - ⚠️ 비율 지표(CTR·CPM·CPV·VTR 등)는 서버가 요청 grain 기준으로 계산한 값이다. 행 값을 합산·평균해 상위 값을 만들지 않는다.
  - 차원 값이 null/빈 문자열인 행은 정상 행이다 — 빌더가 `(미지정)`으로 표시한다.

## 2. `get_target_progress_v2` — 월 예산·목표

```json
{ "brand_name": "<brand>", "month": "YYYY-MM", "as_of_date": "YYYY-MM-DD", "cost_metric": "<metric_keys.cost>" }
```

- `media` 생략 = 전체. 이 플러그인의 스킬은 모두 **`media` 생략 1회**만 부른다 — 매체 목표는 둘째 표의 매체 행에서 읽는다.
- 머리 줄은 `month`·`as_of_date`·`media`·`fee_basis`다. `fee_basis`는 위 봉투와 같은 브랜드 설정이고, 예산(cost)과 CPM·CPC·CPV·ROAS
  목표·실적이 모두 이 기준이다.
- 응답 첫째 표(`| metric | target | actual | progress_ratio |`)는 전체 합계(cost = 매체 예산 합),
  둘째 표(`| media | campaign_name | included | metric | target | actual | achievement |`)는 매체·캠페인 행이다(cost = 예산).
- 그 달 수수료가 있는 매체가 있으면 둘째 표 뒤에 셋째 표 `| media | fee_mode | rate |`가 온다 — 둘째 표의 매체 표기, 수수료가 있는
  매체만. 캠페인 행은 그 매체의 수수료를 따른다.
- **Gross / Net**: 응답 기준(`fee_basis`)이 보고서의 기본 보기이고, 수수료가 있으면 빌더가 다른 기준의 보기를 더 만든다 — 행마다 그 매체의
  그 달 수수료로 마크업은 Gross = Net × (1 + r/100), 커미션은 Gross = Net ÷ (1 − r/100)(수수료가 없으면 그대로). 실적은 봉투의 `fees`,
  예산·단가 목표는 셋째 표를 쓴다. 매체 차원이 없는 응답(전체 합계)은 같은 기간을 매체별로 받은 응답에서 구한 실효 배수를 쓴다.
  규칙은 `shared/assets/fees.py`. 모델이 환산하지 않는다(원문 그대로 넘긴다).
- `fee_basis`가 없는 옛 서버 응답은 광고비 실적이 Net이고 예산이 cost(Gross)·cost_net(Net) 두 행이고 처음 보기는 Gross다 — 빌더가 예전 규칙
  (Gross 광고비 = Net × cost ÷ cost_net, 수수료는 달마다 같다고 본다)으로 읽는다. 비율은 캠페인 비율, 없으면 매체 비율(없으면 그 매체에
  포함된 캠페인들의 합, included N 제외), 그 달 비율이 없으면 가장 최근 달 비율, 없으면 1이다. Net 보기 예산 = `cost_net`(없는 범위는
  Gross − 한 단계 아래 범위의 수수료 합)이고, 단가 목표는 기준에 따라 바꾸지 않는다. `fee_basis`가 있는 응답과 없는 응답이 섞이면 빌더가
  멈춘다 — 모두 다시 받는다.
- 표 대신 한 줄 평문(`No all budget/target available for {month}.` 등)은 오류가 아니라 **목표 없음**이다.
- 응답 원문을 그대로 빌더에 넘긴다 — `actual` 열은 쓰지 않는다(실적은 `get_ad_performance` 값).
- `cost_metric`을 구버전 서버가 거절하면 그 인자를 빼고 1회 재호출한다. 그 밖의 에러는 목표 없음(빈 문자열)으로 두고 계속한다.

## 3. `list_campaign_change_raw` — 캠페인 변경 이력 원본 (종합 리포트 Campaign History)

```json
{ "brand_name": "<brand>", "date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD", "limit": 1000,
  "streams": ["change_event", "activities", "changelog", "campaigns", "campaign_detail", "adgroups", "ad_groups", "ad_group_detail"],
  "cursor": "<이전 응답의 next_cursor>" }   // 첫 호출은 cursor 생략
```

- 응답 `{"contract": "elt.change_raw.v1", "items": [{"source", "stream", "dt", "connection_id", "row": {매체 원본}}], "next_cursor"}`.
  로그 매체(Google `change_event`·Meta `activities`·TikTok `changelog`)는 행 1개 = 로그 1건, 네이버·카카오는 날마다 받은 목록(스냅샷)이다.
- 플러그인 훅이 응답을 저장하고 모델에게는 건수와 `next_cursor`만 보여 준다 — `next_cursor`가 있으면 **같은 인자에 `cursor`만 바꿔**
  `null`이 될 때까지 이어 부른다. 원본은 `prepare.py`·빌더가 읽는다(옮겨 적지 않는다).
- 이력 API가 없는 매체·연결이 없는 브랜드는 `items`가 빈 채로 온다 — 오류가 아니라 "변경 이력 없음"이다.
- 스트림 이름이 틀리면 알려진 목록을 담은 ValueError — 위 목록을 그대로 쓴다.

## 4. `get_brand_list` — 브랜드 목록

- 서버가 `Unknown brand`로 거절할 때만 쓴다. 그 뒤 처리는 아래 공통 규칙을 따른다.

## 공통 규칙

- 도구가 `User has granted the required connector consent. Retry the tool call to proceed.`를 돌려주면 오류가 아니다 —
  **같은 인자로 한 번 재호출**한다.
- 모든 호출의 `brand_name`은 사용자가 말한 브랜드명을 **그대로** 넣는다(비슷한 이름을 확인받았으면 그 이름). 스킬 파일에 브랜드 문자열을 두지 않는다.
- 서버가 `Unknown brand`로 거절하면(이름이 다르거나 그 브랜드를 읽을 권한이 없으면) `get_brand_list`를 1회 불러
  아래 기준에 맞는 이름을 후보로 고른다(1. 공백·대소문자·`(주)`·`주식회사`만 다른 이름, 2. 한쪽이 다른 쪽을 포함하는 이름, 3. 글자 1~2개만 다른 이름 순). **묻지 않고 바꿔 부르지 않는다** —
  AskUserQuestion으로 "'<사용자가 말한 이름>'은(는) '<후보>'를 말씀하신 건가요?"를 묻는다. 선택지는 후보 1~3개(가장 비슷한 것 먼저)와
  "아니요"이다. 후보를 고르면 그 이름을 이후 모든 호출의 `brand_name`, 스크립트의 `--brand`, 제목·파일명에 쓰고 거절된 라운드(동시에 보낸 호출 전체)를 새 이름으로 다시 보낸다.
  "아니요"를 고르거나 비슷한 이름이 없으면 볼 수 있는 브랜드 목록을 보여 주고 멈춘다.
  후보는 이름 기준으로 중복을 없앤다. 목록이 비어 있으면 브랜드 접근 권한과 MCP 사용 설정을 관리자에게 확인하게 한다. AskUserQuestion이 없는 호스트에서는 같은 질문과
  선택지를 채팅으로 내고 답을 기다린다.
- 서버가 `Several brands are named`로 거절하면 읽을 수 있는 브랜드 중 이름이 **완전히 같은** 것이 여럿이라는 뜻이다 —
  어느 이름을 골라도 같은 오류가 나므로 묻지 않는다. 서버 메시지를 그대로 전하고, 관리자에게 브랜드 이름을 구분해 달라고
  요청하게 한 뒤 멈춘다.
- 서로 의존성 없는 호출은 **한 메시지에서 동시에** 보낸다.

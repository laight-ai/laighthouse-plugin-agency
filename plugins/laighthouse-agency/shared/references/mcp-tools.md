# MCP 도구 라우팅 규칙 (laighthouse 서버 — agency 플러그인 공용)

이 플러그인의 스킬이 쓰는 도구는 `get_ad_performance`·`get_target_progress_v2`·`list_campaign_change_raw`(필요하면 `get_brand_list`)뿐이다.

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
  `{"source": "elt", "tenant": "<brand>", "time_grain": "day", "dimensions": [...], "metrics": [...], "metric_units": {...}, "row_count": N, "rows": [...]}`
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
- 응답 첫째 표(`| metric | target | actual | progress_ratio |`)는 전체 합계(cost = Gross),
  둘째 표(`| media | campaign_name | included | metric | target | actual | achievement |`)는 매체·캠페인 행이다.
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

- 서버가 `Unknown brand`로 거절할 때만 정확한 브랜드명을 확인하는 데 쓴다.

## 공통 규칙

- 도구가 `User has granted the required connector consent. Retry the tool call to proceed.`를 돌려주면 오류가 아니다 —
  **같은 인자로 한 번 재호출**한다.
- 모든 호출의 `brand_name`은 사용자가 말한 브랜드명을 **그대로** 넣는다. 스킬 파일에 브랜드 문자열을 두지 않는다.
- 서로 의존성 없는 호출은 **한 메시지에서 동시에** 보낸다.

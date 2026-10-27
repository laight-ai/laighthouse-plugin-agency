# section-2: Total Summary · Monthly Summary

표 데이터(`data`)와 예산·목표(`budgets`)로 브라우저가 그린다. **월·미디어 필터를 따르지 않는다**(전체 기간·전 매체).

- 행 = 미디어 → 디멘전 설정에서 고른 디멘전(기본 상품 · 광고 그룹), 미디어마다 `{미디어} 요약` 행.
  - Total Summary: 맨 앞 열 = 캠페인명(입력란, 기본값 = 브랜드명 — 브라우저에 저장), 마지막 `Total 요약`.
  - Monthly Summary: 맨 앞 열 = 월, 달마다 `{n}월 요약`, 마지막 `Total 요약`.
- 열 = **기본 영역**(예산 · 비용 · 노출 · 클릭 · 조회 · CPM · CPC · CTR · CPV · VTR · 소진율 · 진행율) +
  **목표 영역**(e.Imps · e.Click · e.View · e.CTR · e.VTR · e.CPM · e.CPC · e.CPV · 노출/클릭/조회 달성률).
  지표 설정에서 켜고 끄고 순서를 바꾼다(기본 영역·목표 영역 사이로는 옮기지 않는다). 브랜드가 주지 않는 지표(예: 조회수)에 기대는 열은 빠진다.
- 값: 원자 지표 합 → CPM = 비용/노출×1000, CPC = 비용/클릭, CTR = 클릭/노출, CPV = 비용/조회, VTR = 조회/노출.

## 예산·목표 (budgets)

- 빌더 입력 `budgets` = `[{"month", "target_progress": "<원문>"}]` — 달마다 `get_target_progress_v2`(media 생략) 원문 1개.
  응답 규약(2026-10-16 report-backend 확정):
  - 헤더 `month` · `as_of_date` · `media` · `target_mode`(dashboard | advertiser)
  - 첫째 표 `| metric | target | actual | progress_ratio |` = 호출 범위 합계(cost = Gross 예산 합) → 전체 범위.
  - 둘째 표 `| media | campaign_name | included | metric | target | actual | achievement |` = 매체 행(campaign_name `-`) 뒤에
    그 매체의 캠페인 행(dashboard 브랜드만, included Y/N — 미포함 캠페인도 온다). 단위는 캠페인이 끝이다.
- `cost` 행 = 예산(Gross), `impression`·`click`·`views`·`ctr`·`vtr`·`cpm`·`cpc`·`cpv` 행 = e.* 목표.
  `cost_net`·`revenue`·`roas` 행과 `actual`·`achievement` 열은 쓰지 않는다(실적은 get_ad_performance 값).
  (호출에 `media`를 넣어 받은 원문이면 그 범위로 읽고, 범위 열을 가진 다른 표 형식도 같은 방식으로 읽는다.)
- 매체·캠페인 이름은 BE와 같은 기준(앞뒤 공백·대소문자 무시)으로 데이터 표기에 맞춘다. 맞는 표기가 없는 행(그 달 실적이 없는
  매체·캠페인, 저장 코드 `NAVER GFA` 등)은 어느 행에도 붙지 않는다.
- 칸마다: 그 행의 범위와 **정확히 같은 범위**의 값이 있으면 그 값. 없으면 더 잘게 받은 범위가 그 행에 집행된 단위를 **모두** 덮을 때만 합
  (비율 목표 e.CTR·e.VTR·e.CPM·e.CPC·e.CPV는 합하지 않는다). 여러 달이면 달마다 구해 더한다. 못 구하면 빈칸.
  - `{미디어} 요약`·`{n}월 요약`·`Total 요약`에 예산·소진율이 채워진다. 디멘전 설정에서 미디어 바로 아래에 캠페인을 두면 캠페인 행도
    채워진다(캠페인 목표가 있을 때). 상품·광고그룹 행은 목표 단위가 아니라서 빈칸이다.
- **비어 있는 목표는 계산해서 채운다**(서버 값이 있으면 그대로):
  - 목표 단위마다: e.Imps = 예산/e.CPM×1000(또는 클릭/CTR), e.Click = 예산/e.CPC(또는 노출×CTR), e.View = 노출×VTR(또는 예산/CPV),
    e.CTR·e.CPM·e.CPC·e.VTR·e.CPV는 그 반대로.
  - 여러 단위·여러 달을 합친 행: 합친 예산·노출·클릭·조회 목표로 비율 목표를 다시 계산한다.
- 소진율 = 비용/예산. 진행율 = 경과일/월 일수(여러 달이면 합) — 예산이 있는 **맨 아래 행**에만 표시(목업과 같다).
- 달성률 = 실적/목표(노출·클릭·조회).

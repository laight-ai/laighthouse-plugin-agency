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
  - 헤더 `month` · `as_of_date` · `media`
  - 첫째 표 `| metric | target | actual | progress_ratio |` = 호출 범위 합계(cost = Gross 예산 합) → 전체 범위.
  - 둘째 표 `| media | campaign_name | included | metric | target | actual | achievement |` = 매체 행(campaign_name `-`) 뒤에
    그 매체의 캠페인 행(저장된 경우에만, included Y/N — 미포함 캠페인도 온다). 단위는 캠페인이 끝이다.
- `cost` 행 = 예산(Gross), `cost_net` 행 = 예산(Net), `impression`·`click`·`views`·`ctr`·`vtr`·`cpm`·`cpc`·`cpv` 행 = e.* 목표.
  `revenue`·`roas` 행과 `actual`·`achievement` 열은 쓰지 않는다(실적은 get_ad_performance 값).
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

## Gross / Net (광고비·예산 기준)

- 광고비 실적은 항상 Net이다. 예산에 수수료가 있으면(매체·캠페인 범위의 `cost` ≠ `cost_net`) 머리말에 `광고비·예산 기준 [Gross][Net]`
  토글이 생기고 표마다 지금 기준 배지가 붙는다(기본 Gross, 고른 기준은 브라우저에 남는다). 수수료가 없으면 토글이 없다.
- Gross 보기: 광고비 = Net × (Gross ÷ Net 예산) — 행의 캠페인 비율, 없으면 매체 비율(매체 행, 없으면 그 매체 캠페인들의 합), 없으면 1
  (수수료 0%). 예산 = `cost`. CPM·CPC·CPV·소진율은 환산한 광고비로 다시 계산된다. Placement는 캠페인 차원이 없어 매체 비율을 쓴다.
- Net 보기: 광고비 = 원값, 예산 = `cost_net`. `cost_net`이 없는 범위(첫째 표의 전체 합계, 캠페인 목표만 있는 매체)는
  Gross − 한 단계 아래 범위(전체 → 매체, 매체 → 캠페인)의 수수료 합이다.
- 단가 목표(e.CPM·e.CPC·e.CPV)와 Mix 단가 초기값은 그리드에 넣은 값 그대로다(기준에 따라 바꾸지 않는다).
- Comment 문장(Daily·Weekly)도 기준마다 따로 만든다. 엑셀은 기준마다 한 파일이다.

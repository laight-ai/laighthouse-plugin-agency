"""소재 성과 공용 기준 — 최소 표본과 원자 지표 순서."""

MIN_IMP, MIN_SHARE = 1000, 0.01   # 비율 지표(CTR·ROAS) 순위·효율 비교에 쓰는 최소 표본: 노출 ≥ 1,000 그리고 광고비 ≥ 매체 광고비의 1%
ATOMS = ("cost", "impression", "click", "conversion", "revenue", "view")   # 소재 행의 원자 지표 순서

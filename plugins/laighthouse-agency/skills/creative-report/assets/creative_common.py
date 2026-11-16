"""소재 성과 공용 기준 — 최소 표본과 원자 지표 순서."""

MIN_IMP, MIN_SHARE = 1000, 0.01   # 비율 지표(CTR·ROAS) 순위·효율 비교에 쓰는 최소 표본: 노출 ≥ 1,000 그리고 광고비 ≥ 매체 광고비의 1%
ATOMS = ("cost", "impression", "click", "conversion", "revenue", "view")   # 소재 행의 원자 지표 순서

# 금액 표기 — 공용 킷(report_kit.fmt_money)과 같은 규칙. 소수가 없는 통화(₩·¥·원, 단위 모름)는 100 미만만 소수 1자리,
# 나머지(USD 등)는 소수 2자리. 보고서 화면 JS(report-template.html의 f.money)도 같은 규칙이다.
ZERO_DECIMAL = ("₩", "¥", "원", "")
CURRENCY_SYMBOL = {"KRW": "₩", "USD": "$", "EUR": "€", "JPY": "¥", "GBP": "£"}


def money(v, cur):
    if v is None:
        return "-"
    d = (0 if abs(v) >= 100 else 1) if cur in ZERO_DECIMAL else 2
    body = format(v, ",.%df" % d)
    return body + cur if cur == "원" else cur + body

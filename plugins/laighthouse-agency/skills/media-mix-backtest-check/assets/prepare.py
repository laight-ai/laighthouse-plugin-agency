#!/usr/bin/env python3
"""대상 달 고르기 · 총예산 계산: 저장된 월 · 매체별 광고 성과 응답 → 대상 달 후보와 달마다 총예산(실제 집행액, Net).

사용법:
  python3 assets/prepare.py --brand <브랜드> --cost <비용 지표> --outcome <성과 지표> [--months 2026-03,2026-05]

출력(JSON 한 줄):
- 응답이 아직 없거나 범위가 모자라면 {"missing": [부를 get_ad_performance 인자]}
- 응답이 오류면 {"errors": [...]}
- 아니면 {"eligible": [대상 달 후보], "months": [{target_month, base_month, budget, last_year}], "fee_basis"}
  --months를 주지 않으면 months는 추천 후보(최근 달부터 한 달 걸러 최대 6개)다.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I 실행에서도 옆 모듈을 찾는다
import backtest as bt  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--cost", required=True)
    ap.add_argument("--outcome", required=True)
    ap.add_argument("--months")
    ap.add_argument("--today", help="시험용(YYYY-MM-DD). 기본 오늘(KST)")
    a = ap.parse_args(argv)
    today = bt.date.fromisoformat(a.today) if a.today else bt.kst_today()
    closed = bt.last_closed_month(today)
    try:
        months = sorted({bt.parse_month(m.strip()) for m in a.months.split(",") if m.strip()}) if a.months else None
        late = [m for m in months or [] if m > closed]
        if late:
            raise ValueError(f"아직 끝나지 않은 달은 점검할 수 없다: {', '.join(late)} (끝난 마지막 달은 {closed})")
        start, end = bt.window(months, today) if months else bt.default_window(today)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    recs = bt.sr.load_records(a.brand)
    rec, env = bt.ad_performance(recs)
    if rec is None or not bt.covers(rec, start, end):
        bt.sr.emit({"missing": [bt.call_args(a.brand, start, end)]})
        return 0
    if not isinstance(env, dict) or not isinstance(env.get("rows"), list):
        bt.sr.emit({"errors": [{"call": "get_ad_performance", "response": bt.sr.response_text(rec).strip()[:300]}]})
        return 0
    try:
        data = bt.monthly(env, a.cost, a.outcome)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    first = bt.shift(start.strftime("%Y-%m"), 13)
    span = []
    m = first
    while m <= end.strftime("%Y-%m"):
        span.append(m)
        m = bt.shift(m, 1)
    eligible = [m for m in span if bt.month_total(data, m) > 0 and bt.month_total(data, bt.shift(m, -1)) > 0]
    if months is None:
        months = sorted(list(reversed(eligible))[::2][:bt.SUGGEST])
    bad = [m for m in months if m not in eligible]
    if bad:
        print(f"대상 달이나 그 전월의 광고비가 없다: {', '.join(bad)}", file=sys.stderr)
        return 2
    bt.sr.emit({"eligible": eligible, "fee_basis": env.get("fee_basis"), "months": [
        {"target_month": m, "base_month": bt.shift(m, -1), "budget": bt.won(bt.month_total(data, m)),
         "last_year": bt.month_total(data, bt.shift(m, -13)) > 0 and bt.month_total(data, bt.shift(m, -12)) > 0}
        for m in months]})
    return 0


if __name__ == "__main__":
    sys.exit(main())

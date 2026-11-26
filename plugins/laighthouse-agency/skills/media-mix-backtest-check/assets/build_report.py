#!/usr/bin/env python3
"""백테스트 결과 → 판정 · HTML 보고서. 저장된 월 · 매체별 광고 성과 응답과 get_media_mix_job 응답을 읽는다.

사용법:
  python3 assets/build_report.py --brand <브랜드> --cost <비용 지표> --outcome <성과 지표> --months 2026-03,2026-05 [--out <경로.html>]

출력(JSON 한 줄):
- 광고 성과 응답이 모자라면 {"missing": [...]}, 오류면 {"errors": [...]}
- 끝난 backtest 결과가 없는 달이 있으면 {"missing_jobs": [달]}(결과 조회가 오류로 끝난 응답이 있으면 "errors"도)
- 아니면 {"out": HTML 경로(모두 실패면 null), "facts": {months, counts, flagged, failed}}
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I 실행에서도 옆 모듈을 찾는다
import backtest as bt  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--cost", required=True)
    ap.add_argument("--outcome", required=True)
    ap.add_argument("--months", required=True)
    ap.add_argument("--out")
    ap.add_argument("--today", help="시험용(YYYY-MM-DD). 기본 오늘(KST)")
    a = ap.parse_args(argv)
    today = bt.date.fromisoformat(a.today) if a.today else bt.kst_today()
    try:
        months = sorted({bt.parse_month(m.strip()) for m in a.months.split(",") if m.strip()})
        start, end = bt.window(months, today)
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
    found, errors = bt.jobs(recs, a.cost, a.outcome)
    missing = [m for m in months if m not in found]
    if missing:
        bt.sr.emit({"missing_jobs": missing, **({"errors": errors} if errors else {})})
        return 0
    done = [bt.judge_month(m, found[m], data) for m in months if found[m].get("status") == "succeeded"]
    failed = [(m, found[m].get("error")) for m in months if found[m].get("status") != "succeeded"]
    if not done:
        bt.sr.emit({"out": None, "facts": bt.facts([], bt.count([]), failed)})
        return 0
    page, counts = bt.render(a.brand, a.cost, a.outcome, done, failed)
    safe = re.sub(r'[\\/:*?"<>| ]', "_", a.brand)
    out = a.out or os.path.join(os.path.expanduser("~"), "Downloads", "laighthouse-reports",
                                f"{safe}_media-mix-backtest_{months[0]}_{months[-1]}.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    bt.sr.emit({"out": out.replace("\\", "/"), "facts": bt.facts(done, counts, failed)})
    return 0


if __name__ == "__main__":
    sys.exit(main())

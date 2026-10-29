#!/usr/bin/env python3
"""저장된 MCP 응답 → 빌더 입력(build.json) + Weekly Summary 근거(digest). 모델이 응답 원문을 읽거나 옮겨 적지 않게 한다.

플러그인 저장 훅(hooks/save_responses.py)이 laighthouse 응답 원본을 파일로 남긴다. 이 스크립트는 그중 이 브랜드·기준일의
응답을 (도구 + 인자)로 골라 섹션 입력을 만든다 (E = 기준일 = 데이터 마지막 날):
  s1  get_ad_performance(month, group_by 생략, day_offset = E의 일, E의 전월 1일~E)
      + get_target_progress_v2(month = E의 달, media 생략)
  s3  get_ad_performance(day, group_by ["media"], E-34~E)
  s4  get_ad_performance(total, group_by = FINE_DIMS, 이번주 E-6~E · 전주 E-13~E-7)

사용법 (2차 호출까지 받은 직후, 1회):
  python3 assets/prepare.py --brand <브랜드> --target-date <E>
출력(stdout JSON): {"base": build.json 경로, "missing": [...], "errors": [...], "discover": {...}, "digest": {...}, "note"?}
  → 빌더: python3 assets/build_report.py 에 {"base": <경로>, "dims": "<차원 확인 에러 메시지 원문>", "s2": {...}}를 넘긴다.
"""
import argparse
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(HERE, "..", "shared", "assets"),           # zip 번들
             os.path.join(HERE, "..", "..", "..", "shared", "assets")):  # 개발 트리(src)
    if os.path.exists(os.path.join(cand, "report_kit.py")):
        sys.path.insert(0, os.path.normpath(cand))
        break
else:
    raise SystemExit("report_kit.py를 찾을 수 없다 (shared/assets)")
sys.path.insert(0, HERE)
import build_report  # noqa: E402
import report_kit as kit  # noqa: E402
import saved_responses as sr  # noqa: E402

PERF, TARGET = "get_ad_performance", "get_target_progress_v2"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--target-date", required=True)
    a = ap.parse_args()
    E = date.fromisoformat(a.target_date)   # 기준일 = 데이터 마지막 날(최대 어제)
    if sr.future_date_error(E):
        sr.emit({"date_error": sr.future_date_error(E)})
        return
    pm_first = (E.replace(day=1) - timedelta(days=1)).replace(day=1)
    day = lambda n: E - timedelta(days=n)  # noqa: E731
    recs = sr.load_records(a.brand)
    if not recs:
        sr.emit({"note": sr.no_records_note()})
        return

    w = sr.Workdir(f"{a.brand}_weekly_{E}")
    base = {"out": f"~/Downloads/laighthouse-reports/{a.brand}_weekly_{E}.html", "title": f"{a.brand} Weekly 보고서",
            "target_date": str(E)}
    M = f"{E:%Y-%m}"
    s1 = w.envelope(sr.pick(recs, PERF, time_grain="month", group_by=None, day_offset=E.day, start_date=pm_first, end_date=E),
                    "s1.json", {"section": "s1", "time_grain": "month", "group_by": None, "day_offset": E.day,
                                "range": f"{pm_first}~{E}"})
    target = w.text(sr.pick(recs, TARGET, month=M, media=None), {"section": "s1", "tool": TARGET, "month": M, "media": None})
    s3 = w.envelope(sr.pick(recs, PERF, time_grain="day", group_by=["media"], start_date=day(34), end_date=E), "s3.json",
                    {"section": "s3", "time_grain": "day", "group_by": ["media"], "range": f"{day(34)}~{E}"})
    s4 = {}
    for k, (s, e) in (("cur", (day(6), E)), ("base", (day(13), day(7)))):
        env = w.envelope(sr.pick(recs, PERF, time_grain="total", group_by="*", start_date=s, end_date=e), f"s4_{k}.json",
                         {"section": "s4", "time_grain": "total", "group_by": "FINE_DIMS", "range": f"{s}~{e}"})
        if env:
            s4[k] = env
    if s1:
        base["s1"] = dict(s1, target_progress=target or "")
    base.update({k: v for k, v in (("s3", s3), ("s4", s4)) if v})

    result = {"missing": w.missing, "errors": w.errors}
    disc_env = kit.section_envelope(s3 or s1)
    if disc_env:
        disc = kit.resolve_roles(disc_env)
        base["metric_keys"], base["currency"] = disc["metric_keys"], disc["currency"]
        result["discover"] = {"metric_keys": disc["metric_keys"], "currency": disc["currency"],
                              "metrics_absent": disc["missing"]}
    result["base"] = w.write(base)
    try:
        result["digest"] = build_report.digest(dict(base))
    except SystemExit as e:   # 대조 검증 실패 등 — 빌더도 같은 이유로 멈춘다
        result["digest_error"] = str(e)
    sr.emit(result)


if __name__ == "__main__":
    main()

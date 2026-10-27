#!/usr/bin/env python3
"""저장된 MCP 응답 → 빌더 입력(build.json) + Daily Summary 근거(digest). 모델이 응답 원문을 읽거나 옮겨 적지 않게 한다.

플러그인 저장 훅(hooks/save_responses.py)이 laighthouse 응답 원본을 파일로 남긴다. 이 스크립트는 그중 이 브랜드·기준일의
응답을 (도구 + 인자)로 골라 섹션 입력을 만든다 (D0 = 기준일, D1 = D0-1, D7 = D0-7):
  s1  get_ad_performance(day, group_by 생략, D7~D0)
  s3  get_ad_performance(day, group_by ["media"], D0-6~D0)
  s4  get_ad_performance(total, group_by = FINE_DIMS, D0·D1·D7 하루씩)

사용법 (MCP 호출을 모두 받은 직후, 1회):
  python3 assets/prepare.py --brand <브랜드> --target-date <D0>
출력(stdout JSON): {"base": build.json 경로, "missing": [...], "errors": [...], "discover": {...}, "digest": {...}, "note"?}
  → 빌더: python3 assets/build_report.py 에 {"base": <경로>, "dims": "<차원 확인 에러 메시지 원문>", "s2": {...}}를 넘긴다.
  missing: 저장된 응답이 없는 호출(그 호출만 다시 보내고 재실행). note: 저장된 응답이 하나도 없다 — 훅이 없는 환경.
"""
import argparse
import json
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

PERF = "get_ad_performance"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--target-date", required=True)
    a = ap.parse_args()
    d0 = date.fromisoformat(a.target_date)
    D0, D1, D7, D6 = (str(d0 - timedelta(days=n)) for n in (0, 1, 7, 6))
    recs = sr.load_records(a.brand)
    if not recs:
        sr.emit({"note": sr.no_records_note()})
        return

    w = sr.Workdir(f"{a.brand}_daily_{D0}")
    base = {"out": f"~/Downloads/laighthouse-reports/{a.brand}_daily_{D0}.html", "title": f"{a.brand} Daily 보고서",
            "target_date": D0}
    s1 = w.envelope(sr.pick(recs, PERF, time_grain="day", group_by=None, start_date=D7, end_date=D0), "s1.json",
                    {"section": "s1", "time_grain": "day", "group_by": None, "range": f"{D7}~{D0}"})
    s3 = w.envelope(sr.pick(recs, PERF, time_grain="day", group_by=["media"], start_date=D6, end_date=D0), "s3.json",
                    {"section": "s3", "time_grain": "day", "group_by": ["media"], "range": f"{D6}~{D0}"})
    s4 = {}
    for k, d in (("d0", D0), ("d1", D1), ("d7", D7)):
        e = w.envelope(sr.pick(recs, PERF, time_grain="total", group_by="*", start_date=d, end_date=d), f"s4_{k}.json",
                       {"section": "s4", "time_grain": "total", "group_by": "FINE_DIMS", "range": f"{d}~{d}"})
        if e:
            s4[k] = e
    base.update({k: v for k, v in (("s1", s1), ("s3", s3), ("s4", s4)) if v})

    result = {"missing": w.missing, "errors": w.errors}
    disc_env = kit.section_envelope(s3 or s1)
    if disc_env:
        disc = kit.resolve_roles(disc_env)
        base["metric_keys"], base["currency"] = disc["metric_keys"], disc["currency"]
        # metrics_absent: 브랜드가 주지 않는 지표(views·cpv 등) — 묻지 않는다, 그 카드가 조용히 빠질 뿐이다
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

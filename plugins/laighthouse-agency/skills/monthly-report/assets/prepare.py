#!/usr/bin/env python3
"""저장된 MCP 응답 → 빌더 입력(build.json) + Executive Summary 근거(digest). 모델이 응답 원문을 읽거나 옮겨 적지 않게 한다.

플러그인 저장 훅(hooks/save_responses.py)이 laighthouse 응답 원본을 파일로 남긴다. 이 스크립트는 그중 이 브랜드·대상 월의
응답을 (도구 + 인자)로 골라 섹션 입력을 만든다 (M0 = 대상 월, M-1 = 전월, M-5 = 5개월 전):
  s1  get_ad_performance(month, group_by 생략, M-5 1일~M0 말일) + get_target_progress_v2(month M0, media 생략)
  s4  get_ad_performance(month, group_by ["media"], M-5 1일~M0 말일)
  s6  get_ad_performance(month, group_by = FINE_DIMS, M-1 1일~M0 말일) + get_target_progress_v2(month M0, media = 매체마다)

사용법:
  python3 assets/prepare.py --brand <브랜드> --month <M0> --discover   (1차 호출 직후 — 지표 키·매체 목록)
  python3 assets/prepare.py --brand <브랜드> --month <M0>              (2차 호출까지 받은 직후, 1회)
출력(stdout JSON):
  --discover: {"metric_keys", "currency", "media_list", "metrics_absent"} (s4 응답이 없으면 "missing")
  기본: {"base": build.json 경로, "missing": [...], "errors": [...], "discover": {...}, "digest": {...}, "note"?}
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


def month_first(y, m, back):
    n = y * 12 + (m - 1) - back
    return date(n // 12, n % 12 + 1, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--month", required=True)
    ap.add_argument("--discover", action="store_true")
    a = ap.parse_args()
    y, m = map(int, a.month[:7].split("-"))
    M0 = f"{y:04d}-{m:02d}"
    first5, first1 = month_first(y, m, 5), month_first(y, m, 1)
    last0 = month_first(y, m, -1) - timedelta(days=1)
    recs = sr.load_records(a.brand)
    if not recs:
        sr.emit({"note": sr.no_records_note()})
        return

    s4_rec = sr.pick(recs, PERF, time_grain="month", group_by=["media"], start_date=first5, end_date=last0)
    s4_call = {"section": "s4", "time_grain": "month", "group_by": ["media"], "range": f"{first5}~{last0}"}
    if a.discover:
        env = kit.section_envelope({"json": sr.response_text(s4_rec)}) if s4_rec else None
        if not env:
            sr.emit({"missing": [s4_call]})
            return
        disc = kit.resolve_roles(env)
        sr.emit({"metric_keys": disc["metric_keys"], "currency": disc["currency"], "media_list": disc["media_list"],
                 "metrics_absent": disc["missing"]})
        return

    w = sr.Workdir(f"{a.brand}_monthly_{M0}")
    base = {"out": f"~/Downloads/laighthouse-reports/{a.brand}_monthly_{M0}.html", "title": f"{a.brand} Monthly 보고서",
            "month": M0}
    s1 = w.envelope(sr.pick(recs, PERF, time_grain="month", group_by=None, start_date=first5, end_date=last0), "s1.json",
                    {"section": "s1", "time_grain": "month", "group_by": None, "range": f"{first5}~{last0}"})
    target_all = w.text(sr.pick(recs, TARGET, month=M0, media=None), {"section": "s1", "tool": TARGET, "month": M0, "media": None})
    s4 = w.envelope(s4_rec, "s4.json", s4_call)
    s6 = w.envelope(sr.pick(recs, PERF, time_grain="month", group_by="*", start_date=first1, end_date=last0), "s6.json",
                    {"section": "s6", "time_grain": "month", "group_by": "FINE_DIMS", "range": f"{first1}~{last0}"})
    if s1:
        base["s1"] = dict(s1, target_progress=target_all or "")
    if s4:
        base["s4"] = s4
    if s6:
        targets = {k: sr.response_text(r) for k, r in sr.picks(recs, TARGET, "media", month=M0, media="*").items()}
        base["s6"] = dict(s6, targets=targets)

    result = {"missing": w.missing, "errors": w.errors}
    disc_env = kit.section_envelope(s4 or s1)
    if disc_env:
        disc = kit.resolve_roles(disc_env)
        base["metric_keys"], base["currency"] = disc["metric_keys"], disc["currency"]
        if s6:   # 매체 목표가 빠진 매체 — 목표 없는 매체도 응답(한 줄 메시지)은 저장되므로 빠졌으면 다시 부른다
            for n in disc["media_list"]:
                if n not in base["s6"]["targets"]:
                    w.missing.append({"section": "s6", "tool": TARGET, "month": M0, "media": n})
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

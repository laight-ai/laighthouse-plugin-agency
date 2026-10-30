#!/usr/bin/env python3
"""저장된 MCP 응답 → 빌더 입력(build.json), `--build`면 빌더까지 1회에. 모델이 응답 원문(봉투·목표 표)을 옮겨 적지 않게 한다.

플러그인 저장 훅(hooks/save_responses.py)이 laighthouse 응답 원본을 <tmp>/laighthouse_mcp_responses/<session>/에 남긴다.
이 스크립트는 그중 이 브랜드의 가장 최근 세션 응답을 (도구 + 인자)로 골라 빌더 입력을 만든다(shared/assets/saved_responses.py):
  media   get_ad_performance(S~E, day, group_by ["media"], metrics·filters 생략)
  data    get_ad_performance(day, 표 데이터 group_by) — 걸친 달마다(첫 달 S부터, 마지막 달 E까지) 가장 최근 응답
  place   get_ad_performance(day, group_by에 노출 위치 차원) — 걸친 달마다(있을 때만)
  budgets get_target_progress_v2(month = 걸친 달, media 생략) 원문 — 달마다 가장 최근 응답
  history list_campaign_change_raw(date_from S, date_to E) — cursor 없는 첫 응답부터 next_cursor를 따라간 페이지 전부
  names   get_ad_performance(S~E, total, group_by에 *_id) — 변경 이력의 ID에 이름을 붙인다(차원에 *_id가 있을 때만 필요)

사용법 (3단계 MCP 호출을 모두 보낸 직후, 1회):
  python3 assets/prepare.py --brand <브랜드> --target-date <E> [--start-date <S>] --build <<'PYEOF'
  <차원 확인 에러 메시지 원문>
  PYEOF
출력(stdout JSON): {"base": build.json 경로, "missing": [...], "errors": [...], "discover": {...}, "build"?: 빌더 출력, "note"?}
  --build: missing·errors가 없으면 stdin의 차원 확인 원문을 dims로 넣어 빌더(build_report.py)를 바로 부르고 그 출력을 "build"에 담는다.
  --build 없이: base만 만든다 → 빌더에 {"base": <경로>, "dims": "..."}를 넘긴다.
  missing: 저장된 응답이 없는 호출(그 호출만 다시 보내고 재실행). note: 저장된 응답이 하나도 없다 — 훅이 없는 환경.
  --part comment|total|tables|history|mix: 하위 스킬 — 그 섹션만 그린다. 파일 이름 {브랜드}_overall_summary_{part}_{E}.html.
    쓰지 않는 호출은 찾지 않는다: place는 전체·tables에서만, budgets는 tables·history에서 빼고,
    history·names는 전체·history에서만, history는 성과 데이터(media·data)도 찾지 않는다.
  --tables product,target,place,weekly,daily: --part tables에서 고른 표만(없으면 다섯 표 모두).
"""
import argparse
import io
import json
import os
import subprocess
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
import report_kit as kit  # noqa: E402
import saved_responses as sr  # noqa: E402

PLACE_DIMS = ("placement", "노출위치", "노출 위치", "노출_위치", "position")


def month_segments(start, end):
    """[start, end]를 달 경계로 나눈 (시작, 끝) 목록."""
    segs, cur = [], start
    while cur <= end:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        segs.append((cur, min(end, nxt - timedelta(days=1))))
        cur = nxt
    return segs


def day_perf(recs, s, e, keep):
    """day grain·metrics·filters 생략·기간 [s, e] 응답 중 group_by가 keep을 만족하는 가장 최근 기록."""
    for r in reversed(recs):
        gb = (r.get("tool_input") or {}).get("group_by") or []
        if (r["_tool"] == "get_ad_performance" and "__list_dimensions__" not in gb and keep(gb)
                and sr.pick([r], "get_ad_performance", time_grain="day", start_date=s, end_date=e)):
            return r
    return None


def change_pages(recs, S, E, w):
    """변경 이력: cursor 없는 가장 최근 응답부터 next_cursor를 따라 페이지를 모은다 → items 파일 경로.
    빠진 페이지는 missing(그 cursor로 다시 부른다), 에러 응답은 errors."""
    call = {"tool": "list_campaign_change_raw", "date_from": str(S), "date_to": str(E), "limit": 1000}
    pages = [r for r in recs if r["_tool"] == "list_campaign_change_raw"
             and str((r.get("tool_input") or {}).get("date_from"))[:10] == str(S)
             and str((r.get("tool_input") or {}).get("date_to"))[:10] == str(E)]
    items, cursor, seen = [], None, set()
    while True:
        rec = next((r for r in reversed(pages) if ((r.get("tool_input") or {}).get("cursor") or None) == cursor), None)
        if rec is None:
            w.missing.append(dict(call, cursor=cursor) if cursor else call)
            return None
        text = sr.response_text(rec)
        try:
            page = json.loads(text)
        except ValueError:
            page = None
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            w.errors.append({"call": call, "response": str(text).strip().split("\n", 1)[0][:300]})
            return None
        items += page["items"]
        cursor = page.get("next_cursor") or None
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
    path = os.path.join(w.folder, "history.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, ensure_ascii=False)
    return {"json_files": [path.replace("\\", "/")]}


def names_perf(recs, S, E):
    """변경 이력 ID → 이름: total grain·group_by에 *_id가 있는 S~E 응답 중 가장 최근 것.
    이름만 쓰므로 metrics는 무엇이든 된다(광고비 하나만 받아 응답을 줄인다)."""
    for r in reversed(recs):
        ti = r.get("tool_input") or {}
        if (r["_tool"] == "get_ad_performance" and any(str(d).endswith("_id") for d in ti.get("group_by") or [])
                and (ti.get("time_grain") or "day") == "total" and not ti.get("filters")
                and str(ti.get("start_date"))[:10] == str(S) and str(ti.get("end_date"))[:10] == str(E)):
            return r
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--target-date", required=True)
    ap.add_argument("--start-date")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--part", choices=("comment", "total", "tables", "history", "mix"))
    ap.add_argument("--tables", help="--part tables에서 고를 표(쉼표로): product,target,place,weekly,daily")
    a = ap.parse_args()
    E = date.fromisoformat(a.target_date)   # 기준일 = 데이터 마지막 날(최대 어제)
    if sr.future_date_error(E):
        sr.emit({"date_error": sr.future_date_error(E)})
        return
    S = date.fromisoformat(a.start_date) if a.start_date else (E.replace(day=1) - timedelta(days=1)).replace(day=1)
    recs = sr.load_records(a.brand)
    if not recs:
        sr.emit({"note": sr.no_records_note()})
        return

    name = f"{a.brand}_overall_summary_{a.part + '_' if a.part else ''}{E}"
    w = sr.Workdir(name)
    base = {"out": f"~/Downloads/laighthouse-reports/{name}.html", "brand": a.brand, "target_date": str(E)}
    if a.start_date:
        base["start_date"] = str(S)
    tables = [t.strip() for t in (a.tables or "").split(",") if t.strip()] if a.part == "tables" else []
    if a.part:
        base["part"] = a.part
        if tables:
            base["tables"] = tables
    want_place = not a.part or (a.part == "tables" and (not tables or "place" in tables))
    want_perf = a.part != "history"   # 변경 이력만 그리는 history는 성과 데이터·목표를 쓰지 않는다
    dims = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8").read().strip() if a.build else ""
    result = {}
    if not a.part or a.part == "history":
        hist = change_pages(recs, S, E, w)
        if hist:
            base["history"] = hist
        nrec = names_perf(recs, S, E)
        if nrec:
            nm = w.envelope(nrec, "names.json", {"tool": "get_ad_performance", "range": f"{S}~{E}", "time_grain": "total",
                                                 "group_by": "NAME_DIMS"})
            if nm:
                base["names"] = nm
        elif "_id'" in dims:   # 브랜드가 ID 차원을 주는데 이름 호출이 없다 — 이름 없이 ID만 보이게 된다
            w.missing.append({"tool": "get_ad_performance", "range": f"{S}~{E}", "time_grain": "total", "group_by": "NAME_DIMS"})
    if not want_perf:
        result.update({"missing": w.missing, "errors": w.errors, "base": w.write(base)})
        return finish(a, result, w, dims)
    media = w.envelope(day_perf(recs, S, E, lambda gb: gb == ["media"]), "media.json",
                       {"tool": "get_ad_performance", "range": f"{S}~{E}", "time_grain": "day", "group_by": ["media"]})
    if media:
        base["media"] = media
        disc = kit.resolve_roles(kit.section_envelope(media))
        base["metric_keys"], base["currency"] = disc.get("metric_keys"), disc.get("currency")
        # metrics_absent: 브랜드가 주지 않는 지표(views·cpv 등) — 묻지 않는다, 그 칸이 조용히 빠질 뿐이다
        result["discover"] = {"metric_keys": disc.get("metric_keys"), "currency": disc.get("currency"),
                              "metrics_absent": disc.get("missing") or []}

    data_files, place_files = [], []
    for s, e in month_segments(S, E):
        is_place = lambda gb: bool(set(gb) & set(PLACE_DIMS))  # noqa: E731
        t = w.envelope(day_perf(recs, s, e, lambda gb: gb != ["media"] and bool(gb) and not is_place(gb)), f"data_{s}.json",
                       {"tool": "get_ad_performance", "range": f"{s}~{e}", "time_grain": "day", "group_by": "FINE_DIMS"})
        if t:
            data_files += t["json_files"]
        place = day_perf(recs, s, e, is_place) if want_place else None
        if place:   # 노출 위치 차원이 없는 브랜드는 부르지 않는다 — 없어도 missing이 아니다
            p = w.envelope(place, f"place_{s}.json", {"tool": "get_ad_performance", "range": f"{s}~{e}", "group_by": "PLACE"})
            if p:
                place_files += p["json_files"]
    if data_files:
        base["data"] = {"json_files": data_files}
    if place_files:
        base["place"] = {"json_files": place_files}

    budgets = []
    for s, e in month_segments(S, E) if a.part != "tables" else ():   # 표만 그리는 tables는 목표를 쓰지 않는다
        m = f"{s.year:04d}-{s.month:02d}"
        text = w.text(sr.pick(recs, "get_target_progress_v2", month=m, media=None),
                      {"tool": "get_target_progress_v2", "month": m, "media": None})
        if text is not None:
            budgets.append({"month": m, "target_progress": text})
    base["budgets"] = budgets

    result.update({"missing": w.missing, "errors": w.errors, "base": w.write(base)})
    finish(a, result, w, dims)


def finish(a, result, w, dims):
    """--build면 missing·errors가 없을 때 빌더를 부르고, 결과를 내보낸다."""
    if a.build and not w.missing and not w.errors:
        out = subprocess.run([sys.executable, os.path.join(HERE, "build_report.py")], capture_output=True,
                             input=json.dumps({"base": result["base"], "dims": dims}, ensure_ascii=False).encode("utf-8"))
        text = out.stdout.decode("utf-8", "replace").strip()
        try:
            result["build"] = json.loads(text)
        except ValueError:   # 빌더가 멈췄다(대조 검증 실패 등) — 그 메시지를 그대로 돌려준다
            result["build_error"] = (out.stderr.decode("utf-8", "replace").strip() or text)[-1500:]
    sr.emit(result)


if __name__ == "__main__":
    main()

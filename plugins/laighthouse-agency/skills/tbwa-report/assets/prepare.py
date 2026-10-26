#!/usr/bin/env python3
"""저장된 MCP 응답 → 빌더 입력(build.json). 모델이 응답 원문(봉투·목표 표)을 옮겨 적지 않게 한다.

플러그인 저장 훅(hooks/save_responses.py)이 laighthouse 응답 원본을 <tmp>/laighthouse_mcp_responses/<session>/에 남긴다.
이 스크립트는 그중 이 브랜드·기간의 응답을 (도구 + 인자)로 골라 빌더 입력을 만든다:
  media   get_ad_performance(S~E, day, group_by ["media"], metrics·filters 생략)
  data    get_ad_performance(day, 표 데이터 group_by) — 걸친 달마다(첫 달 S부터, 마지막 달 E까지) 가장 최근 응답
  place   get_ad_performance(day, group_by에 노출 위치 차원) — 걸친 달마다(있을 때만)
  budgets get_target_progress_v2(month = 걸친 달, media 생략) 원문 — 달마다 가장 최근 응답

사용법 (3단계 MCP 호출을 모두 보낸 직후, 1회):
  python3 assets/prepare.py --brand <브랜드> --target-date <D> [--start-date <S>]
출력(stdout JSON): {"base": build.json 경로, "missing": [...], "errors": [...], "discover": {...}, "note"?}
  → 빌더: python3 assets/build_report.py 에 {"base": <경로>, "dims": "<차원 확인 에러 메시지 원문>"}를 넘긴다.
  missing: 저장된 응답이 없는 호출(그 호출만 다시 보내고 재실행). note: 저장된 응답이 하나도 없다 — 훅이 없는 환경.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
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

ROOT = os.path.join(tempfile.gettempdir(), "laighthouse_mcp_responses")
WORK_ROOT = os.path.join(tempfile.gettempdir(), "laighthouse_prepare")
MAX_AGE = 24 * 3600
PLACE_DIMS = ("placement", "노출위치", "노출 위치", "노출_위치", "position")
SPILL_RE = re.compile(r"Output has been saved to (\S+?)\.?\s*$", re.M)


def unwrap(text):
    """{"result": "<본문>"} 래퍼·[{"type":"text","text":…}] 블록 리스트를 벗긴다."""
    for _ in range(3):
        if not isinstance(text, str) or not text.lstrip().startswith(("{", "[")):
            return text
        try:
            obj = json.loads(text)
        except ValueError:
            return text
        if isinstance(obj, dict) and set(obj) == {"result"}:
            text = obj["result"] if isinstance(obj["result"], str) else json.dumps(obj["result"], ensure_ascii=False)
        elif isinstance(obj, list) and obj and all(isinstance(b, dict) and "text" in b for b in obj):
            text = "\n".join(b["text"] for b in obj)
        else:
            return text
    return text


def response_text(rec):
    text = rec.get("response")
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    m = SPILL_RE.search(text) if len(text) < 5000 else None
    path = rec.get("spilled_path") or (m.group(1) if m else None)
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            pass
    return unwrap(text)


def load_records(brand):
    out, now = [], time.time()
    try:
        sessions = os.listdir(ROOT)
    except OSError:
        return out
    for s in sessions:
        folder = os.path.join(ROOT, s)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if not name.endswith(".json"):
                continue
            try:
                if now - os.path.getmtime(path) > MAX_AGE:
                    continue
                with open(path, encoding="utf-8") as f:
                    rec = json.load(f)
            except (OSError, ValueError):
                continue
            ti = rec.get("tool_input") or {}
            if isinstance(ti, dict) and ti.get("brand_name") == brand:
                rec["_tool"] = str(rec.get("tool_name") or "").rsplit("__", 1)[-1]
                out.append(rec)
    out.sort(key=lambda r: r.get("saved_at") or 0)
    return out


def month_segments(start, end):
    """[start, end]를 달 경계로 나눈 (시작, 끝) 목록."""
    segs, cur = [], start
    while cur <= end:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        segs.append((cur, min(end, nxt - timedelta(days=1))))
        cur = nxt
    return segs


def is_day_perf(ti, s, e):
    return ((ti.get("time_grain") or "day") == "day" and str(ti.get("start_date"))[:10] == str(s)
            and str(ti.get("end_date"))[:10] == str(e) and ti.get("metrics") is None and not ti.get("filters"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--target-date", required=True)
    ap.add_argument("--start-date")
    a = ap.parse_args()
    D = date.fromisoformat(a.target_date)
    E = D - timedelta(days=1)
    S = date.fromisoformat(a.start_date) if a.start_date else (E.replace(day=1) - timedelta(days=1)).replace(day=1)
    recs = load_records(a.brand)
    result = {"missing": [], "errors": []}
    if not recs:
        result = {"note": (f"저장된 응답이 없다({ROOT}) — 저장 훅이 동작하지 않는 환경이다. 응답 원문을 build.json에 직접 "
                           "넣는 기존 방법(SKILL.md 「훅이 없을 때」)으로 진행한다.")}
        os.write(1, json.dumps(result, ensure_ascii=False).encode("utf-8"))
        return

    folder = os.path.join(WORK_ROOT, re.sub(r"[^\w.-]", "_", f"{a.brand}_tbwa_{D}"))
    os.makedirs(folder, exist_ok=True)

    def save_env(name, rec, call):
        text = response_text(rec)
        try:
            env = json.loads(text)
        except ValueError:
            env = None
        if not isinstance(env, dict) or not isinstance(env.get("rows"), list):
            result["errors"].append({"call": call, "response": str(text).strip().split("\n", 1)[0][:300]})
            return None
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(env, f, ensure_ascii=False)
        return path.replace("\\", "/")

    perf = [r for r in recs if r["_tool"] == "get_ad_performance"]
    media = [r for r in perf if is_day_perf(r["tool_input"], S, E) and (r["tool_input"].get("group_by") or []) == ["media"]]
    base = {"out": f"~/Downloads/laighthouse-reports/{a.brand}_tbwa_{D}.html", "brand": a.brand, "target_date": str(D)}
    if a.start_date:
        base["start_date"] = str(S)
    media_path = None
    if media:
        media_path = save_env("media.json", media[-1], {"group_by": ["media"], "range": f"{S}~{E}"})
    else:
        result["missing"].append({"tool": "get_ad_performance", "range": f"{S}~{E}", "time_grain": "day", "group_by": ["media"]})
    if media_path:
        base["media"] = {"json_files": [media_path]}
        with open(media_path, encoding="utf-8") as f:
            disc = kit.resolve_roles(json.load(f)) if hasattr(kit, "resolve_roles") else None
        if disc:
            base["metric_keys"], base["currency"] = disc.get("metric_keys"), disc.get("currency")
            # metrics_absent: 브랜드가 주지 않는 지표(views·cpv 등) — 묻지 않는다, 그 칸이 조용히 빠질 뿐이다
            result["discover"] = {"metric_keys": disc.get("metric_keys"), "currency": disc.get("currency"),
                                  "metrics_absent": disc.get("missing") or []}

    data_files, place_files = [], []
    for i, (s, e) in enumerate(month_segments(S, E)):
        seg = [r for r in perf if is_day_perf(r["tool_input"], s, e) and (r["tool_input"].get("group_by") or []) != ["media"]]
        tables = [r for r in seg if not set(r["tool_input"].get("group_by") or []) & set(PLACE_DIMS)]
        places = [r for r in seg if set(r["tool_input"].get("group_by") or []) & set(PLACE_DIMS)]
        if tables:
            p = save_env(f"data_{s}.json", tables[-1], {"range": f"{s}~{e}", "group_by": tables[-1]["tool_input"].get("group_by")})
            if p:
                data_files.append(p)
        else:
            result["missing"].append({"tool": "get_ad_performance", "range": f"{s}~{e}", "time_grain": "day", "group_by": "FINE_DIMS"})
        if places:
            p = save_env(f"place_{s}.json", places[-1], {"range": f"{s}~{e}", "group_by": places[-1]["tool_input"].get("group_by")})
            if p:
                place_files.append(p)
    if data_files:
        base["data"] = {"json_files": data_files}
    if place_files:
        base["place"] = {"json_files": place_files}

    budgets = []
    for s, e in month_segments(S, E):
        m = f"{s.year:04d}-{s.month:02d}"
        hits = [r for r in recs if r["_tool"] == "get_target_progress_v2" and str(r["tool_input"].get("month")) == m
                and r["tool_input"].get("media") in (None, "", "all")]
        if hits:
            budgets.append({"month": m, "target_progress": response_text(hits[-1])})
        else:
            result["missing"].append({"tool": "get_target_progress_v2", "month": m, "media": None})
    base["budgets"] = budgets

    path = os.path.join(folder, "build.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False)
    result["base"] = path.replace("\\", "/")
    os.write(1, json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()

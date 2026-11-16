#!/usr/bin/env python3
"""소재 성과 — 저장된 MCP 응답 → 채팅용 표(표로 보기) 또는 썸네일 포함 HTML 보고서. 모델이 응답 원문을 읽지 않게 한다.

플러그인 저장 훅(hooks/save_responses.py)이 laighthouse 응답 원본을 파일로 남긴다. 이 스크립트는 그중 이 브랜드의 응답을
(도구 + 인자)로 골라 쓴다:
  성과   get_ad_performance(S~E, total, group_by = media + 소재 차원(ad_name 포함), metrics·filters 생략)
  메타   get_ad_creative_info(brand_name만)                      ← 보고서 모드만
  이미지 get_ad_creative_image(ad_id = 메타 항목 id)              ← 보고서 모드만, image_calls에 나온 것

사용법:
  python3 assets/creative_report.py --brand <브랜드> --start-date <S> --end-date <E> --mode table|report
         [--media <매체> ...] [--sort cost|ctr|roas|click|conversion] [--top 3] [--image-file <id>=<경로> ...]
보고서 화면 = 매체별 상위 소재(썸네일 카드) + 세부 광고 성과 표(썸네일 열, 광고 단계까지 펼친 채로 시작). 이미지가 들어가는 두 부분만 둔다.
출력(stdout JSON):
  table  → {"chat": "<채팅에 그대로 낼 마크다운>", "facts": {...}, "digest": {...}}
  report → {"image_calls": [id, ...]}   이 이미지를 아직 안 받았다 — 한 메시지에 모두 부르고 같은 명령을 다시 실행한다
           {"out": "<html 경로>", "facts": {...}}
  공통   → {"missing": [...]} 호출이 빠졌다 · {"error": "..."} 멈춘 이유 · {"note": ...} 저장 훅이 없는 호스트
랭킹 규칙: 매체마다 정렬 지표 상위 N개. CTR·ROAS·CVR처럼 비율 정렬은 최소 표본(노출 ≥ 1,000 그리고 광고비 ≥ 그 매체
광고비의 1%)을 채운 소재만 — 하나도 없으면 전체 소재로 폴백한다. 동점은 광고비가 큰 소재 우선.
"""
import argparse
import base64
import json
import os
import re
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(HERE, "..", "shared", "assets"),           # zip 번들
             os.path.join(HERE, "..", "..", "..", "shared", "assets")):  # 개발 트리
    if os.path.exists(os.path.join(cand, "saved_responses.py")):
        SHARED = os.path.normpath(cand)
        sys.path.insert(0, SHARED)
        break
else:
    raise SystemExit("saved_responses.py를 찾을 수 없다 (shared/assets)")
import saved_responses as sr  # noqa: E402

sys.path.insert(0, HERE)
import creative_digest as cd  # noqa: E402
from creative_common import ATOMS, MIN_IMP, MIN_SHARE  # noqa: E402  (ATOMS 순서 = 보고서 화면 JS의 원자 지표 순서)

KEYS = {   # 지표 키 후보(대소문자 무시, 정확히 같은 이름) — 처음 있는 것
    "cost": ("광고비", "cost", "spend", "spending"),
    "impression": ("노출", "impression", "impressions"),
    "click": ("클릭", "click", "clicks"),
    "conversion": ("전환", "conversions", "conversion"),
    "revenue": ("매출", "revenue", "purchase_value", "conversion_value"),
    "view": ("조회수", "video_views", "views", "view"),
}
SORT_LABEL = {"cost": "광고비", "ctr": "CTR", "roas": "ROAS", "click": "클릭", "conversion": "전환"}
RATIO_SORTS = ("ctr", "roas")
MAX_IMAGES = 30
IMG_RE = re.compile(r"^[A-Za-z0-9+/=\s]{200,}$")
IMG_SRC_RE = re.compile(r"\[Image: source: ([^\]]+)\]")


def resolve_keys(metrics, rows=()):
    """원자 지표마다 응답에 있는 후보 지표 목록(값이 있는 것 먼저). 같은 뜻의 지표를 매체마다 다른 이름으로 내보내는
    브랜드(예: Meta는 spending, 다른 매체는 광고비)가 있어 행마다 값이 있는 첫 후보를 쓴다(`pick`)."""
    low = {str(m).lower(): m for m in metrics or []}
    filled = {k for r in rows for k, v in r.items() if v is not None}
    out = {}
    for k, cands in KEYS.items():
        found = [low[c.lower()] for c in cands if c.lower() in low]
        out[k] = [m for m in found if m in filled] or found[:1]
    return out


def pick(row, names):
    """행에서 값이 있는 첫 후보 지표의 값(없으면 0)."""
    return next((num(row[m]) for m in names if row.get(m) is not None), 0)


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def creative_rows(env, keys, media_filter):
    """응답 행 → 소재(매체·캠페인·광고그룹·ad_id·소재명) 단위 원자 지표. 같은 소재 행은 더한다(source가 갈린 경우)."""
    want = {m.lower() for m in media_filter or []}
    out = {}
    for r in env.get("rows") or []:
        media = str(r.get("media") or "-")
        if want and media.lower() not in want:
            continue
        ident = (media, r.get("campaign_name"), r.get("ad_group_name"), r.get("ad_id"), r.get("ad_name"))
        e = out.setdefault(ident, {"media": media, "source": r.get("source"), "campaign_name": r.get("campaign_name"),
                                   "ad_group_name": r.get("ad_group_name"), "ad_id": r.get("ad_id"),
                                   "ad_name": r.get("ad_name"), "cost": 0, "impression": 0, "click": 0,
                                   "conversion": 0, "revenue": 0, "view": 0})
        for k, names in keys.items():
            e[k] += pick(r, names)
    for e in out.values():
        name = e["ad_name"] if e["ad_name"] not in (None, "", "-") else None
        e["name"] = name or "%s (소재명 없음)" % (e["ad_group_name"] or e["campaign_name"] or "-")
        ratios(e)
    return [e for e in out.values() if e["cost"] or e["impression"]]


def ratios(e):
    imp, clk, cost = e["impression"], e["click"], e["cost"]
    e["ctr"] = clk / imp * 100 if imp else None
    e["cpc"] = cost / clk if clk else None
    e["cvr"] = e["conversion"] / clk * 100 if clk else None
    e["roas"] = e["revenue"] / cost * 100 if cost else None
    return e


def rank(items, sort, top):
    total_cost = sum(e["cost"] for e in items)
    pool = items
    fallback = False
    if sort in RATIO_SORTS:
        pool = [e for e in items if e["impression"] >= MIN_IMP and e["cost"] >= total_cost * MIN_SHARE]
        if not pool:
            pool, fallback = items, True
        pool = [e for e in pool if e[sort] is not None]
    pool = sorted(pool, key=lambda e: (-(e[sort] or 0), -e["cost"]))
    return pool[:top], fallback


def media_summary(items):
    s = dict({k: 0 for k in ATOMS}, media=items[0]["media"], creatives=len(items))
    for e in items:
        for k in ATOMS:
            s[k] += e[k]
    return ratios(s)


# ── 썸네일 ──────────────────────────────────────────────────────────────────────────────────────────────
def creative_items(recs):
    rec = next((r for r in reversed(recs) if r["_tool"] == "get_ad_creative_info"
                and not any((r.get("tool_input") or {}).get(k) for k in ("name_query", "source", "limit"))), None)
    if rec is None:
        return None
    try:
        obj = json.loads(sr.response_text(rec))
    except ValueError:
        return []
    return [it for it in (obj.get("items") or []) if isinstance(it, dict)]


def match_item(e, items):
    """ad_id가 같으면 그 항목, 없으면 소재명(ad_name·ad_display_name)이 정확히 같은 첫 항목. 이미지가 RESOLVED인 것만."""
    ok = [it for it in items if (it.get("image_lookup_status") or "RESOLVED") == "RESOLVED" and it.get("id") is not None]
    if e["ad_id"]:
        hit = next((it for it in ok if str(it.get("ad_id")) == str(e["ad_id"])), None)
        if hit:
            return hit
    if e["ad_name"] not in (None, "", "-"):
        return next((it for it in ok if e["ad_name"] in (it.get("ad_name"), it.get("ad_display_name"))), None)
    return None


def find_image(obj):
    """저장된 이미지 응답(블록 리스트·dict) → (mime, base64). 못 찾으면 None."""
    if isinstance(obj, dict):
        src = obj.get("source") if isinstance(obj.get("source"), dict) else obj
        data = src.get("data")
        if isinstance(data, str) and IMG_RE.match(data[:4000]):
            return src.get("mimeType") or src.get("media_type") or "image/jpeg", data
        for v in obj.values():
            got = find_image(v)
            if got:
                return got
    if isinstance(obj, list):
        for v in obj:
            got = find_image(v)
            if got:
                return got
    return None


def image_uri(recs, item_id, files):
    path = files.get(str(item_id))
    if path == "-":   # 이미지를 못 받았다 — 빈 썸네일
        return ""
    if path and os.path.exists(path):
        ext = os.path.splitext(path)[1].lower().lstrip(".") or "jpeg"
        with open(path, "rb") as f:
            return "data:image/%s;base64,%s" % ("jpeg" if ext == "jpg" else ext, base64.b64encode(f.read()).decode())
    rec = next((r for r in reversed(recs) if r["_tool"] == "get_ad_creative_image"
                and str((r.get("tool_input") or {}).get("ad_id")) == str(item_id)), None)
    if rec is None:
        return None
    text = rec.get("response") if isinstance(rec.get("response"), str) else sr.response_text(rec)
    try:
        got = find_image(json.loads(text))
    except (TypeError, ValueError):
        got = None
    if got:
        return "data:%s;base64,%s" % (got[0], re.sub(r"\s", "", got[1]))
    # 호스트가 이미지를 `[Image: source: <경로>]` 안내로 바꿔 넘긴 경우 — 그 파일을 읽는다
    src = IMG_SRC_RE.search(text or "")
    if src and os.path.exists(src.group(1).strip()):
        return image_uri([], item_id, {str(item_id): src.group(1).strip()})
    # 에러 응답(썸네일 없음 등)이면 빈 썸네일, 아니면 이미지를 못 남긴 것 — image_calls로 다시 드러내 --image-file 경로를 타게 한다
    return "" if re.search(r"error|ValueError", text or "", re.I) else None


# ── 출력 ────────────────────────────────────────────────────────────────────────────────────────────────
def fmt(v, kind, cur):
    if v is None:
        return "-"
    if kind == "money":
        return "%s%s" % (cur, format(round(v), ","))
    if kind == "pct":
        return "%.1f%%" % v
    if kind == "ctr":
        return "%.2f%%" % v
    return format(round(v), ",")


def columns(has):
    cols = [("impression", "노출", "int"), ("click", "클릭", "int"), ("ctr", "CTR", "ctr"), ("cpc", "CPC", "money"),
            ("cost", "비용", "money")]
    if has["conversion"]:
        cols += [("conversion", "전환", "int"), ("cvr", "CVR", "pct")]
    if has["revenue"]:
        cols += [("roas", "ROAS", "pct")]
    return cols


def chat_markdown(brand, s, e, groups, sort, cols, cur, notes):
    lines = ["**%s 소재 성과** (%s ~ %s · %s 상위)" % (brand, s, e, SORT_LABEL[sort]), ""]
    for g in groups:
        m = g["summary"]
        head = "**%s** — 비용 %s · CTR %s" % (m["media"], fmt(m["cost"], "money", cur), fmt(m["ctr"], "ctr", cur))
        head += " · ROAS %s" % fmt(m["roas"], "pct", cur) if any(c[0] == "roas" for c in cols) else " · CPC %s" % fmt(m["cpc"], "money", cur)
        lines += [head, "", "| # | 소재명 | " + " | ".join(c[1] for c in cols) + " |",
                  "|---|---|" + "---:|" * len(cols)]
        for i, it in enumerate(g["top"], 1):
            lines.append("| %d | %s | %s |" % (i, it["name"].replace("|", "/"),
                                               " | ".join(fmt(it[c[0]], c[2], cur) for c in cols)))
        if g["fallback"]:
            lines.append("")
            lines.append("_최소 표본(노출 1,000·광고비 1%)을 채운 소재가 없어 전체 소재로 순위를 냈습니다._")
        lines.append("")
    lines += notes
    return "\n".join(lines).rstrip() + "\n\n— by LaightAI"


def find_perf(recs, start, end, group_by=None):
    """기간의 소재 성과 응답(가장 최근). group_by를 주면 그 차원 구성과 같은 응답만 — 직전 기간은 이번 기간과
    차원이 같아야 소재 키(ad_id 등)가 맞는다."""
    for r in reversed(recs):
        ti = r.get("tool_input") or {}
        gb = ti.get("group_by") or []
        if (r["_tool"] == "get_ad_performance" and not ti.get("filters") and ti.get("metrics") is None
                and (ti.get("time_grain") or "day") == "total" and "ad_name" in gb
                and (group_by is None or sorted(gb) == sorted(group_by))
                and str(ti.get("start_date"))[:10] == start and str(ti.get("end_date"))[:10] == end):
            return r
    return None


def load_env(rec):
    try:
        env = json.loads(sr.response_text(rec))
        return env if isinstance(env.get("rows"), list) else None
    except (ValueError, AttributeError):
        return None


def prev_period(start, end):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    n = (e - s).days + 1
    return (s - timedelta(days=n)).isoformat(), (s - timedelta(days=1)).isoformat()


def path_of(e):
    return (e["media"], e["campaign_name"] or "-", e["ad_group_name"] or "-", (e["ad_id"], e["ad_name"]))


def detail_tree(rows, prev_rows, thumbs):
    """매체 › 캠페인 › 광고그룹 › 소재 트리. 노드 = {n 이름, c 이번 기간 원자 지표, p 직전 기간(없으면 null), t 썸네일, k 하위}.
    직전 기간 값은 같은 경로의 직전 기간 소재를 더한 것이다(직전 기간에만 있던 소재도 위 단계 합에 들어간다)."""
    prev = {}
    for e in prev_rows if prev_rows is not None else []:
        path = path_of(e)
        for d in range(1, 5):
            acc = prev.setdefault(path[:d], [0] * len(ATOMS))
            for i, k in enumerate(ATOMS):
                acc[i] += e[k]
    root = {"k": {}}
    for e in sorted(rows, key=lambda x: -x["cost"]):
        path, node = path_of(e), root
        for d in range(1, 5):
            key = path[d - 1]
            if key not in node["k"]:
                node["k"][key] = {"n": (e["ad_name"] if e["ad_name"] not in (None, "", "-") else "(미지정)") if d == 4 else key, "c": [0] * len(ATOMS),
                                  "p": prev.get(path[:d], [0] * len(ATOMS)) if prev_rows is not None else None, "k": {}}
            node = node["k"][key]
            for i, k in enumerate(ATOMS):
                node["c"][i] += e[k]
        if thumbs.get(id(e)):
            node["t"] = thumbs[id(e)]

    def flat(node):
        kids = sorted(node["k"].values(), key=lambda x: -x["c"][0])
        for k in kids:
            k["k"] = flat(k)
        return kids
    return flat(root)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--start-date", required=True)
    ap.add_argument("--end-date", required=True)
    ap.add_argument("--mode", choices=("table", "report"), default="table")
    ap.add_argument("--media", nargs="*", default=[])
    ap.add_argument("--sort", choices=tuple(SORT_LABEL), default="cost")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--image-file", nargs="*", default=[])
    ap.add_argument("--out")
    a = ap.parse_args()

    recs = sr.load_records(a.brand)
    if not recs:
        return sr.emit({"note": "저장된 응답 없음 — 저장 훅이 없는 호스트다"})
    perf = find_perf(recs, a.start_date, a.end_date)
    if perf is None:
        return sr.emit({"missing": [{"tool": "get_ad_performance", "start_date": a.start_date, "end_date": a.end_date,
                                     "time_grain": "total", "group_by": "media + 소재 차원(ad_name 포함)"}]})
    env = load_env(perf)
    if env is None:
        return sr.emit({"error": "성과 응답이 에러다: " + str(sr.response_text(perf)).strip()[:300]})
    keys = resolve_keys(env.get("metrics"), env["rows"])
    if not all(keys[k] for k in ("cost", "impression", "click")):
        return sr.emit({"error": "광고비·노출·클릭 지표를 찾지 못했다", "metrics": env.get("metrics")})
    cur = next((u for k, u in (env.get("metric_units") or {}).items() if k in keys["cost"] and u), "")
    cur = {"KRW": "₩", "USD": "$"}.get(cur, cur if len(cur) <= 2 else "")

    rows = creative_rows(env, keys, a.media)
    if not rows:
        return sr.emit({"error": "이 기간·매체에 소재 성과가 없다", "media_in_data": sorted({str(r.get("media")) for r in env["rows"]})})
    has = {"conversion": bool(keys["conversion"]) and any(e["conversion"] for e in rows),
           "revenue": bool(keys["revenue"]) and any(e["revenue"] for e in rows),
           "view": bool(keys["view"]) and any(e["view"] for e in rows)}
    sort = a.sort
    if sort == "roas" and not has["revenue"]:
        sort = "click"
    if sort == "conversion" and not has["conversion"]:
        sort = "cost"
    sorts = ["cost", "ctr", "roas" if has["revenue"] else "click"] + (["conversion"] if has["conversion"] else [])
    if sort not in sorts:   # 매출이 있는 브랜드에 --sort click — 화면 탭·인쇄 머리말·썸네일 우선순위가 이 기준을 알게 한다
        sorts.append(sort)

    by_media = {}
    for e in rows:
        by_media.setdefault(e["media"], []).append(e)
    order = sorted(by_media, key=lambda m: -sum(x["cost"] for x in by_media[m]))
    notes = []
    if not has["revenue"]:
        notes.append("_매출 지표가 없어 ROAS 대신 CPC를 보여 줍니다._")

    # 직전 기간(같은 길이) — 표 모드는 있으면 쓰고, 보고서 모드는 필수
    p_start, p_end = prev_period(a.start_date, a.end_date)
    perf_group_by = (perf.get("tool_input") or {}).get("group_by") or []
    prev_rec = find_perf(recs, p_start, p_end, perf_group_by)
    prev_env = load_env(prev_rec) if prev_rec else None
    prev_rows = creative_rows(prev_env, resolve_keys(prev_env.get("metrics"), prev_env["rows"]), a.media) if prev_env else None
    # 비교는 이번 기간에 집행한 매체끼리만 — 직전 기간에만 집행한 매체는 화면·요약 어디에도 나오지 않는다
    if prev_rows is not None:
        prev_rows = [e for e in prev_rows if e["media"] in by_media]
    if a.mode == "table":
        digest = cd.build(rows, prev_rows, has, cur, "%s ~ %s" % (a.start_date, a.end_date), "%s ~ %s" % (p_start, p_end))
        groups = []
        for m in order:
            top, fb = rank(by_media[m], sort, a.top)
            groups.append({"summary": media_summary(by_media[m]), "top": top, "fallback": fb})
        return sr.emit({"chat": chat_markdown(a.brand, a.start_date, a.end_date, groups, sort, columns(has), cur, notes),
                        "facts": {"sort": sort, "media": order}, "digest": digest})

    # ── 보고서 ──
    items = creative_items(recs)
    missing = []
    if items is None:
        missing.append({"tool": "get_ad_creative_info", "brand_name": a.brand})
    if prev_env is None:   # 없거나 에러 응답 — 비교 없이 그리지 않고 다시 부르게 한다
        missing.append({"tool": "get_ad_performance", "start_date": p_start, "end_date": p_end, "time_grain": "total",
                        "group_by": perf_group_by})
    if missing:
        return sr.emit({"missing": missing})

    # 썸네일(최대 MAX_IMAGES개): TOP 표(정렬 지표마다 상위 N개 — 화면에서 기준을 바꿔도 붙어 있다)를 먼저, 그다음 광고비 순
    files = dict(p.split("=", 1) for p in a.image_file if "=" in p)
    want = [e for m in order for s in sorts for e in rank(by_media[m], s, a.top)[0]]
    want += sorted(rows, key=lambda e: -e["cost"])
    need, picked = [], {}
    for e in want:
        if id(e) in picked:
            continue
        it = match_item(e, items)
        if it is None or (it["id"] not in need and len(need) >= MAX_IMAGES):
            continue
        picked[id(e)] = it["id"]
        if it["id"] not in need:
            need.append(it["id"])
    uris = {i: image_uri(recs, i, files) for i in need}
    todo = [i for i, u in uris.items() if u is None]
    if todo:
        return sr.emit({"image_calls": todo})
    thumbs = {k: uris.get(v) or None for k, v in picked.items()}

    data = {"brand": a.brand, "start": a.start_date, "end": a.end_date, "currency": cur, "top": a.top,
            "sort": sort, "sorts": [[s, SORT_LABEL[s]] for s in sorts], "has": has,
            "min": {"impression": MIN_IMP, "share": MIN_SHARE}, "media": [],
            "prev": {"start": p_start, "end": p_end, "ok": prev_rows is not None},
            "tree": detail_tree(rows, prev_rows, thumbs)}
    fields = ("name", "campaign_name", "ad_group_name", "cost", "impression", "click", "conversion", "revenue", "view",
              "ctr", "cpc", "cvr", "roas")
    # 소재별 직전 기간 원자 지표(카드 증감·신규 표시용). 같은 소재 = 매체·캠페인·광고그룹·ad_id·소재명이 같은 것
    pkey = lambda e: (e["media"], e["campaign_name"], e["ad_group_name"], e["ad_id"], e["ad_name"])  # noqa: E731
    pmap = {pkey(e): [e[k] for k in ATOMS] for e in prev_rows or []}
    for m in order:
        data["media"].append({"summary": media_summary(by_media[m]),
                              "rows": [dict({k: e[k] for k in fields}, thumb=thumbs.get(id(e)), prev=pmap.get(pkey(e)))
                                       for e in by_media[m]]})
    with open(os.path.join(HERE, "report-template.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(SHARED, "report_kit.css"), encoding="utf-8") as f:
        kit_css = f.read()
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("/*__KIT_CSS__*/", kit_css).replace('"__DATA__"', blob).replace("__TITLE__", "%s 소재 성과" % a.brand)
    out = a.out or os.path.join(os.path.expanduser("~"), "Downloads", "laighthouse-reports",
                                "%s_creative_%s_%s.html" % (re.sub(r'[\\/:*?"<>|]', "_", a.brand), a.start_date, a.end_date))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    sr.emit({"out": out.replace("\\", "/"), "facts": {"sort": sort, "media": order,
                                                      "thumbnails": sum(1 for u in uris.values() if u),
                                                      "thumbnail_missing": sum(1 for u in uris.values() if not u)}})


if __name__ == "__main__":
    main()

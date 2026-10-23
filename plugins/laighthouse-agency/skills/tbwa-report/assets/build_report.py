#!/usr/bin/env python3
"""TBWA 보고서 조립기 — 미리 검증된 asset 스크립트.

MCP 응답 원문(봉투·목표 표)을 그대로 받아 Daily/Weekly Comment를 규칙으로 만들고, 표 데이터(일 × 가장 잘게 쪼갠 차원)를
열 기반으로 HTML에 넣는다. Total/Monthly Summary와 Product·Target·Weekly·Daily 표는 브라우저(assets/tbwa_report.js)가
그 데이터로 묶어 그린다(월·미디어 필터, 디멘전·지표 설정, 접기).

기간 (기준일 D, 데이터 마지막 날 E = D-1): 집계 기간 = start_date ~ E (start_date를 안 주면 E의 전월 1일).
집계 기간이 걸친 달마다 Monthly Summary·월 필터·Mix 월 칸이 생긴다(366일까지).

사용법:
  python3 assets/build_report.py <입력.json>      (또는 stdin으로 JSON)

입력 (JSON):
{
  "out": "~/Downloads/laighthouse-reports/{브랜드}_tbwa_2026-10-08.html",   # 필수
  "brand": "{브랜드}",                                                     # 필수 (제목 = 브랜드명)
  "target_date": "2026-10-08",                                           # 필수 (기준일 D)
  "start_date": "2026-07-15",    # 선택 — 집계 시작일(사용자가 말한 날). 없으면 E의 전월 1일
  "skeleton": true,              # 선택 — 데이터 없이 틀만
  "metric_keys": {...}, "currency": "₩",          # discover.py 출력 그대로
  "dims": "<차원 확인(group_by [\"__list_dimensions__\"]) 에러 메시지 원문>",   # 필수 — 빠진 차원이 있으면 멈춘다
  "data": {"json_files": ["<첫 달 응답>", "<다음 달 응답>", ...]},
        # day grain, group_by = FINE_DIMS, 집계 기간을 달마다 나눠(첫 달은 시작일부터, 마지막 달은 E까지) 받은 응답을 함께 넣는다
  "media": {"json_files": [...]} 또는 {"json": "..."},
        # day grain, group_by ["media"], 집계 기간 전체 — 대조 검증(매체별 일 합 = 표 데이터 합)
  "budgets": [{"month": "2026-09", "target_progress": "<get_target_progress_v2(media 생략) 원문>"},
              {"month": "2026-10", "target_progress": "<원문>"}]
        # 첫째 표(metric|target|…) = 전체 합계, 둘째 표(media|campaign_name|included|metric|target|…) = 매체·캠페인 행.
        # cost 행 = 예산(Gross), impression·click·views·ctr·vtr·cpm·cpc·cpv 행 = 목표 영역(e.*)·Mix 목표. 행이 없으면 빈칸.
        # 항목에 범위 키(media·상품·campaign_name·ad_group_name)를 주면 첫째 표를 그 범위로 읽는다(그 인자로 부른 경우).
  "place": {"json_files": ["<첫 달 응답>", ...]}
        # 선택 — Placement 표. day grain, group_by = [media, (ad_type 또는 상품), 노출 위치 차원(PLACE_DIMS 중 브랜드가 주는 것)],
        # 달마다 나눠 받는다. 표 데이터와 따로 받아(행 수가 적다) Placement 표만 그린다. 없거나 노출 위치 차원이 없으면 표가 빠진다.
}
- 응답에 없는 차원(예: 상품)은 표·디멘전 설정에 나오지 않는다 — 조용히 빠진다.
- 출력(stdout): {"out", "bytes", "rows", "sections": {"comment", "tables"}: "ok"|"placeholder"}
"""
import html as _html
import io
import json
import os
import re
import sys
from calendar import monthrange
from datetime import date, timedelta

if __name__ == "__main__":
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(ASSETS_DIR, "..", "shared", "assets"),
             os.path.join(ASSETS_DIR, "..", "..", "..", "shared", "assets")):
    if os.path.exists(os.path.join(cand, "report_kit.py")):
        sys.path.insert(0, os.path.normpath(cand))
        break
else:
    raise SystemExit("report_kit.py를 찾을 수 없다 (shared/assets)")
import report_kit as kit  # noqa: E402

P = kit.PRODUCT_DIM
AD_TYPE = "ad_type"
# 표 디멘전(미디어 아래): 서버 차원 → 짧은 키 · 라벨 (목업 순서).
# 'p'(상품 / Ad Type) = 캠페인에 배정된 구분값 — 브랜드가 ad_type을 주면 그것, 없으면 상품(둘 다 있으면 ad_type).
DIMS = [("campaign_name", "c", "캠페인"), (AD_TYPE, "p", "Ad Type"), (P, "p", "상품"), ("ad_group_name", "t", "광고 그룹"),
        ("ad_name", "cr", "소재")]
SHORT = {src: k for src, k, _ in DIMS}
SHORT["media"] = "m"
# Placement 표의 노출 위치 차원 — ELT가 붙일 이름 후보(먼저 나온 것을 쓴다)
PLACE_DIMS = ("placement", "노출위치", "노출 위치", "노출_위치", "position")
for _src in PLACE_DIMS:
    SHORT[_src] = "pl"
ATOMS = (("cost", "cost"), ("impression", "imp"), ("click", "click"), ("views", "view"))
DROP_THRESHOLD = 20   # Daily Comment 급감 기준(%)
TOP_LINES = 5         # Comment 하위 불릿: 매체마다 이만큼만 적고 나머지는 "외 N개"로 묶는다(실데이터는 광고그룹·상품이 수백 개)
# 목표 표 행 이름 → 목표 키 (cost = 예산, 나머지 = 목표 영역 e.*)
TARGET_ROWS = {"cost": "cost", "budget": "cost", "impression": "imp", "impressions": "imp", "imps": "imp",
               "click": "click", "clicks": "click", "views": "view", "view": "view", "video_views": "view",
               "ctr": "ctr", "vtr": "vtr", "cpm": "cpm", "cpc": "cpc", "cpv": "cpv"}
SCOPE_COLS = {"media": "m", "매체": "m", P: "p", AD_TYPE: "p", "product": "p", "campaign_name": "c", "campaign": "c", "캠페인": "c",
              "ad_group_name": "t", "ad_group": "t", "광고그룹": "t", "광고 그룹": "t"}


# ── 포맷 (목업과 같은 규칙) ─────────────────────────────────────────────────


def n0(v):
    return f"{round(v):,}"


def sgn(v):
    return ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v):.1f}"


def pct(c, p):
    return (c - p) / p * 100 if p else 0.0


def krdate(d):
    return f"{d.month}월 {d.day}일"


def money(v, currency):
    return n0(v) + "원" if currency in ("₩", "원", "KRW") else kit.fmt_money(v, currency)


# ── 입력 해석 ────────────────────────────────────────────────────────────────


def _num(s):
    s = (s or "").strip().replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v else None


def _tables(text):
    """markdown 원문 → 표(연속한 '|' 줄 묶음) 리스트. 표 사이는 빈 줄 등 '|'가 아닌 줄로 나뉜다."""
    out, cur = [], []
    for ln in (text or "").splitlines():
        if ln.strip().startswith("|"):
            cur.append(ln.strip())
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def parse_budget(entry):
    """budgets 항목 1개(get_target_progress_v2 원문) → [{"mo", "scope": {짧은 키: 값}, "v": {목표 키: 값}, "inc"?}].
    표마다 metric·target 열을 읽는다(cost = Gross 예산, cost_net·revenue·roas·actual·achievement는 쓰지 않는다).
    - 첫째 표 `| metric | target | actual | progress_ratio |` = 호출 범위(media 인자, 생략 = 전체)의 합계.
    - 둘째 표 `| media | campaign_name | included | metric | … |` = 매체 행(campaign_name `-`)과 캠페인 행(dashboard 브랜드).
      범위 열 값이 `-`·all이면 그 차원은 범위에 넣지 않는다. 캠페인 행의 included(Y/N)는 "inc"로 남긴다.
    표가 아니면(한 줄 '목표 없음' 메시지·에러) 빈 리스트."""
    text = entry.get("target_progress") or ""
    m = re.search(r"^month:\s*(\d{4}-\d{2})", text, re.M)
    month = str(entry.get("month") or (m.group(1) if m else ""))[:7]
    base = {SHORT[k]: str(entry[k]) for k in ("media", AD_TYPE, P, "campaign_name", "ad_group_name") if entry.get(k)}
    out = {}
    for lines in _tables(text):
        head = [c.strip().lower() for c in lines[0].strip("|").split("|")]
        if "metric" not in head or "target" not in head:
            continue
        mi, ti = head.index("metric"), head.index("target")
        ii = head.index("included") if "included" in head else None
        scols = {i: SCOPE_COLS[h] for i, h in enumerate(head) if h in SCOPE_COLS}
        for ln in lines[1:]:
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) != len(head) or set(cells[mi]) <= set("-: "):
                continue
            key = TARGET_ROWS.get(cells[mi].lower())
            v = _num(cells[ti])
            if not key or v is None:
                continue
            scope = dict(base)
            for i, k in scols.items():
                if cells[i] and cells[i].lower() not in ("all", "-", "전체"):
                    scope[k] = cells[i]
            sk = json.dumps(sorted(scope.items()), ensure_ascii=False)
            e = out.setdefault(sk, {"mo": month, "scope": scope, "v": {}})
            e["v"][key] = v
            if ii is not None and cells[ii] in ("Y", "N"):
                e["inc"] = cells[ii]
    for e in out.values():
        derive_targets(e["v"])
    return list(out.values())


def derive_targets(v):
    """비어 있는 목표를 있는 목표로 계산해 채운다(서버 값이 있으면 그대로). 같은 범위 안에서만 계산한다.
    노출 = 예산/CPM×1000 (또는 클릭/CTR), 클릭 = 예산/CPC (또는 노출×CTR), 조회 = 노출×VTR (또는 예산/CPV),
    CTR = 클릭/노출, CPM = 예산/노출×1000, CPC = 예산/클릭, VTR = 조회/노출, CPV = 예산/조회."""
    g = v.get
    if g("imp") is None:
        if g("cost") and g("cpm"):
            v["imp"] = g("cost") / g("cpm") * 1000
        elif g("click") and g("ctr"):
            v["imp"] = g("click") / (g("ctr") / 100)
    if g("click") is None:
        if g("cost") and g("cpc"):
            v["click"] = g("cost") / g("cpc")
        elif g("imp") and g("ctr"):
            v["click"] = g("imp") * g("ctr") / 100
    if g("view") is None:
        if g("imp") and g("vtr"):
            v["view"] = g("imp") * g("vtr") / 100
        elif g("cost") and g("cpv"):
            v["view"] = g("cost") / g("cpv")
    for k, num, den, mul in (("ctr", "click", "imp", 100), ("cpm", "cost", "imp", 1000), ("cpc", "cost", "click", 1),
                             ("vtr", "view", "imp", 100), ("cpv", "cost", "view", 1)):
        if g(k) is None and g(num) and g(den):
            v[k] = g(num) / g(den) * mul
    return v


def load_rows(env, keys, dims, start, end):
    """표 데이터 봉투 → 원자 행 [{"day": date, "m", <짧은 키>..., "cost", "imp", "click", "view"}] (집계 기간 밖 행은 버린다)."""
    rows = []
    for r in env.get("rows") or []:
        p = kit.period_of(r)
        try:
            d = date.fromisoformat(p[:10])
        except ValueError:
            raise SystemExit("data: day grain 응답이 아니다(행에 date가 없다) — time_grain \"day\"로 다시 받는다.")
        if not start <= d <= end:
            continue
        row = {"day": d, "m": kit._label(r.get("media"))}
        for src in dims:
            row[SHORT[src]] = kit._label(r.get(src))
        for role, k in ATOMS:
            v = r.get(keys.get(role)) if keys.get(role) else None
            row[k] = v if isinstance(v, (int, float)) else 0
        if not (row["cost"] or row["imp"] or row["click"] or row["view"]):
            continue   # 실적이 전부 0인 행(집행 없는 광고그룹의 날) — 합계에 영향 없고 표만 길게 만든다
        rows.append(row)
    return rows


# ── 묶기 ─────────────────────────────────────────────────────────────────────


def agg(rows):
    a = {"cost": 0, "imp": 0, "click": 0, "view": 0}
    for r in rows:
        for k in a:
            a[k] += r[k]
    return a


def kpi(a):
    imp, view = a["imp"], a["view"]
    return dict(a, cpm=a["cost"] / imp * 1000 if imp else 0, cpv=a["cost"] / view if view else 0,
                vtr=view / imp * 100 if imp else 0, ctr=a["click"] / imp * 100 if imp else 0)


def uniq(seq):
    return list(dict.fromkeys(seq))   # 나타난 순서 유지(행 수만 개에서도 빠르게)


def live(rows):
    return any(r["cost"] or r["imp"] for r in rows)


# ── 예산 (Python: Weekly Comment의 당월 소진율용 — 전체 범위만) ────────────────


def month_budget(budgets, mo, rows):
    """그 달 전체 예산: 전체 범위 항목, 없으면 더 잘게 받은 범위(매체 → … → 광고그룹 순) 중 그 달 집행 단위를 모두 덮는 것의 합."""
    es = [b for b in budgets if b["mo"] == mo and b["v"].get("cost")]
    exact = [b for b in es if not b["scope"]]
    if exact:
        return exact[0]["v"]["cost"]
    for ks in sorted({tuple(sorted(b["scope"])) for b in es}, key=len):
        level = [b for b in es if tuple(sorted(b["scope"])) == ks]
        have = {tuple(b["scope"][k] for k in ks) for b in level}
        need = {tuple(r.get(k) for k in ks) for r in rows if live([r])}
        if need and need <= have:
            return sum(b["v"]["cost"] for b in level)
    return None


# ── Daily Comment (목업 buildDaily) ─────────────────────────────────────────


def line_dims(dims):
    """급감 판정 단위 = 매체 × (상품/Ad Type, 광고그룹 중 있는 것) — 없으면 캠페인."""
    ld = [SHORT[d] for d in (AD_TYPE, P, "ad_group_name") if d in dims]
    return ld or ([SHORT["campaign_name"]] if "campaign_name" in dims else [])


def unit_word(ld):
    return "광고그룹" if "t" in ld else "상품" if "p" in ld else "캠페인" if "c" in ld else "매체"


def line_label(key, ld, lines_in_media):
    """상품(광고그룹) — 같은 매체 안에서 상품이 여러 광고그룹으로 나뉠 때만 괄호를 붙인다(목업 lineName)."""
    if not ld:
        return key[0]
    head = key[1]
    if len(ld) > 1 and sum(1 for k in lines_in_media if k[1] == head) > 1:
        return f"{head}({key[2]})"
    return head


def last_spend(rows, m):
    ds = [r["day"] for r in rows if r["m"] == m and live([r])]
    return max(ds) if ds else None


def build_daily(rows, E, media, ld, threshold, currency):
    prev = E - timedelta(days=1)
    cur = [r for r in rows if r["day"] == E]
    pre = [r for r in rows if r["day"] == prev]
    a, b = agg(cur), agg(pre)
    summary = (f"{krdate(E)} 기준 광고비 {money(a['cost'], currency)}({sgn(pct(a['cost'], b['cost']))}%), "
               f"노출 {n0(a['imp'])}({sgn(pct(a['imp'], b['imp']))}%), 클릭 {n0(a['click'])}({sgn(pct(a['click'], b['click']))}%)"
               f"로 전일({krdate(prev)}) 대비 집계되었습니다.")
    lkey = lambda r: (r["m"],) + tuple(r[k] for k in ld)  # noqa: E731
    keys = uniq(lkey(r) for r in sorted(rows, key=lambda r: r["day"]))
    by_cur, by_pre, by_media = {}, {}, {}
    for r in cur:
        by_cur.setdefault(lkey(r), []).append(r)
    for r in pre:
        by_pre.setdefault(lkey(r), []).append(r)
    for k in keys:
        by_media.setdefault(k[0], []).append(k)
    flagged = []
    for k in keys:
        c = agg(by_cur.get(k, []))
        p = agg(by_pre.get(k, []))
        if not p["cost"]:
            continue
        lab = line_label(k, ld, by_media[k[0]])
        if not c["cost"]:
            flagged.append({"m": k[0], "k": lab, "loss": p["cost"], "v": "전일 대비 광고비가 집행되지 않았습니다. 캠페인 상태 확인이 필요합니다."})
            continue
        drops = [(lb, pct(c[x], p[x]), p[x], c[x]) for lb, x in (("광고비", "cost"), ("노출", "imp"), ("클릭", "click"))]
        drops = [x for x in drops if x[1] <= -threshold]
        if drops:
            flagged.append({"m": k[0], "k": lab, "loss": p["cost"] - c["cost"], "v": ", ".join(f"{lb} {n0(f)} → {n0(t)}({sgn(d)}%)" for lb, d, f, t in drops)
                            + " 감소하였습니다. 입찰 및 소재 노출 상태 점검이 필요합니다."})
    active = sum(1 for k in keys if live(by_cur.get(k, [])))
    word = unit_word(ld)
    items = []
    for m in media:
        fm = sorted((f for f in flagged if f["m"] == m), key=lambda f: -f["loss"])   # 광고비가 많이 줄어든 순
        subs = [{"k": f["k"], "v": f["v"]} for f in fm[:TOP_LINES]]
        if len(fm) > TOP_LINES:
            rest = fm[TOP_LINES:]
            subs.append({"k": f"외 {len(rest)}개 {unit_word(ld)}",
                         "v": "광고비 감소 폭이 작은 순이라 생략했습니다(표에서 확인)."})
        mc, mp = [r for r in cur if r["m"] == m], [r for r in pre if r["m"] == m]
        if subs:
            v = f"전일 대비 급감한 {word}이 {len(fm)}개 확인되었습니다." if word != "매체" else "전일 대비 급감이 확인되었습니다."
        elif not live(mc):
            ls = last_spend(rows, m)
            v = ("특이사항 없음 (전일 대비 집행 중단)" if live(mp) else
                 f"특이사항 없음 ({krdate(ls)} 집행 종료)" if ls else "특이사항 없음 (집행 없음)")
        else:
            x, y = agg(mc), agg(mp)
            v = (f"특이사항 없음 (광고비 {sgn(pct(x['cost'], y['cost']))}%, 노출 {sgn(pct(x['imp'], y['imp']))}%, "
                 f"클릭 {sgn(pct(x['click'], y['click']))}%)")
        items.append({"k": m, "v": v, "subs": subs})
    closing = ("급감 " + word + " 외에는 전일과 유사한 수준으로 정상 운영 중입니다." if flagged else
               f"전 매체 모두 전일 대비 광고비·노출·클릭이 {threshold}% 이상 급감한 {word}은 없으며, 운영상 특이 이슈는 확인되지 않습니다.")
    return {"meta": f"{krdate(E)} vs {krdate(prev)} · 집행 중 {word} {active}개 · 급감 기준 −{threshold}%",
            "summary": summary, "items": items, "closing": closing}


# ── Weekly Comment (목업 buildWeekly) ───────────────────────────────────────


def _desc(c, p):
    """상품 한 줄: 변화가 큰 단가·효율 지표 최대 2개(목업 desc)."""
    d_cpm, d_cpv, d_vtr, d_ctr = pct(c["cpm"], p["cpm"]), pct(c["cpv"], p["cpv"]), c["vtr"] - p["vtr"], pct(c["ctr"], p["ctr"])
    cpvf = (lambda x: f"{x:.1f}") if c["cpv"] < 20 else n0
    cand = [
        (abs(d_cpm), bool(c["imp"] and p["imp"]) and abs(d_cpm) >= 5, f"CPM {n0(p['cpm'])}원 → {n0(c['cpm'])}원({sgn(d_cpm)}%)으로 노출 단가가 "
         + ("개선되었" if d_cpm < 0 else "상승하였")),
        (abs(d_cpv), bool(c["cpv"] and p["cpv"]) and abs(d_cpv) >= 5,
         f"CPV {cpvf(p['cpv'])}원 → {cpvf(c['cpv'])}원({sgn(d_cpv)}%)으로 조회 단가가 " + ("개선되었" if d_cpv < 0 else "상승하였")),
        (abs(d_vtr) * 2, bool(c["imp"] and p["imp"] and (c["view"] or p["view"])) and abs(d_vtr) >= 3, f"VTR {round(c['vtr'])}%로 {sgn(d_vtr)}%p " + ("개선되었" if d_vtr > 0 else "하락하였")),
        (abs(d_ctr) * 0.5, bool(c["imp"] and p["imp"] and p["click"]) and abs(d_ctr) >= 15, f"CTR {c['ctr']:.2f}%로 {sgn(d_ctr)}% " + ("상승하였" if d_ctr > 0 else "하락하였")),
    ]
    cand = sorted([x for x in cand if x[1]], key=lambda x: -x[0])[:2]
    if not cand:
        return "직전 주와 유사한 효율로 안정적으로 운영 중입니다."
    return "".join(t + ("으며, " if i < len(cand) - 1 else "습니다.") for i, (_, _, t) in enumerate(cand))


def build_weekly(rows, E, media, ld, budgets, months, currency, has_view=True):
    ws = E - timedelta(days=E.weekday())            # ISO 주(월~일)의 월요일
    pws, pwe = ws - timedelta(days=7), ws - timedelta(days=1)
    W, Pw = E.isocalendar()[1], pws.isocalendar()[1]
    cw = [r for r in rows if ws <= r["day"] <= E]
    pw = [r for r in rows if pws <= r["day"] <= pwe]
    lkey = lambda r: (r["m"],) + tuple(r[k] for k in ld)  # noqa: E731

    def days(rs):
        return len({r["day"] for r in rs}) or 1

    def rng(rs):
        ds = sorted({r["day"] for r in rs})
        return f"{ds[0].month}.{ds[0].day}–{ds[-1].month}.{ds[-1].day}" if ds else "-"

    active = {lkey(r) for r in cw if live([r])}
    c_avg = agg(cw)["cost"] / days(cw)
    pw_act = [r for r in pw if lkey(r) in active]
    p_avg = agg(pw_act)["cost"] / days(pw_act)
    dc = pct(c_avg, p_avg)
    sections = []
    if abs(dc) < 5:
        spend = f"일평균 광고비 {money(c_avg, currency)}으로 직전 주({money(p_avg, currency)})와 유사하게 안정적으로 소진 진행 중입니다."
    else:
        spend = f"일평균 광고비 {money(c_avg, currency)}으로 직전 주 대비 {sgn(dc)}% {'증가' if dc > 0 else '감소'}하였습니다."
    m0 = months[-1]
    m0_rows = [r for r in rows if f"{r['day']:%Y-%m}" == m0["key"]]
    bud = month_budget(budgets, m0["key"], m0_rows)
    if bud:
        burn, prog = agg(m0_rows)["cost"] / bud * 100, m0["elapsed"] / m0["days"] * 100
        spend += (f" {int(m0['key'][5:])}월 예산 대비 소진율 {burn:.1f}%로 진행율({prog:.1f}%)에 "
                  + ("맞춰 운영 중입니다." if abs(burn - prog) < 3 else
                     "앞서 있어 일 예산 조정 검토가 필요합니다." if burn > prog else "미달하여 소진 속도 점검이 필요합니다."))
    ended = [m for m in media if live([r for r in pw if r["m"] == m]) and not live([r for r in cw if r["m"] == m])]
    if ended:
        by_day = {}
        for m in ended:
            by_day.setdefault(last_spend(rows, m), []).append(m)
        spend += " " + ", ".join(f"{', '.join(ms)}는 {krdate(d)}" for d, ms in by_day.items()) + " 집행 종료되었습니다."
    sections.append({"h": "[소진]", "text": spend, "groups": []})

    pk = ld[0] if ld else None
    groups = []
    for m in media:
        mc, mp = [r for r in cw if r["m"] == m], [r for r in pw if r["m"] == m]
        if not live(mc):
            ls = last_spend(rows, m)
            why = f"{krdate(ls)} 집행 종료로 {W}주차 집행 없음" if ls else "집행 없음"
            groups.append({"media": m, "summary": f"특이사항 없음 ({why})", "bullets": []})
            continue
        c, p = kpi(agg(mc)), kpi(agg(mp))
        d_cpm = pct(c["cpm"], p["cpm"])
        view_part = (f", CPV {n0(c['cpv'])}원({sgn(pct(c['cpv'], p['cpv']))}%), VTR {round(c['vtr'])}%({sgn(c['vtr'] - p['vtr'])}%p)"
                     if has_view else f", CTR {c['ctr']:.2f}%({sgn(c['ctr'] - p['ctr'])}%p)")   # 조회 지표가 없는 브랜드는 CTR
        summary = (f"직전 주 대비 CPM {n0(c['cpm'])}원({sgn(d_cpm)}%){view_part}로 "
                   + ("전반적으로 개선된 효율로 운영 중입니다." if d_cpm <= 0 and c["vtr"] >= p["vtr"] else
                      "노출 단가가 다소 상승하였습니다." if d_cpm > 5 else "전반적으로 유사한 효율로 운영 중입니다."))
        bullets = []
        if pk:
            by_c, by_p = {}, {}
            for r in mc:
                by_c.setdefault(r[pk], []).append(r)
            for r in mp:
                by_p.setdefault(r[pk], []).append(r)
            names = [n for n in sorted(by_c, key=lambda n: -agg(by_c[n])["cost"]) if live(by_c[n])]
            for name in names[:TOP_LINES]:
                rc = by_c[name]
                if not live(rc):
                    continue
                bullets.append({"k": name, "v": _desc(kpi(agg(rc)), kpi(agg(by_p.get(name, []))))})
            if len(names) > TOP_LINES:
                bullets.append({"k": f"외 {len(names) - TOP_LINES}개", "v": "광고비 상위 " + str(TOP_LINES) + "개만 적었습니다."})
        groups.append({"media": m, "summary": summary, "bullets": bullets})
    tc, tp = kpi(agg(cw)), kpi(agg(pw_act))
    o_cpm, o_cpv = pct(tc["cpm"], tp["cpm"]), pct(tc["cpv"], tp["cpv"])
    overall = ("전체 캠페인 모두 직전 주 대비 개선된 효율로 운영 중입니다." if o_cpm <= 0 and o_cpv <= 0 else
               "전체 캠페인 모두 직전 주와 유사한 효율로 안정적으로 운영 중이며, 일부 상품에서 단가 변동이 확인됩니다."
               if abs(o_cpm) < 5 and abs(o_cpv) < 5 else "일부 상품에서 단가 변동이 있어 상품별 효율 점검이 필요합니다.")
    sections.append({"h": "[효율]", "text": overall, "groups": groups})
    return {"meta": f"{W}주차({rng(cw)}, {days(cw)}일) vs {Pw}주차({rng(pw)}, {days(pw)}일) · 일평균/단가 기준",
            "sections": sections}


# ── 조립 ─────────────────────────────────────────────────────────────────────


def encode(rows, dims, start, end):
    """원자 행 → 열 기반 표 데이터(값 사전 + 코드). 날짜는 days 인덱스."""
    ndays = (end - start).days + 1
    day_list = [start + timedelta(days=i) for i in range(ndays)]
    wk = sorted({d.isocalendar()[:2] for d in day_list})   # 주 정렬 키(연도 경계에서도 순서 유지)
    days = [{"label": f"{d.year}.{d.month}.{d.day}", "mo": f"{d:%Y-%m}", "w": d.isocalendar()[1],
             "ws": wk.index(d.isocalendar()[:2])} for d in day_list]
    keys = ["m"] + [SHORT[d] for d in dims]
    # 값 사전은 집계 기간 광고비 큰 순(표·필터의 기본 순서)
    dic = {}
    for k in keys:
        tot = {}
        for r in rows:
            tot[r[k]] = tot.get(r[k], 0) + r["cost"]
        dic[k] = sorted(tot, key=lambda v: (-tot[v], v))
    pos = {k: {v: i for i, v in enumerate(dic[k])} for k in keys}
    cols = {k: [pos[k][r[k]] for r in rows] for k in keys}
    cols["d"] = [(r["day"] - start).days for r in rows]
    for _, k in ATOMS:
        cols[k] = [r[k] if not float(r[k]).is_integer() else int(r[k]) for r in rows]
    return {"days": days, "dict": dic, "cols": cols, "n": len(rows)}


def compute(payload):
    target = date.fromisoformat(payload["target_date"])
    E = target - timedelta(days=1)
    if payload.get("start_date"):   # 사용자가 정한 시작일
        start = date.fromisoformat(payload["start_date"])
        if start > E:
            raise SystemExit(f"start_date({start})가 데이터 마지막 날(기준일 전날 {E})보다 늦다.")
        if (E - start).days > 365:
            raise SystemExit("집계 기간은 366일까지다(get_ad_performance 상한) — start_date를 줄인다.")
    else:                           # 기본: E의 전월 1일
        start = date(E.year, E.month, 1) - timedelta(days=1)
        start = date(start.year, start.month, 1)
    months = []
    d = date(start.year, start.month, 1)
    multi_year = start.year != E.year
    while d <= E:
        n = monthrange(d.year, d.month)[1]
        months.append({"key": f"{d:%Y-%m}", "label": (f"{d.year % 100}년 " if multi_year else "") + f"{d.month}월", "days": n,
                       "elapsed": E.day if (d.year, d.month) == (E.year, E.month) else n})
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    keys = payload.get("metric_keys") or {}
    currency = payload.get("currency") or "₩"
    skeleton = bool(payload.get("skeleton"))
    env = None if skeleton else kit.section_envelope(payload.get("data"))
    header = {"period": f"{start:%Y.%m.%d} – {E:%Y.%m.%d}", "media": ""}
    report = {"brand": payload["brand"], "currency": currency, "months": months, "header": header,
              "comment": None, "table": None}
    if not env or not keys.get("cost"):
        return report, []
    # 노출 위치 차원은 Placement 데이터(place)로 따로 받는다 — 표 데이터에는 요구하지 않는다
    need = [d for d in kit.fine_dims(kit.probe_dims(payload.get("dims")) or [])
            if d not in kit.SIZE_FALLBACK_DIMS and d not in PLACE_DIMS]
    valid = kit.require_dims(payload.get("dims"), [("data", env)], "data 표 데이터", need=need)
    dims = [d for d, _, _ in DIMS if d in (env.get("dimensions") or []) and d in valid]
    if AD_TYPE in dims and P in dims:
        dims.remove(P)   # 같은 'p' 자리 — ad_type이 우선
    rows = load_rows(env, keys, dims, start, E)
    if not rows:
        return report, []
    menv = kit.section_envelope(payload.get("media"))
    if menv:
        kit.require_rollup([("매체 ↔ 표 데이터(일)", kit.check_rollup(menv, ["media"], env, ["media"], keys))])
    tot = {}
    for r in rows:
        tot[r["m"]] = tot.get(r["m"], 0) + r["cost"]
    media = sorted(tot, key=lambda m: (-tot[m], m))
    header["media"] = " · ".join(media)
    budgets = [b for e in (payload.get("budgets") or []) for b in parse_budget(e)]
    # 목표 표의 매체·캠페인 표기를 데이터 표기에 맞춘다 — BE와 같은 기준(앞뒤 공백·대소문자 무시).
    # 맞는 표기가 없으면 그대로 둔다(그 달 실적이 없는 매체·캠페인 → 어느 행에도 붙지 않는다).
    canon = {k: {str(v).strip().lower(): v for v in {r[k] for r in rows if k in r}} for k in ("m", "c")}
    for b in budgets:
        for k in ("m", "c"):
            if k in b["scope"]:
                b["scope"][k] = canon[k].get(str(b["scope"][k]).strip().lower(), b["scope"][k])
    ld = line_dims(dims)
    report["comment"] = {"daily": build_daily(rows, E, media, ld, DROP_THRESHOLD, currency),
                         "weekly": build_weekly(rows, E, media, ld, budgets, months, currency, has_view=bool(keys.get("views")))}
    has = {"imp": bool(keys.get("impression")), "click": bool(keys.get("click")), "view": bool(keys.get("views"))}
    report["table"] = dict(encode(rows, dims, start, E), dims=[{"key": k, "label": lb} for src, k, lb in DIMS if src in dims],
                           has=has, budgets=budgets)
    report["place"] = build_place(payload.get("place"), menv, keys, start, E)
    return report, rows


def build_place(spec, menv, keys, start, E):
    """Placement 표 데이터: 미디어 × (Ad Type/상품) × 노출 위치 × 일. 노출 위치 차원이 없으면 None(표가 조용히 빠진다)."""
    penv = kit.section_envelope(spec) if spec else None
    if not penv:
        return None
    pdims_have = penv.get("dimensions") or []
    pl = next((d for d in PLACE_DIMS if d in pdims_have), None)
    if not pl:
        return None
    pd = [d for d in (AD_TYPE, P) if d in pdims_have][:1] + [pl]
    if menv:   # 매체별 일 합 = Placement 데이터 합(표 데이터와 같은 대조)
        kit.require_rollup([("매체 ↔ Placement 데이터(일)", kit.check_rollup(menv, ["media"], penv, ["media"], keys))])
    prow = load_rows(penv, keys, pd, start, E)
    if not prow:
        return None
    labels = {pl: "노출 위치", AD_TYPE: "Ad Type", P: "상품"}
    return dict(encode(prow, pd, start, E), dims=[{"key": SHORT[d], "label": labels[d]} for d in pd])


def build_html(report, out):
    with open(os.path.join(ASSETS_DIR, "report-template.html"), encoding="utf-8") as f:
        template = f.read()
    js = kit._read_first(ASSETS_DIR, ["tbwa_report.txt", "tbwa_report.js"])
    css = kit._read_first(kit.KIT_DIR, ["report_kit.css"])
    values = {"__TITLE__": _html.escape(report["brand"]), "__REPORT_KIT_CSS__": css, "__TBWA_JS__": js,
              "__REPORT_JSON__": kit.js_json(report)}
    left = set(re.findall(r"__[A-Z0-9]+(?:_[A-Z0-9]+)*__", template)) - set(values)
    if left:
        raise SystemExit(f"치환되지 않은 placeholder: {sorted(left)}")
    html = re.sub(r"__[A-Z0-9]+(?:_[A-Z0-9]+)*__", lambda m: values.get(m.group(0), m.group(0)), template)
    path = os.path.abspath(os.path.expanduser(out))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path, os.path.getsize(path)


def main():
    payload = kit.read_payload()
    report, rows = compute(payload)
    path, size = build_html(report, payload["out"])
    json.dump({"out": path, "bytes": size, "rows": len(rows),
               "sections": {"comment": "ok" if report["comment"] else "placeholder",
                            "tables": "ok" if report["table"] else "placeholder"}},
              sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()

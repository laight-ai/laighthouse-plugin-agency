"""미디어믹스 예산안 백테스트 타당성 점검 — prepare.py·build_report.py가 쓰는 본체.

과거 대상 달마다 backtest 예산안(get_media_mix_job의 `optimized`)을 기준 달 실적(`current`)과 견주어, 그 시점까지의
데이터에 비춰 말이 되는지 세 기준으로 판정한다. 대상 달의 실제 성과와는 맞춰 보지 않는다(성과 검증이 아니다).

- ① 추세: 기준 달까지 최근 3개월 효율(성과 ÷ 비용) 추세와 제안 증감 방향이 어긋나면 "설명 필요"
- ② 변동 폭: 제안 증감률이 그 매체의 최근 12개월 월간 증감률 범위를 벗어나면 "범위 밖"(±30%는 참고선)
- ③ 작년 흐름: 작년 (대상 달-13 → 대상 달-12) 증감과 방향이 반대면 "작년과 반대"

월 실적은 get_ad_performance(time_grain month, group_by media, metrics 생략) 응답을 Net 비용으로 바꿔 쓴다.
"""
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.join(HERE, "..", "shared", "assets"),           # 스킬 폴더 안 사본(Cowork·ChatGPT)
              os.path.join(HERE, "..", "..", "..", "shared", "assets")):   # 플러그인 루트 · 공통 레포
    if os.path.exists(os.path.join(_cand, "saved_responses.py")):
        sys.path.insert(0, os.path.normpath(_cand))
        break
else:
    raise SystemExit("saved_responses.py를 찾을 수 없다 (shared/assets)")
import saved_responses as sr  # noqa: E402

DEAD = 0.05          # 이보다 작은 증감은 방향이 없는 것으로 본다
TREND = 0.10         # 3개월 효율 변화가 이 이상이면 개선 · 이 이하(음수)면 악화
REF_LINE = 0.30      # 관리자 참고선(±30%)
MIN_HISTORY = 6      # ② 과거 월간 증감률이 이보다 적으면 판단 불가
FLOOR = 1_000_000    # 이 금액(Net, 원) 미만의 달 비용은 비율이 튀므로 판정에 쓰지 않는다
MAX_SPAN_DAYS = 730  # get_ad_performance month grain 상한
SUGGEST = 6
KST = timezone(timedelta(hours=9))


# ── 달 계산 ──────────────────────────────────────────────────────────────
def parse_month(text):
    if not re.fullmatch(r"\d{4}-\d{2}", text or "") or not 1 <= int(text[5:]) <= 12:
        raise ValueError(f"달은 YYYY-MM 이어야 한다: {text}")
    return text


def shift(month, n):
    y, m = int(month[:4]), int(month[5:]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def first_day(month):
    return date(int(month[:4]), int(month[5:]), 1)


def last_day(month):
    return first_day(shift(month, 1)) - timedelta(days=1)


def last_closed_month(today):
    return shift(f"{today.year:04d}-{today.month:02d}", -1)


def kst_today():
    return datetime.now(KST).date()


def label(month):
    return f"{int(month[:4])}년 {int(month[5:])}월"


# ── 응답 읽기 ────────────────────────────────────────────────────────────
def window(months, today):
    """조회할 범위: 가장 이른 대상 달의 13개월 전 1일 ~ 가장 늦은 대상 달 말일."""
    start, end = first_day(shift(min(months), -13)), last_day(max(months))
    if (end - start).days + 1 > MAX_SPAN_DAYS:
        raise ValueError("대상 달 사이가 너무 멀다 — 가장 이른 달과 가장 늦은 달이 9개월 안에 들어야 한다"
                         " (13개월 전 실적까지 한 번에 조회한다)")
    return start, end


def default_window(today):
    """대상 달을 정하기 전 첫 조회: 끝난 마지막 달까지 23개월(대상 달 후보는 그중 최근 10개월)."""
    end_month = last_closed_month(today)
    return first_day(shift(end_month, -22)), last_day(end_month)


def call_args(brand, start, end):
    return {"tool": "get_ad_performance", "brand_name": brand, "start_date": start.isoformat(),
            "end_date": end.isoformat(), "time_grain": "month", "group_by": ["media"]}


def ad_performance(recs):
    """가장 최근의 월 · 매체별 조회 응답 (기록, 봉투). 없으면 (None, None)."""
    rec = sr.pick(recs, "get_ad_performance", time_grain="month", group_by=["media"])
    if rec is None:
        return None, None
    try:
        env = json.loads(sr.response_text(rec))
    except ValueError:
        env = None
    return rec, env


def covers(rec, start, end):
    ti = rec.get("tool_input") or {}
    return str(ti.get("start_date"))[:10] <= start.isoformat() and str(ti.get("end_date"))[:10] >= end.isoformat()


def monthly(env, cost_metric, outcome_metric):
    """{매체: {달: [Net 비용, 성과]}}. 비용은 응답 기준(fee_basis)이 gross면 매체 · 달 수수료로 Net으로 바꾼다."""
    for name in (cost_metric, outcome_metric):
        if name not in (env.get("metrics") or []):
            raise ValueError(f"광고 성과 응답에 지표 '{name}'이 없다 — 있는 지표: {', '.join(env.get('metrics') or [])}")
    fees = {(f["media"], f["month"]): f for f in env.get("fees") or []} if env.get("fee_basis") == "gross" else {}
    out = {}
    for row in env.get("rows") or []:
        media, month = row.get("media"), str(row.get("month") or "")[:7]
        if media is None or not month:
            continue
        cost = float(row.get(cost_metric) or 0)
        fee = fees.get((media, month))
        if fee:
            r = float(fee["rate"]) / 100
            cost = cost / (1 + r) if fee["fee_mode"] == "markup" else cost * (1 - r)
        cell = out.setdefault(str(media), {}).setdefault(month, [0.0, 0.0])
        cell[0] += cost
        cell[1] += float(row.get(outcome_metric) or 0)
    return out


def month_total(data, month):
    return sum(by_month.get(month, [0, 0])[0] for by_month in data.values())


def won(v):
    return int(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def jobs(recs, cost_metric, outcome_metric):
    """대상 달마다 가장 최근의 끝난 backtest 결과 {달: 응답}. 계산 중인 것은 뺀다."""
    out = {}
    for rec in recs:
        if rec["_tool"] != "get_media_mix_job":
            continue
        try:
            job = json.loads(sr.response_text(rec))
        except ValueError:
            continue
        req = job.get("request") if isinstance(job, dict) else None
        if not isinstance(req, dict) or not req.get("backtest"):
            continue
        if req.get("cost_metric") != cost_metric or req.get("outcome_metric") != outcome_metric:
            continue
        if job.get("status") in ("succeeded", "failed", "canceled"):
            out[req.get("target_month")] = job
    return out


# ── 판정 ────────────────────────────────────────────────────────────────
def pct(new, old):
    return None if not old else new / old - 1


def direction(change):
    if change is None:
        return 0
    return 1 if change >= DEAD else -1 if change <= -DEAD else 0


def summary_rows(job):
    rows = {}
    for r in job.get("summary") or []:
        rows.setdefault(r.get("media"), {})[r.get("kind")] = r
    return rows


def judge_month(target, job, data):
    base = shift(target, -1)
    rows = summary_rows(job)
    media = sorted((m for m in rows if m != "*"),
                   key=lambda m: (-float((rows[m].get("optimized") or {}).get("cost") or 0), m))
    out = []
    for m in media:
        cur, opt = rows[m].get("current") or {}, rows[m].get("optimized") or {}
        c0, c1 = float(cur.get("cost") or 0), float(opt.get("cost") or 0)
        hist = data.get(m, {})
        cost = {k: v[0] for k, v in hist.items()}
        change = pct(c1, c0)
        item = {"media": m, "base_cost": c0, "proposed_cost": c1, "change": change,
                "base_opc": cur.get("outcome_per_cost"), "proposed_opc": opt.get("outcome_per_cost")}
        if c0 < FLOOR and c1 < FLOOR:
            item.update(small=True, trend={"verdict": "small"}, swing={"verdict": "small"}, season={"verdict": "small"})
        else:
            item.update(small=False, trend=_trend(base, hist, change, item), swing=_swing(base, cost, c0, change),
                        season=_season(target, cost, change))
        out.append(item)
    total = rows.get("*", {})
    return {"target_month": target, "base_month": base, "budget": (job.get("request") or {}).get("target_budget"),
            "base_total": float((total.get("current") or {}).get("cost") or 0),
            "proposed_total": float((total.get("optimized") or {}).get("cost") or 0), "media": out}


def _trend(base, hist, change, item):
    months = [shift(base, -2), base]
    eff = []
    for k in months:
        c, o = hist.get(k, [0, 0])
        if c < FLOOR:
            return {"verdict": "unknown", "reason": f"{label(k)} 비용이 판정 하한 미만이거나 없음"}
        eff.append(o / c)
    t = pct(eff[1], eff[0])
    trend = "up" if t >= TREND else "down" if t <= -TREND else "flat"
    d = direction(change)
    res = {"efficiency_change": t, "trend": trend, "from": months[0], "to": months[1]}
    if (trend == "up" and d < 0) or (trend == "down" and d > 0):
        b, p = item["base_opc"], item["proposed_opc"]
        if d < 0 and b and p and p > b:
            why = "cut_raises_average"
        elif d > 0 and b and p and p < b:
            why = "raise_lowers_average"
        else:
            why = "none"
        res.update(verdict="explain", why=why)
    else:
        res["verdict"] = "ok"
    return res


def _swing(base, cost, c0, change):
    if c0 < FLOOR:
        return {"verdict": "new" if c0 == 0 else "small"}
    changes = []
    for i in range(12):
        k = shift(base, -i)
        prev = cost.get(shift(k, -1), 0)
        if prev >= FLOOR:
            changes.append(cost.get(k, 0) / prev - 1)
    if len(changes) < MIN_HISTORY:
        return {"verdict": "unknown", "reason": f"비교할 과거 달이 {len(changes)}개뿐"}
    lo, hi = min(changes), max(changes)
    return {"verdict": "out" if change < lo or change > hi else "ok", "range": [lo, hi],
            "months": len(changes), "over_ref": abs(change) > REF_LINE}


def _season(target, cost, change):
    a, b = shift(target, -13), shift(target, -12)
    if cost.get(a, 0) < FLOOR or cost.get(b, 0) < FLOOR:
        return {"verdict": "unknown", "reason": "작년 같은 시기 비용이 없거나 판정 하한 미만"}
    ly = cost[b] / cost[a] - 1
    opposite = direction(ly) * direction(change) < 0
    return {"verdict": "opposite" if opposite else "ok", "last_year": ly, "from": a, "to": b}


# ── 서식 · HTML ─────────────────────────────────────────────────────────
def fmt_won(v):
    return "₩" + f"{won(v):,}"


def fmt_pct(v, sign=True):
    if v is None:
        return "–"
    d = Decimal(str(v * 100)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{'+' if sign and d > 0 else ''}{d}%"


def fmt_eff(v):
    return "–" if v is None else f"{Decimal(str(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


TREND_WORD = {"up": "개선", "down": "악화", "flat": "보합"}
WHY = {
    "cut_raises_average": "예산을 줄이면 평균 효율이 {b}에서 {p}까지 오른다고 본 배분입니다(모델은 한계 효율로 나눕니다).",
    "raise_lowers_average": "늘리면 평균 효율이 {b}에서 {p}까지 내려가도 성과 합계가 커진다고 본 배분입니다.",
    "none": "모델의 평균 효율 변화({b}에서 {p})로도 설명되지 않습니다.",
}


def cell_trend(item):
    t = item["trend"]
    v = t["verdict"]
    if v == "small":
        return "소액 제외", ""
    if v == "unknown":
        return "판단 불가", t["reason"]
    head = f"{TREND_WORD[t['trend']]} {fmt_pct(t['efficiency_change'])}"
    if v == "ok":
        return "통과", head
    why = WHY[t["why"]].format(b=fmt_eff(item["base_opc"]), p=fmt_eff(item["proposed_opc"]))
    return "설명 필요", f"{head} · {why}"


def cell_swing(item):
    s = item["swing"]
    v = s["verdict"]
    if v == "small":
        return "소액 제외", ""
    if v == "new":
        return "새로 배분", "기준 달 비용이 없던 매체"
    if v == "unknown":
        return "판단 불가", s["reason"]
    lo, hi = s["range"]
    note = f"최근 {s['months']}개월 {fmt_pct(lo)} ~ {fmt_pct(hi)}"
    if s["over_ref"]:
        note += " · ±30% 참고선 넘음"
    return ("범위 밖" if v == "out" else "통과"), note


def cell_season(item):
    s = item["season"]
    v = s["verdict"]
    if v == "small":
        return "소액 제외", ""
    if v == "unknown":
        return "판단 불가", s["reason"]
    note = f"작년 {int(s['from'][5:])}월 → {int(s['to'][5:])}월 {fmt_pct(s['last_year'])}"
    return ("작년과 반대" if v == "opposite" else "통과"), note


FLAGGED = {"설명 필요", "범위 밖", "새로 배분", "작년과 반대"}


def count(months):
    keys = ("trend", "swing", "season")
    cells = {"trend": cell_trend, "swing": cell_swing, "season": cell_season}
    out = {k: 0 for k in keys}
    for m in months:
        for item in m["media"]:
            for k in keys:
                if cells[k](item)[0] in FLAGGED:
                    out[k] += 1
    return out


CSS = """body{margin:0;background:#f5f6f8;color:#262c34;font:14px/1.55 'Pretendard Variable',Pretendard,-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif}
.page{max-width:1200px;margin:0 auto;padding:24px 24px 64px}h1{margin:0 0 6px;font-size:24px}h2{margin:0;font-size:16px}
.sub{color:#6b7683;font-size:12px}.note{background:#fff8e6;border:1px solid #f3d58a;border-radius:10px;padding:12px 16px;margin:16px 0}
.note li{margin:2px 0}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:16px 0}
.kpi,.card{background:#fff;border:1px solid #e6e8ec;border-radius:12px}.kpi{padding:14px 16px}.k-v{font-size:22px;font-weight:700}
.card{margin-top:20px}.card-head{padding:14px 20px;border-bottom:1px solid #e6e8ec}.wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse}th{font-size:12px;color:#4f5a66;background:#fafbfc;border-bottom:1px solid #dcdfe4;padding:8px 10px;text-align:left;white-space:nowrap}
td{border-bottom:1px solid #eef0f3;padding:7px 10px;vertical-align:top}.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.tag{display:inline-block;padding:0 6px;border-radius:4px;font-size:12px;font-weight:600;white-space:nowrap}
.ok{background:#eef9f4;color:#245c4a}.flag{background:#fdecec;color:#a12f2f}.na{background:#f1f2f4;color:#5b6570}
tr.total td{font-weight:700;background:#fafbfc}"""


def tag(word):
    cls = "flag" if word in FLAGGED else "ok" if word == "통과" else "na"
    return f'<span class="tag {cls}">{html.escape(word)}</span>'


def render(brand, cost_metric, outcome_metric, months, failed):
    e = html.escape
    counts = count(months)
    parts = [f"<!doctype html><html lang='ko'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
             f"<title>{e(brand)} 예산안 백테스트 타당성 점검</title>"
             "<link rel='stylesheet' href='https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css'>"
             f"<style>{CSS}</style></head><body><div class='page'>",
             f"<h1>{e(brand)} 예산안 백테스트 타당성 점검</h1>",
             f"<div class='sub'>지표 {e(cost_metric)} · {e(outcome_metric)} · 대상 달 {e(', '.join(label(m['target_month']) for m in months))}</div>",
             "<div class='note'><b>읽기 전에</b><ul>"
             "<li>성과 검증이 아닙니다. 대상 달의 실제 성과와 맞춰 보지 않고, 제안대로 썼을 때의 결과도 판단하지 않습니다. "
             "배분이 그 시점까지의 데이터에 비춰 상식적으로 말이 되는지만 봅니다.</li>"
             "<li>백테스트 예산안은 기준 달 말일에 그 달 데이터를 모두 갖고 제안했다면 나왔을 값입니다. 당시 실제로 받은 제안과 다를 수 있습니다.</li>"
             "<li>총예산은 대상 달의 실제 집행액(VAT 제외 Net)을 썼습니다. 대상 달 실적은 이것 말고는 쓰지 않습니다.</li>"
             f"<li>비용은 모두 VAT 제외 Net입니다. 한 달 비용이 {fmt_won(FLOOR)} 미만인 달은 비율이 튀어 판정에 쓰지 않습니다.</li>"
             "</ul></div>",
             "<div class='kpis'>"
             f"<div class='kpi'><div class='sub'>점검한 달</div><div class='k-v'>{len(months)}개</div></div>"
             f"<div class='kpi'><div class='sub'>① 추세와 어긋남</div><div class='k-v'>{counts['trend']}건</div></div>"
             f"<div class='kpi'><div class='sub'>② 평소 변동 폭 밖</div><div class='k-v'>{counts['swing']}건</div></div>"
             f"<div class='kpi'><div class='sub'>③ 작년 흐름과 반대</div><div class='k-v'>{counts['season']}건</div></div></div>"]
    if failed:
        parts.append("<div class='note'><b>계산하지 못한 달</b><ul>" + "".join(
            f"<li>{e(label(m))}: {e(err or '사유 없음')}</li>" for m, err in failed) + "</ul></div>")
    for m in months:
        parts.append(f"<section class='card'><div class='card-head'><h2>{label(m['target_month'])} 예산안</h2>"
                     f"<div class='sub'>기준 달 {label(m['base_month'])} 실적 {fmt_won(m['base_total'])} → 제안 {fmt_won(m['proposed_total'])}"
                     f"(총예산 {fmt_won(m['budget'] or 0)})</div></div><div class='wrap'><table><thead><tr>"
                     f"<th>매체</th><th class='num'>{label(m['base_month'])} 실적</th><th class='num'>제안</th><th class='num'>증감</th>"
                     "<th>① 효율 추세</th><th>② 변동 폭</th><th>③ 작년 흐름</th></tr></thead><tbody>")
        for item in m["media"]:
            cells = "".join(f"<td>{tag(w)}<div class='sub'>{e(n)}</div></td>" for w, n in
                            (cell_trend(item), cell_swing(item), cell_season(item)))
            parts.append(f"<tr><td>{e(item['media'])}</td><td class='num'>{fmt_won(item['base_cost'])}</td>"
                         f"<td class='num'>{fmt_won(item['proposed_cost'])}</td><td class='num'>{fmt_pct(item['change'])}</td>{cells}</tr>")
        parts.append(f"<tr class='total'><td>합계</td><td class='num'>{fmt_won(m['base_total'])}</td>"
                     f"<td class='num'>{fmt_won(m['proposed_total'])}</td><td class='num'>{fmt_pct(pct(m['proposed_total'], m['base_total']))}</td>"
                     "<td></td><td></td><td></td></tr></tbody></table></div></section>")
    parts.append("<section class='card'><div class='card-head'><h2>판정 기준</h2></div><div style='padding:12px 20px'><ul>"
                 f"<li>① 효율 추세: 기준 달과 그 두 달 전의 효율({e(outcome_metric)} ÷ {e(cost_metric)})을 견줘 {fmt_pct(TREND, False)} 이상 오르면 개선, "
                 f"그만큼 내리면 악화로 봅니다. 개선 중인 매체를 줄이거나 악화 중인 매체를 늘리면(증감 {fmt_pct(DEAD, False)} 이상) 설명 필요로 표시합니다. "
                 "모델은 한계 효율로 배분하므로 이것만으로 잘못된 배분은 아닙니다.</li>"
                 f"<li>② 변동 폭: 제안 증감률이 그 매체의 최근 12개월 월간 증감률 범위를 벗어나면 범위 밖입니다. 관리자 참고선 ±30%도 함께 적습니다. "
                 "이 모델에는 월간 변동 상한이 없습니다.</li>"
                 f"<li>③ 작년 흐름: 작년 같은 시기(대상 달 13개월 전 → 12개월 전) 증감과 제안 증감의 방향이 반대면(둘 다 {fmt_pct(DEAD, False)} 이상) 작년과 반대입니다.</li>"
                 "</ul></div></section></div></body></html>")
    return "".join(parts), counts


def facts(months, counts, failed):
    flagged = []
    for m in months:
        for item in m["media"]:
            for key, fn in (("trend", cell_trend), ("swing", cell_swing), ("season", cell_season)):
                word, note = fn(item)
                if word in FLAGGED:
                    flagged.append({"target_month": m["target_month"], "media": item["media"], "check": key,
                                    "verdict": word, "change": fmt_pct(item["change"]), "note": note})
    return {"months": [m["target_month"] for m in months], "counts": counts, "flagged": flagged,
            "failed": [{"target_month": m, "error": err} for m, err in failed]}

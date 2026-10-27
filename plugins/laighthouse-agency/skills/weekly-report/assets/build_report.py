#!/usr/bin/env python3
"""weekly 최종 보고서 조립기 — 미리 검증된 asset 스크립트.

MCP 응답 원문(봉투·목표 표)을 섹션별로 그대로 받아, 공용 킷(`shared/assets/report_kit.*`)으로 뷰 모델을 계산하고
`assets/report-template.html`에 주입해 **최종 HTML 한 파일을 한 번의 호출로** 만든다.

기간 (기준일 D, 데이터 마지막 날 E = D-1):
  이번주 = E-6 ~ E, 전주 = E-13 ~ E-7, 최근 5주 = E-34 ~ E(7일 단위), 월 누적 = E가 속한 달 1일 ~ E

사용법:
  python3 assets/build_report.py <입력.json>      (또는 stdin으로 JSON)
  {"base": <assets/prepare.py가 만든 build.json 경로>, "dims": ..., "s2": ...} 형태도 받는다(base 내용에 나머지 키를 덮어쓴다).

입력 (JSON):
{
  "out": "~/Downloads/laighthouse-reports/{브랜드}_weekly_2026-09-20.html",   # 필수
  "title": "{브랜드} Weekly 보고서",                                         # 필수
  "target_date": "2026-09-20",                                             # 필수 (기준일 D)
  "skeleton": true,             # 선택 — 전 섹션 "데이터 준비 중"
  "metric_keys": {...}, "currency": "₩",          # discover.py 출력 그대로
  "dims": "<차원 확인(group_by [\"__list_dimensions__\"]) 에러 메시지 원문>",   # 필수(표가 있을 때) — 빠진 차원이 있으면 멈춘다
  "s1": {"json": "<month, group_by 없음, day_offset = E의 일, E의 전월 1일 ~ E 응답 원문>",
         "target_progress": "<get_target_progress_v2(month = E의 달, media 생략, as_of_date = E) 응답 원문>"},
  "s2": {"groups": [{"title": "소진", "lead": "...", "media": [{"name": "Google", "desc": "...",
                     "bullets": [{"label": "Masthead", "text": "...", "tone": "red|yellow|green|neutral"}]}]}, ...]},
  "s3": {"json": "<day, group_by [\"media\"], E-34 ~ E 응답 원문>"},
  "s4": {"cur": {"json_files": [...]}, "base": {"json_files": [...]}}
        # 이번주·전주 각 1회: total grain, group_by = 브랜드가 제공하는 차원(FINE_DIMS)
}
- 목표 표에 행이 있는 지표만 목표 대비 카드가 된다(현재 서버는 cost뿐). 목표가 없는 지표는 전월 동기간 대비 카드다.
- 응답에 없는 차원(예: 상품)은 표의 Dimension 메뉴에 나오지 않는다 — 조용히 빠진다.
- 출력(stdout): {"out", "bytes", "sections": {"s1".."s4": "ok"|"placeholder"}}
"""
import io
import json
import os
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
VOL_ROLES = ("impression", "click", "views")       # 월 목표 대비 누적 달성률(진행률 세로선)
GOAL_ROLES = ("impression", "click", "ctr", "views", "cpm", "cpv")
TONE_CLS = {"green": "good", "yellow": "warn", "red": "up"}
BAR_CLS = {"green": "", "yellow": "warn", "red": "up"}


def md(d):
    return f"{d.month}월 {d.day}일"


def range_label(a, b, short=False):
    """9/13~19 · 8/30~9/5 (short) / 9월 13일~19일 · 8월 30일~9월 5일"""
    if short:
        return f"{a.month}/{a.day}~{b.day}" if a.month == b.month else f"{a.month}/{a.day}~{b.month}/{b.day}"
    return f"{md(a)}~{b.day}일" if a.month == b.month else f"{md(a)}~{md(b)}"


def periods(target):
    E = target - timedelta(days=1)
    cur = (E - timedelta(days=6), E)
    base = (E - timedelta(days=13), E - timedelta(days=7))
    weeks = [(E - timedelta(days=34 - 7 * i), E - timedelta(days=28 - 7 * i)) for i in range(5)]
    return E, cur, base, weeks


def compute(payload, check_dims=True):
    target = date.fromisoformat(payload["target_date"])
    E, cur_w, base_w, weeks = periods(target)
    dim = monthrange(E.year, E.month)[1]
    elapsed = E.day / dim
    pm = date(E.year, E.month, 1) - timedelta(days=1)
    M0, M1 = f"{E:%Y-%m}", f"{pm:%Y-%m}"
    skeleton = bool(payload.get("skeleton"))
    keys = payload.get("metric_keys") or {}
    currency = payload.get("currency") or "₩"
    cost = keys.get("cost")

    def sec(name):
        return None if skeleton else payload.get(name)

    e1, e3 = kit.section_envelope(sec("s1")), kit.section_envelope(sec("s3"))
    s4 = sec("s4") or {}
    fine = {k: e for k in ("cur", "base") for e in [kit.section_envelope(s4.get(k))] if e} if isinstance(s4, dict) else {}
    e4 = dict(next(iter(fine.values())), rows=[r for e in fine.values() for r in e["rows"]]) if fine else None
    if fine and check_dims:
        # 받은 주만 검사한다 — 빠진 주는 차원 오류가 아니라 그 비교가 비는 것이다(prepare.py의 missing)
        kit.require_dims(payload.get("dims"), [({"cur": "s4 이번주", "base": "s4 전주"}[k], v) for k, v in fine.items()],
                         "s4 주간 비교 표")

    metrics, units = kit.metrics_units(e1, e3, e4)
    ratio_keys = {keys.get(r) for r in kit.RATIO_ROLES if keys.get(r)}
    additive = {x for x in metrics if units.get(x) != "%" and x not in ratio_keys}
    meta = kit.metric_meta(metrics, units, currency, additive, keys)
    mm = kit.meta_map(meta)

    # 대조 검증: 주간 표의 매체별 합 = 일별 매체 응답의 그 주 합
    if e3 and fine:
        atoms = [keys[r] for r in kit.ROLLUP_ROLES if keys.get(r)]
        checks = []
        for k, (a, b) in (("cur", cur_w), ("base", base_w)):
            if k not in fine:
                continue
            days = {(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)}
            sums = {}
            for r in e3.get("rows") or []:
                if kit.period_of(r) in days:
                    acc = sums.setdefault(kit._label(r.get("media")), {})
                    for m in atoms:
                        if isinstance(r.get(m), (int, float)):
                            acc[m] = acc.get(m, 0) + r[m]
            parent = {"metrics": atoms, "rows": [dict(v, date=k, media=n) for n, v in sums.items()]}
            checks.append((f"매체 ↔ 표({range_label(a, b, True)})",
                           kit.check_rollup(parent, ["media"], kit.with_period(fine[k], "date", k), ["media"], keys)))
        kit.require_rollup(checks)

    i3 = kit.index_rows(e3, ["media"])
    media = kit.ordered_names(i3) or kit.ordered_names(kit.index_rows(e4, ["media"]))
    colors = kit.media_colors(media)
    sections = {}

    # s1 — 월간 성과 요약: 월 누적(E의 달 1일~E) · 목표 대비 진척도 / 목표 없는 지표는 전월 동기간 대비
    i1 = kit.index_rows(e1, [])
    tot = lambda k: (i1.get(k) or {}).get(()) or {}  # noqa: E731
    targets = {}
    if e1 and tot(M0):
        cur, prev = tot(M0), tot(M1)
        targets = kit.parse_targets((sec("s1") or {}).get("target_progress"), keys)
        cards = []
        sp = cur.get(cost)
        if targets.get(cost) and isinstance(sp, (int, float)):
            r = sp / targets[cost]
            cards.append({"label": "예산 소진율", "value": f"{r * 100:.1f}%", "bar": r, "marker": elapsed,
                          "lines": [{"text": f"MTD 광고비 {kit.fmt_metric(sp, currency)}"}],
                          "sub": f"월 예산 {kit.fmt_metric(targets[cost], currency)} · 세로선은 기간 진행률({elapsed * 100:.1f}%)",
                          "deltas": []})
        roles = [r for r in kit.ROLES if keys.get(r) and (r != "cost" or not cards)]
        for role in roles:
            k = keys[role]
            unit = (mm.get(k) or {}).get("unit")
            v, g = cur.get(k), targets.get(k) if role != "cost" else None
            if g and isinstance(v, (int, float)) and role in VOL_ROLES:
                rr, gap = v / g, (v / g - elapsed) * 100
                pr = rr / elapsed if elapsed else None
                st = ("달성 예상", "green") if pr >= 1 else ("주의", "yellow") if pr >= 0.9 else ("미달 예상", "red")
                cards.append({"label": kit.ROLE_LABELS[role], "value": kit.fmt_metric(v, unit), "tag": {"label": st[0], "tone": st[1]},
                              "bar": rr, "marker": elapsed, "bar_cls": BAR_CLS[st[1]],
                              "lines": [{"text": f"월 목표 대비 {rr * 100:.1f}% (진행률 대비 {gap:+.1f}%p)", "cls": "lh-kpi-line " + TONE_CLS[st[1]]}],
                              "sub": f"월 목표 {kit.fmt_metric(g, unit)} · 예상 월마감 {kit.fmt_metric(v / elapsed, unit)} ({pr * 100:.0f}%)",
                              "deltas": []})
            elif g and isinstance(v, (int, float)) and v:
                higher = role not in kit.LOWER_BETTER_ROLES
                att = v / g if higher else g / v
                diff = (v / g - 1) * 100
                ok = diff >= -0.05 if higher else diff <= 0.05
                word = ("목표 이상" if ok else "목표 미만") if higher else ("목표 이하" if ok else "목표 초과")
                tone = "green" if ok else "red"
                cards.append({"label": kit.ROLE_LABELS[role], "value": kit.fmt_metric(v, unit),
                              "tag": {"label": "목표 달성" if ok else "목표 미달", "tone": tone}, "bar": att, "bar_cls": BAR_CLS[tone],
                              "lines": [{"text": f"목표 {kit.fmt_metric(g, unit)} 대비 {diff:+.1f}% ({word})", "cls": "lh-kpi-line " + TONE_CLS[tone]}],
                              "sub": ("높을수록" if higher else "낮을수록") + " 좋은 지표 · 막대는 목표 대비 달성도", "deltas": []})
            else:
                c = kit.kpi_cards(cur, [("prev", "전월 동기간", prev)], {role: k}, meta)[0]
                c["sub"] = f"전월 동기간 {kit.fmt_metric(prev.get(k), unit)}"
                cards.append(c)
        goal_labels = [kit.ROLE_LABELS[r] for r in GOAL_ROLES if keys.get(r) and targets.get(keys[r])]
        notes = []
        if goal_labels:
            notes.append(f"* {'·'.join(goal_labels)}은(는) 월 목표 대비 진척도입니다(노출·클릭·조회수는 누적 달성률, CTR·CPM·CPV는 목표 대비 달성도).")
        if any(c.get("marker") is not None for c in cards):
            notes.append(f"* 세로선은 기간 진행률({elapsed * 100:.1f}% = {E.day}/{dim}일)입니다.")
        if any(c.get("deltas") for c in cards):
            notes.append(f"* 목표가 없는 지표는 전월 동기간({pm.month}월 1일~{min(E.day, pm.day)}일) 대비 증감이며, 색은 방향만 나타냅니다(▲ 빨강 · ▼ 파랑).")
        sections["s1"] = {"cards": cards, "note": "\n".join(notes)}

    # s2 — Weekly Summary (모델 작성)
    s2 = sec("s2")
    groups = (s2 or {}).get("groups") if isinstance(s2, dict) else None
    if groups:
        out2 = []
        for g in groups:
            ms = [dict(m, dot=m.get("dot") or colors.get(m.get("name")) or colors.get(str(m.get("name", "")).split(" ")[0]))
                  for m in g.get("media") or []]
            out2.append({"title": g.get("title", ""), "lead": g.get("lead", ""), "media": ms})
        sections["s2"] = {"groups": out2}
    elif s2:
        b = kit.bullets_of(s2)
        sections["s2"] = {"bullets": b} if b else None

    # s3 — 매체별 주단위 성과 추이 (최근 5주): 일별 매체 응답을 7일씩 묶는다
    if e3:
        buckets = {}
        for i, (a, b) in enumerate(weeks):
            for j in range((b - a).days + 1):
                buckets[(a + timedelta(days=j)).isoformat()] = i
        wv = kit.bucket_values(e3, ["media"], buckets, metrics, units, keys)
        series = [{"name": n, "color": colors[n],
                   "values": {x: [((wv.get(i) or {}).get((n,)) or {}).get(x) for i in range(5)] for x in metrics}} for n in media]
        shown = [m for m in meta if any(v is not None for s in series for v in s["values"][m["key"]])]   # 값 없는 지표는 탭에서 뺀다
        if shown:
            sections["s3"] = {"labels": [range_label(a, b, True) for a, b in weeks], "metrics": shown,
                              "default_metric": cost if cost in {m["key"] for m in shown} else shown[0]["key"], "series": series}

    # s4 — 주간 성과 비교 (Dimension·지표 선택)
    if fine:
        dims = [d for d in (e4.get("dimensions") or []) if d not in kit.PIVOT_SKIP_DIMS and not d.endswith("_id")]
        dd = [d for d in dims if d != P]
        dd = dd if len(dd) > 1 else dims
        sections["s4"] = kit.pick_section(
            fine, meta, keys, dots=colors, default_dims=dd, labels={"ad_name": "소재"}, search_dim="campaign_name",
            compare={"base": "base", "cur": "cur", "base_label": "전주 " + range_label(*base_w, True),
                     "cur_label": "이번주 " + range_label(*cur_w, True)})

    for k in ("s1", "s2", "s3", "s4"):
        sections.setdefault(k, None)
    rep = {
        "__TITLE__": payload["title"],
        "__DATE_LABEL__": kit.kdate(target),
        "__PERIODS__": f"이번주: {range_label(*cur_w)} · 전주: {range_label(*base_w)} · 월 누적: {E.month}월 1일~{E.day}일",
        "__MEDIA_SUM__": (" + ".join(media) + " 합산, ") if media else "",
        "__MTD_RANGE__": f"{E.month}월 1일~{E.day}일 누적",
        "__S1_DESC__": "월간 목표 대비 진척도" if targets else "전월 동기간 대비",
        "__CUR_SHORT__": range_label(*cur_w, True), "__BASE_SHORT__": range_label(*base_w, True),
        "__WEEKS_RANGE__": f"{md(weeks[0][0])}~{md(weeks[-1][1])}",
        "__CMP_TITLE__": f"{range_label(*base_w)} vs {range_label(*cur_w)}",
    }
    ctx = {"E": E, "cur_w": cur_w, "base_w": base_w, "M0": M0, "elapsed": elapsed, "keys": keys, "currency": currency,
           "metrics": metrics, "units": units, "media": media, "fine": fine, "tot": tot(M0) if e1 else {},
           "targets": targets, "e3": e3}
    return sections, rep, ctx


def digest(payload):
    """Weekly Summary 작성 근거 — 이번주·전주 값과 변화(매체, 매체-상품). 화면 표와 같은 규칙의 숫자다."""
    sections, rep, c = compute(payload, check_dims=False)
    keys, metrics, units, cur_c = c["keys"], c["metrics"], c["units"], c["currency"]
    mm, fmt, change = kit.digest_fmt(keys, units, cur_c)
    unit_of = lambda k: units.get(k) or (cur_c if k in {keys.get(r) for r in kit.MONEY_ROLES} else None)  # noqa: E731

    out = {"이번주": rep["__CUR_SHORT__"], "전주": rep["__BASE_SHORT__"]}
    if c["tot"]:
        sp, bud = c["tot"].get(keys.get("cost")), c["targets"].get(keys.get("cost"))
        out["월누적"] = {"광고비": kit.fmt_metric(sp, cur_c, cur_c), "월예산": kit.fmt_metric(bud, cur_c, cur_c) if bud else None,
                       "소진율": f"{sp / bud * 100:.1f}%" if bud and isinstance(sp, (int, float)) else None,
                       "기간진행률": f"{c['elapsed'] * 100:.1f}%",
                       "목표": {mm[k]: kit.fmt_metric(v, unit_of(k), cur_c) for k, v in c["targets"].items() if k in mm}}
    fine = c["fine"]
    if "cur" in fine and "base" in fine:
        dims = fine["cur"].get("dimensions") or []
        for name, ds in (("전체", []), ("매체", ["media"]), ("매체-상품", ["media", P])):
            if any(d not in dims for d in ds):
                continue   # 응답에 없는 차원은 건너뛴다
            a = kit.group_values(fine["cur"], ds, metrics, units, keys)
            b = kit.group_values(fine["base"], ds, metrics, units, keys)
            ks = sorted(a, key=lambda k: -((a[k].get(keys.get("cost")) or 0)))
            out[name] = [{"이름": " ".join(k) or "전체", "이번주": fmt(a[k]), "전주": fmt(b.get(k) or {}),
                          "변화": change(a[k], b.get(k) or {})} for k in ks[:kit.DIGEST_TOP]]
            if len(ks) > kit.DIGEST_TOP:
                out[name + " 생략"] = f"광고비 상위 {kit.DIGEST_TOP}개만 — 나머지 {len(ks) - kit.DIGEST_TOP}개"
    return out


def main():
    payload = kit.read_payload()
    sections, rep, _ = compute(payload)
    report = {"currency": payload.get("currency") or "₩", "sections": sections}
    path, size = kit.build_html(ASSETS_DIR, rep, report, payload["out"])
    json.dump({"out": path, "bytes": size,
               "sections": {k: ("ok" if sections[k] is not None else "placeholder") for k in sorted(sections)}},
              sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()

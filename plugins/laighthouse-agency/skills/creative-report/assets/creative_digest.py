"""소재 성과 — 요약 근거(digest)와 소재 기준 상수. 모델이 직접 부르지 않는다.

digest는 모델이 「소재 Summary」를 쓸 근거다(guides/creative-summary.md). 수치는 화면에 쓸 문자열로 만들어 두고,
변화(직전 기간 대비)도 미리 계산한다 — 모델은 값을 다시 계산하지 않고 그대로 옮긴다.
"""

MIN_IMP, MIN_SHARE = 1000, 0.01   # 비율 지표(CTR·ROAS) 순위·효율 비교에 쓰는 최소 표본: 노출 ≥ 1,000 그리고 광고비 ≥ 매체 광고비의 1%
ATOMS = ("cost", "impression", "click", "conversion", "revenue", "view")   # 원자 지표 — 보고서 화면 JS의 순서와 같다


def ratios(e):
    imp, clk, cost = e["impression"], e["click"], e["cost"]
    e["ctr"] = clk / imp * 100 if imp else None
    e["cpc"] = cost / clk if clk else None
    e["cvr"] = e["conversion"] / clk * 100 if clk else None
    e["roas"] = e["revenue"] / cost * 100 if cost else None
    return e


def total(rows):
    t = {k: 0 for k in ATOMS}
    for e in rows:
        for k in ATOMS:
            t[k] += e[k]
    return ratios(t)


# ── 표기 ──────────────────────────────────────────────────────────────────────────────────────────────
def money(v, cur):
    if v is None:
        return "-"
    return "%s%s" % (cur, format(round(v, 1), ",.1f") if abs(v) < 100 and v != int(v) else format(round(v), ","))


def count(v):
    return "-" if v is None else format(round(v), ",")


def pct(v, digits=1):
    return "-" if v is None else "%.*f%%" % (digits, v)


def change(cur, prev, pp=False):
    """직전 기간 대비. 비율 지표는 %p 차, 나머지는 변화율. 직전 값이 0·없음이면 '신규', 이번 값이 0이면 '중단'."""
    if cur is None or prev is None:
        return "-"
    if pp:
        return "%+.1f%%p" % (cur - prev)
    if not prev:
        return "신규" if cur else "-"
    if not cur:
        return "중단"
    return "%+.1f%%" % ((cur - prev) / abs(prev) * 100)


def card(e, p, cur, has):
    """지표 묶음(값 + 직전 대비). p가 None이면 비교 없이 값만."""
    out = {"광고비": money(e["cost"], cur), "노출": count(e["impression"]), "클릭": count(e["click"]),
           "CTR": pct(e["ctr"], 2), "CPC": money(e["cpc"], cur)}
    if has["conversion"]:
        out.update({"전환": count(e["conversion"]), "CVR": pct(e["cvr"])})
    if has["revenue"]:
        out["ROAS"] = pct(e["roas"])
    if p is not None:
        diff = {"광고비": change(e["cost"], p["cost"]), "노출": change(e["impression"], p["impression"]),
                "클릭": change(e["click"], p["click"]), "CTR": change(e["ctr"], p["ctr"], True),
                "CPC": change(e["cpc"], p["cpc"])}
        if has["conversion"]:
            diff.update({"전환": change(e["conversion"], p["conversion"]), "CVR": change(e["cvr"], p["cvr"], True)})
        if has["revenue"]:
            diff["ROAS"] = change(e["roas"], p["roas"], True)
        out["직전 대비"] = diff
    return out


def label(e):
    """요약에 쓸 소재 이름: 매체 / 캠페인 / 광고그룹 / 소재."""
    parts = [e["media"], e["campaign_name"], e["ad_group_name"], e["name"]]
    out = []
    for p in parts:
        if p and p not in out:
            out.append(str(p))
    return " / ".join(out)


def key(e):
    return (e["media"], e["campaign_name"], e["ad_group_name"], e["ad_id"], e["ad_name"])


def eligible(items):
    tc = sum(e["cost"] for e in items)
    return [e for e in items if e["impression"] >= MIN_IMP and e["cost"] >= tc * MIN_SHARE]


def build(rows, prev_rows, has, cur, period, prev_period, top=5):
    """요약 근거. prev_rows가 None이면 직전 기간 비교 없이 값만 낸다."""
    pmap = {key(e): e for e in prev_rows or []}
    by_media = {}
    for e in rows:
        by_media.setdefault(e["media"], []).append(e)
    pby = {}
    for e in prev_rows or []:
        pby.setdefault(e["media"], []).append(e)
    order = sorted(by_media, key=lambda m: -sum(x["cost"] for x in by_media[m]))
    cmp_ = prev_rows is not None
    d = {"기간": period, "직전 기간": prev_period if cmp_ else "없음(비교하지 않는다)",
         "전체": card(total(rows), total(prev_rows) if cmp_ else None, cur, has), "매체": []}
    eff_key, eff_label = ("roas", "ROAS") if has["revenue"] else ("ctr", "CTR")
    for m in order:
        items = by_media[m]
        tc = sum(x["cost"] for x in items)
        md = {"매체": m, "소재 수": len(items),
              "성과": card(total(items), total(pby.get(m, [])) if cmp_ else None, cur, has), "광고비 상위 소재": []}
        for e in sorted(items, key=lambda x: -x["cost"])[:top]:
            c = card(e, pmap.get(key(e)) if cmp_ else None, cur, has)
            if cmp_ and key(e) not in pmap:
                c["직전 대비"] = "신규 집행"
            md["광고비 상위 소재"].append(dict({"소재": label(e), "광고비 비중": pct(e["cost"] / tc * 100 if tc else None)}, **c))
        pool = eligible(items)
        for k, lab in ((eff_key, eff_label), ("cpc", "CPC")):
            cand = [e for e in pool if e[k] is not None]
            if len(cand) < 2:
                continue
            best = sorted(cand, key=lambda x: (x[k] if k != "cpc" else -x[k]), reverse=True)
            fmt = (lambda v: money(v, cur)) if k == "cpc" else (lambda v: pct(v, 2 if k == "ctr" else 1))
            n = 2 if len(best) >= 4 else 1   # 소재가 적으면 위아래 하나씩만 — 우수·저조가 겹치지 않게
            row = lambda e: {"소재": label(e), lab: fmt(e[k]), "광고비": money(e["cost"], cur)}  # noqa: E731
            md["%s 우수" % lab] = [row(e) for e in best[:n]]
            md["%s 저조" % lab] = [row(e) for e in best[::-1][:n]]
        md["최소 표본"] = "노출 %s 이상·광고비 %s 이상 소재 %d개(우수·저조는 이 소재만 비교)" % (
            format(MIN_IMP, ","), money(tc * MIN_SHARE, cur), len(pool))
        d["매체"].append(md)
    if cmp_:   # 직전 기간 대비 광고비 변동(절대액)이 큰 소재 — 신규 집행·집행 중단 포함
        moves = []
        for e in rows:
            p = pmap.get(key(e))
            moves.append((abs(e["cost"] - (p["cost"] if p else 0)), e, p))
        cur_keys = {key(e) for e in rows}
        for k, p in pmap.items():
            if k not in cur_keys and p["cost"]:
                moves.append((p["cost"], None, p))
        moves.sort(key=lambda x: -x[0])
        d["광고비 변동 상위 소재"] = [
            {"소재": label(e or p), "광고비": "%s → %s" % (money(p["cost"] if p else 0, cur), money(e["cost"] if e else 0, cur)),
             "변화": "신규 집행" if not p or not p["cost"] else "집행 중단" if not e or not e["cost"] else change(e["cost"], p["cost"])}
            for _, e, p in moves[:top] if _]
    return d


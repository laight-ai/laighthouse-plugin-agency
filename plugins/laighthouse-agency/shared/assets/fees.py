"""광고비·예산 Gross / Net — 빌더가 공유하는 규칙.

광고비 실적(get_ad_performance)은 항상 Net이다. 예산(get_target_progress_v2 원문 둘째 표)에 수수료가 있으면
(같은 범위의 cost ≠ cost_net) Gross 보기를 더 만든다.
- Gross 광고비 = Net × (그 범위의 cost ÷ cost_net). 범위는 캠페인 → 매체 → 1(수수료 0%) 순.
  매체 행에 비율이 없으면 그 매체에 포함된 캠페인(included N 제외)의 합(Gross 합 ÷ Net 합)으로 채운다.
- 수수료는 달마다 같다고 본다 — 그 달 비율이 없으면 다른 달(가장 최근) 비율을 쓴다.
- Net 예산 = cost_net. 없는 범위는 Gross − 한 단계 아래 범위(전체 → 매체, 매체 → 캠페인, included N 제외)의 수수료 합.
- 화면의 위·아래 단계 숫자가 맞도록, 덜 잘게 받은 응답(매체·전체)은 더 잘게 받은 응답을 환산한 결과에서 구한
  실효 비율(Σ Gross ÷ Σ Net)을 쓴다(eff_factors → gross_envelope(eff=...)).

부품:
- 원문용(weekly·monthly): parse_fees · has_fee · gross_envelope · eff_factors · net_target_text
- 파싱된 예산 목록용(종합 리포트): fee_ratios · ratios_have_fee · add_gross · net_budgets
"""
import re

from report_kit import label, period_of

_COST_PER_RE = re.compile(r"^cp[a-z]{1,2}$", re.I)   # CPM·CPC·CPV·CPA… — 광고비 ÷ 무엇 → Gross 비율만큼 커진다
_PER_COST = {"roas"}                                  # 무엇 ÷ 광고비 → Gross 비율만큼 작아진다


def _nk(s):
    return str(s).strip().lower()


def _money(v):
    """환산 금액 — 소수 둘째 자리까지(원 단위 통화는 정수가 된다)."""
    v = round(v, 2)
    return int(v) if float(v).is_integer() else v


# ── 원문(get_target_progress_v2) ─────────────────────────────────────────────


def _rows(text):
    """둘째 표 → [(매체, 캠페인 또는 '-', included, metric, 목표)]. 목표가 0이거나 숫자가 아니면 뺀다."""
    out = []
    for ln in (text or "").splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] in ("media", "") or set(cells[0]) <= {"-", " "}:
            continue
        try:
            v = float(cells[4].replace(",", ""))
        except ValueError:
            continue
        if v:
            out.append((cells[0], cells[1], cells[2], cells[3], v))
    return out


def _first_row(text, metric):
    m = re.search(r"^\|\s*" + metric + r"\s*\|\s*([0-9][0-9.,]*)\s*\|", text or "", re.M)
    return float(m.group(1).replace(",", "")) if m else None


def _budget_maps(text):
    """둘째 표 → (Gross {(매체, 캠페인): 값}, Net {…}, 미포함 캠페인 집합). 이름은 소문자·공백 정리, 매체 행의 캠페인은 '-'."""
    g, n, excl = {}, {}, set()
    for media, camp, inc, name, v in _rows(text):
        k = (_nk(media), "-" if camp == "-" else _nk(camp))
        if name == "cost":
            g[k] = v
        elif name == "cost_net":
            n[k] = v
        if inc == "N":
            excl.add(k)
    return g, n, excl


def parse_fees(text):
    """목표 원문 → {"media": {매체: Gross÷Net}, "campaign": {(매체, 캠페인): Gross÷Net}}."""
    g, n, excl = _budget_maps(text)
    media_r, camp_r, sums = {}, {}, {}
    for (m, c), gv in g.items():
        nv = n.get((m, c))
        if not nv:
            continue
        if c == "-":
            media_r[m] = gv / nv
        else:
            camp_r[(m, c)] = gv / nv
            if (m, c) not in excl:
                s = sums.setdefault(m, [0.0, 0.0])
                s[0] += gv
                s[1] += nv
    for m, (gv, nv) in sums.items():
        media_r.setdefault(m, gv / nv)
    return {"media": media_r, "campaign": camp_r}


def has_fee(fees):
    return any(abs(r - 1) > 1e-9 for d in (fees or {}).values() for r in d.values())


BASIS_NOTE = {True: "Gross(광고비 = 매체 집행액 Net × 수수료 비율, 예산 = Gross)", False: "Net(수수료 미등록 — Gross = Net)"}


def net_only(net, gross):
    """Net 섹션 묶음에서 Gross와 같은 섹션을 뺀다 — 화면은 빠진 섹션을 기본(Gross) 묶음에서 가져온다."""
    return {k: v for k, v in net.items() if v != gross.get(k)}


def report_has_fee(target_progress):
    """목표 원문에 수수료가 있으면(cost ≠ cost_net) True — Weekly·Monthly 빌더가 Gross/Net 두 벌을 만들지 정한다."""
    return has_fee(parse_fees(target_progress))


def _scalers(metrics, metric_keys):
    """지표마다 Gross 환산 방향: +1(×비율) · -1(÷비율). 환산하지 않는 지표는 빠진다."""
    cost_like = {metric_keys.get(k) for k in ("cost", "cpm", "cpv") if metric_keys.get(k)}
    out = {}
    for x in metrics:
        if x in cost_like or _COST_PER_RE.match(x):
            out[x] = 1
        elif x.lower() in _PER_COST:
            out[x] = -1
    return out


def gross_envelope(env, fees, metric_keys, eff=None, eff_key=None):
    """Net 봉투 → Gross 봉투(광고비·CPM·CPC·CPV 등은 ×비율, ROAS는 ÷비율). 행 순서는 그대로다.
    캠페인이 있는 행은 그 캠페인 비율. 그 밖의 행(매체 행·전체 합계)은 eff(더 잘게 받은 응답에서 구한 실효 비율)에서
    (기간, 매체) → (전체 기간, 매체) 순으로 찾고(매체가 없는 행은 매체 = 전체), 없으면 매체 비율 → 1.
    eff_key(행) = eff를 찾을 기간 키(기본 period_of)."""
    if not env:
        return env
    eff = eff or {}
    key = eff_key or period_of
    sc = _scalers(env.get("metrics") or [], metric_keys)
    rows = []
    for r in env.get("rows") or []:
        m = _nk(label(r.get("media"))) if r.get("media") is not None else None
        c = _nk(label(r.get("campaign_name"))) if m is not None and r.get("campaign_name") is not None else None
        f = ((c is not None and fees["campaign"].get((m, c))) or eff.get((key(r), m)) or eff.get((None, m))
             or (m is not None and fees["media"].get(m)) or 1.0)
        out = dict(r)
        for x, d in sc.items():
            v = r.get(x)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[x] = v * f if d > 0 else v / f
        rows.append(out)
    return dict(env, rows=rows)


def eff_factors(pairs, metric_keys):
    """[(Net 봉투, 같은 순서의 Gross 봉투, 기간 키 함수)] → 실효 비율 {(기간 또는 None, 매체 또는 None): Σ Gross ÷ Σ Net}.
    None 기간 = 모든 기간 합, None 매체 = 모든 매체 합. 덜 잘게 받은 응답을 같은 숫자로 환산할 때 gross_envelope(eff=...)에 넘긴다."""
    cost = metric_keys.get("cost")
    acc = {}
    for net, gross, key in pairs:
        if not net or not gross:
            continue
        for a, b in zip(net.get("rows") or [], gross.get("rows") or []):
            v, w = a.get(cost), b.get(cost)
            if not isinstance(v, (int, float)) or not isinstance(w, (int, float)):
                continue
            m = _nk(label(a.get("media"))) if a.get("media") is not None else None
            p = key(a)
            for k in {(p, m), (None, m), (p, None), (None, None)}:
                s = acc.setdefault(k, [0.0, 0.0])
                s[0] += w
                s[1] += v
    return {k: g / n for k, (g, n) in acc.items() if n}


def _fmt_num(v):
    return str(int(v)) if float(v).is_integer() else f"{v:.4f}".rstrip("0").rstrip(".")


def net_target_text(text):
    """목표 원문 → cost 목표를 Net 예산으로 바꾼 원문(Net 보기용 — 다른 파서를 그대로 쓴다).
    둘째 표: 같은 범위의 cost_net, 없으면 Gross − 그 매체 캠페인(included N 제외)의 수수료 합.
    첫째 표: 첫째 표의 cost_net이 있으면 그 값, 없으면 전체 Gross − 매체 수수료 합."""
    if not text:
        return text
    g, n, excl = _budget_maps(text)

    def net(k):
        if k in n:
            return n[k]
        if k[1] != "-":
            return g[k]
        return g[k] - sum(gv - net(x) for x, gv in g.items() if x[0] == k[0] and x[1] != "-" and x not in excl)

    first_net = _first_row(text, "cost_net")
    media_fee = sum(gv - net(k) for k, gv in g.items() if k[1] == "-")
    out = []
    for ln in text.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")] if ln.strip().startswith("|") else None
        k = (_nk(cells[0]), "-" if cells[1] == "-" else _nk(cells[1])) if cells and len(cells) >= 5 else None
        if k and cells[3] == "cost" and k in g:
            cells[4] = _fmt_num(net(k))
            ln = "| " + " | ".join(cells) + " |"
        elif cells and len(cells) >= 2 and cells[0] == "cost" and (first_net or media_fee):
            try:
                cells[1] = _fmt_num(first_net or float(cells[1].replace(",", "")) - media_fee)
                ln = "| " + " | ".join(cells) + " |"
            except ValueError:
                pass
        out.append(ln)
    return "\n".join(out)


# ── 파싱된 예산 목록(종합 리포트 parse_budget: {"mo", "scope": {"m"?, "c"?}, "v": {"cost", "cost_net", …}, "inc"?}) ──


def fee_ratios(budgets):
    """예산 목록 → {(달 또는 None, 매체, 캠페인 또는 None): Gross ÷ Net}. 매체·캠페인 범위에 cost·cost_net이 둘 다 있을 때만.
    매체 비율이 없으면 그 매체에 포함된 캠페인(inc N 제외)의 합으로 채운다. 달이 None인 키 = 가장 최근 달의 비율
    (수수료는 달마다 같다고 보고, 그 달 비율이 없을 때 쓴다)."""
    out, camp, direct = {}, {}, set()
    for b in sorted(budgets, key=lambda b: b["mo"]):
        g, n, sc = b["v"].get("cost"), b["v"].get("cost_net"), b["scope"]
        if not g or not n or "m" not in sc or set(sc) - {"m", "c"}:
            continue
        k = (sc["m"], sc.get("c"))
        out[(b["mo"],) + k] = out[(None,) + k] = g / n   # 달 순서로 돌아 None 키는 가장 최근 달 값이 남는다
        if "c" not in sc:
            direct.add(sc["m"])
        elif b.get("inc") != "N":
            s = camp.setdefault((b["mo"], sc["m"]), [0.0, 0.0])
            s[0] += g
            s[1] += n
    for (mo, m), (g, n) in sorted(camp.items()):
        out.setdefault((mo, m, None), g / n)
        if m not in direct:
            out[(None, m, None)] = g / n
    return out


def ratios_have_fee(ratios):
    return any(abs(r - 1) > 1e-9 for r in ratios.values())


def add_gross(rows, ratios):
    """원자 행마다 Gross 광고비(cost_g)를 붙인다 — 그 달 캠페인 → 그 달 매체 → 다른 달 캠페인 → 다른 달 매체 → 1."""
    for r in rows:
        mo, m, c = f"{r['day']:%Y-%m}", r["m"], r.get("c")
        f = ((c is not None and ratios.get((mo, m, c))) or ratios.get((mo, m, None))
             or (c is not None and ratios.get((None, m, c))) or ratios.get((None, m, None)) or 1.0)
        r["cost_g"] = _money(r["cost"] * f)


def _net_cost(b, budgets):
    """cost_net이 없는 범위(첫째 표의 전체 합계, 캠페인 목표만 있는 매체 등)의 Net 예산 = Gross − 한 단계 아래 범위의 수수료 합
    (전체 → 매체, 매체 → 캠페인 — 미포함 캠페인 제외). 아래 범위에 수수료가 없으면 수수료 0%(Gross 그대로)."""
    sc = b["scope"]
    nxt = "m" if not sc else "c" if set(sc) == {"m"} else None
    fee = 0.0
    if nxt:
        for x in budgets:
            xs = x["scope"]
            if (x["mo"] == b["mo"] and set(xs) == set(sc) | {nxt} and all(xs[k] == sc[k] for k in sc)
                    and x.get("inc") != "N" and x["v"].get("cost")):
                fee += x["v"]["cost"] - (x["v"].get("cost_net") or _net_cost(x, budgets))
    return b["v"]["cost"] - fee


def net_budgets(budgets, derive=None):
    """Net 보기의 예산 목록: cost = cost_net(없으면 _net_cost). derive(v)를 주면 서버가 준 목표(b["srv"])만 남기고
    Net 예산으로 비어 있는 목표(노출 = 예산/CPM 등)를 다시 계산한다 — Gross 예산으로 계산한 값이 남지 않게."""
    out = []
    for b in budgets:
        v = {k: x for k, x in b["v"].items() if k in b["srv"]} if derive and "srv" in b else dict(b["v"])
        n = v.pop("cost_net", None)
        if b["v"].get("cost"):
            v["cost"] = n or _net_cost(b, budgets)
        if derive:
            derive(v)
        out.append(dict(b, v=v))
    return out

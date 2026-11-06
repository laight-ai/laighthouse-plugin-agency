"""옛 서버(get_ad_performance 봉투에 fee_basis가 없는 응답)의 Gross / Net 규칙과, 두 경로를 잇는 view·bundle·digest_note.
report-backend#522가 모든 환경에 배포되면 이 파일과 빌더의 fees_legacy 호출을 지운다.

광고비 실적은 항상 Net이다. 예산(get_target_progress_v2 원문 둘째 표)에 수수료가 있으면(같은 범위의 cost ≠ cost_net) Gross 보기를 더 만든다.
- Gross 광고비 = Net × (그 범위의 cost ÷ cost_net). 범위는 캠페인 → 매체 → 1(수수료 0%) 순.
  매체 행에 비율이 없으면 그 매체에 포함된 캠페인(included N 제외)의 합(Gross 합 ÷ Net 합)으로 채운다.
- 수수료는 달마다 같다고 본다 — 그 달 비율이 없으면 다른 달(가장 최근) 비율을 쓴다.
- Net 예산 = cost_net. 없는 범위는 Gross − 한 단계 아래 범위(전체 → 매체, 매체 → 캠페인, included N 제외)의 수수료 합.
- 화면의 위·아래 단계 숫자가 맞도록, 덜 잘게 받은 응답(매체·전체)은 더 잘게 받은 응답을 환산한 결과에서 구한
  실효 비율(Σ Gross ÷ Σ Net)을 쓴다(fees.eff_factors → gross_envelope(eff=...)).
"""
import re

import fees
from report_kit import label, period_of


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
        k = (fees.nk(media), "-" if camp == "-" else fees.nk(camp))
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


def has_fee(fz):
    return any(abs(r - 1) > 1e-9 for d in (fz or {}).values() for r in d.values())


BASIS_UI = {"label": fees.TOGGLE_LABEL, "options": [
    {"key": "gross", "label": "Gross", "title": "광고비 = 매체 집행액(Net) × 수수료 비율(Gross 예산 ÷ Net 예산), 예산 = Gross"},
    {"key": "net", "label": "Net", "title": "광고비 = 매체 집행액(Net), 예산 = Net"}]}
BASIS_NOTE = {True: "Gross(광고비 = 매체 집행액 Net × 수수료 비율, 예산 = Gross)", False: "Net(수수료 미등록 — Gross = Net)"}


def _fee_pct(r):
    """Gross ÷ Net → 수수료율(%) 문자열 — 그리드 입력과 같은 정의(Net = Gross × (1 − 수수료))."""
    v = round((1 - 1 / r) * 100, 1)
    return f"{v:g}%"


def _fee_text(by_media):
    """{매체: [비율…]} → '수수료 Meta 15% · Google 10%'. 매체 안에서 캠페인마다 다르면 '10~15%'."""
    parts = []
    for m, rs in by_media.items():
        ps = sorted({round((1 - 1 / r) * 100, 1) for r in rs})
        parts.append(f"{m} " + (_fee_pct(1 / (1 - ps[0] / 100)) if len(ps) == 1 else f"{ps[0]:g}~{ps[-1]:g}%"))
    return "수수료 " + " · ".join(parts) if parts else ""


def fee_note(target_progress):
    """목표 원문 → 토글 옆 수수료율 문구(Weekly·Monthly — 기준 달). 매체 표기는 원문 그대로."""
    g, n, _ = _budget_maps(target_progress)
    names = {fees.nk(m): m for m, *_ in _rows(target_progress)}
    by = {}
    for k, gv in g.items():
        if n.get(k):
            by.setdefault(names.get(k[0], k[0]), []).append(gv / n[k])
    return _fee_text(by)


def basis_ui(note=""):
    """토글 문구 + 수수료율 문구(note) — 화면은 받아 그리기만 한다."""
    return dict(BASIS_UI, note=note) if note else dict(BASIS_UI)


def basis_bundle(gross, net, summary_note, note=""):
    """Weekly·Monthly report["basis"] — 기본(Gross) 섹션은 report.sections, Net은 달라진 섹션만, s2(모델 요약) 아래 각주,
    note = 토글 옆 수수료율 문구(fee_note)."""
    return dict(basis_ui(note), default="gross", sections={"net": fees.changed_only(net, gross)}, notes={"net": {"s2": summary_note}})


def report_has_fee(target_progress):
    """목표 원문에 수수료가 있으면(cost ≠ cost_net) True — Weekly·Monthly 빌더가 Gross/Net 두 벌을 만들지 정한다."""
    return has_fee(parse_fees(target_progress))


def gross_envelope(env, fz, metric_keys, eff=None, eff_key=None):
    """Net 봉투 → Gross 봉투(광고비·CPM·CPC·CPV 등은 ×비율, ROAS는 ÷비율). 행 순서는 그대로다.
    캠페인이 있는 행은 그 캠페인 비율. 그 밖의 행(매체 행·전체 합계)은 eff(더 잘게 받은 응답에서 구한 실효 비율)에서
    (기간, 매체) → (전체 기간, 매체) 순으로 찾고(매체가 없는 행은 매체 = 전체), 없으면 매체 비율 → 1.
    eff_key(행) = eff를 찾을 기간 키(기본 period_of)."""
    if not env:
        return env
    eff = eff or {}
    key = eff_key or period_of
    sc = fees.scalers(env.get("metrics") or [], metric_keys)
    rows = []
    for r in env.get("rows") or []:
        m = fees.nk(label(r.get("media"))) if r.get("media") is not None else None
        c = fees.nk(label(r.get("campaign_name"))) if m is not None and r.get("campaign_name") is not None else None
        f = ((c is not None and fz["campaign"].get((m, c))) or eff.get((key(r), m)) or eff.get((None, m))
             or (m is not None and fz["media"].get(m)) or 1.0)
        out = dict(r)
        for x, d in sc.items():
            v = r.get(x)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[x] = v * f if d > 0 else v / f
        rows.append(out)
    return dict(env, rows=rows)


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
    # 매체 수수료 — 매체 행이 있으면 그 행, 없으면(캠페인 목표만 있는 매체) 포함 캠페인 수수료의 합
    media_fee = sum(gv - net(k) for k, gv in g.items() if k[1] == "-")
    media_fee += sum(gv - net(k) for k, gv in g.items() if k[1] != "-" and k not in excl and (k[0], "-") not in g)
    out = []
    for ln in text.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")] if ln.strip().startswith("|") else None
        k = (fees.nk(cells[0]), "-" if cells[1] == "-" else fees.nk(cells[1])) if cells and len(cells) >= 5 else None
        if k and cells[3] == "cost" and k in g:
            cells[4] = fees.fmt_num(net(k))
            ln = "| " + " | ".join(cells) + " |"
        elif cells and len(cells) >= 2 and cells[0] == "cost" and (first_net or media_fee):
            try:
                cells[1] = fees.fmt_num(first_net or float(cells[1].replace(",", "")) - media_fee)
                ln = "| " + " | ".join(cells) + " |"
            except ValueError:
                pass
        out.append(ln)
    return "\n".join(out)


def fee_ratios(budgets):
    """예산 목록 → {(달 또는 None, 매체, 캠페인 또는 None): Gross ÷ Net}. 매체·캠페인 범위에 cost·cost_net이 둘 다 있을 때만.
    매체 비율이 없으면 그 달 그 매체에 포함된 캠페인(inc N 제외)의 합으로 채운다. 달이 None인 키 = 그 범위 비율이 있는
    가장 최근 달의 값(수수료는 달마다 같다고 보고, 그 달 비율이 없을 때 쓴다)."""
    out, camp = {}, {}
    for b in budgets:
        g, n, sc = b["v"].get("cost"), b["v"].get("cost_net"), b["scope"]
        if not g or not n or "m" not in sc or set(sc) - {"m", "c"}:
            continue
        out[(b["mo"], sc["m"], sc.get("c"))] = g / n
        if "c" in sc and b.get("inc") != "N":
            s = camp.setdefault((b["mo"], sc["m"]), [0.0, 0.0])
            s[0] += g
            s[1] += n
    for (mo, m), (g, n) in camp.items():
        out.setdefault((mo, m, None), g / n)
    for (mo, m, c) in sorted((k for k in list(out) if k[0] is not None), key=lambda k: k[0]):
        out[(None, m, c)] = out[(mo, m, c)]   # 달 순서로 덮어써 가장 최근 달 값이 남는다
    return out


def ratios_fee_note(ratios):
    """fee_ratios 결과 → 토글 옆 수수료율 문구(종합 리포트 — 범위마다 가장 최근 달 비율)."""
    by = {}
    for (mo, m, c), r in ratios.items():
        if mo is None:
            by.setdefault(m, []).append(r)
    return _fee_text(by)


def ratios_have_fee(ratios):
    return any(abs(r - 1) > 1e-9 for r in ratios.values())


def add_gross(rows, ratios):
    """원자 행마다 Gross 광고비(cost_g)를 붙인다 — 그 달 캠페인 → 그 달 매체 → 다른 달 캠페인 → 다른 달 매체 → 1."""
    for r in rows:
        mo, m, c = f"{r['day']:%Y-%m}", r["m"], r.get("c")
        f = ((c is not None and ratios.get((mo, m, c))) or ratios.get((mo, m, None))
             or (c is not None and ratios.get((None, m, c))) or ratios.get((None, m, None)) or 1.0)
        r["cost_g"] = fees.money(r["cost"] * f)


def add_gross_like(rows, ref, ratios):
    """덜 잘게 받은 행(Placement 등 캠페인 차원이 없는 행)의 Gross 광고비 — 본 표 행(ref, add_gross를 거친 행)의
    (달, 매체)별 실효 비율(Σ cost_g ÷ Σ cost)을 써서 두 표의 Gross 합을 맞춘다. 본 표에 그 (달, 매체)가 없으면 add_gross 규칙."""
    acc = {}
    for r in ref:
        s = acc.setdefault((f"{r['day']:%Y-%m}", r["m"]), [0.0, 0.0])
        s[0] += r["cost_g"]
        s[1] += r["cost"]
    eff = {k: g / n for k, (g, n) in acc.items() if n}
    add_gross(rows, ratios)
    for r in rows:
        f = eff.get((f"{r['day']:%Y-%m}", r["m"]))
        if f:
            r["cost_g"] = fees.money(r["cost"] * f)


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
        if nxt == "m":   # 매체 범위가 없는 매체(캠페인 목표만 있는 매체)는 그 포함 캠페인들의 수수료
            have = {x["scope"]["m"] for x in budgets if x["mo"] == b["mo"] and set(x["scope"]) == {"m"} and x["v"].get("cost")}
            for x in budgets:
                xs = x["scope"]
                if (x["mo"] == b["mo"] and set(xs) == {"m", "c"} and xs["m"] not in have and x.get("inc") != "N"
                        and x["v"].get("cost") and x["v"].get("cost_net")):
                    fee += x["v"]["cost"] - x["v"]["cost_net"]
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


def view(envs, texts, tp):
    """(기본 보기, 서버 기준, 수수료 표). 기본 보기 None = 수수료 없음(토글 없이 원값).
    서버가 fee_basis를 주면 그 기준이 기본이고 수수료 표에 무엇이 있을 때 두 보기를 만든다. 옛 서버면 기준 달 예산에 수수료가 있을 때(tp) 기본 Gross."""
    served = fees.served_basis(envs, texts)
    if served:
        table = fees.fee_table(envs, texts)
        return (served if table else None), served, table
    return ("gross" if report_has_fee(tp) else None), None, {}


def bundle(default, served, table, sections, alt, summary_name, tp, months):
    """Weekly·Monthly report["basis"] — 두 경로 중 서버 응답에 맞는 것. months = 보고서가 다루는 달("YYYY-MM")."""
    note = f"* {summary_name}는 {fees.LABEL[default]} 기준 숫자로 작성되었습니다."
    if served:
        return fees.served_bundle(served, sections, alt, note, fees.served_fee_note(table, served, months))
    return basis_bundle(sections, alt, note, fee_note(tp))


def digest_note(default, served, table):
    return fees.served_digest_note(served, bool(table)) if served else BASIS_NOTE[bool(default)]

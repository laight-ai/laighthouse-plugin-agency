"""광고비·예산 Gross / Net — 빌더가 공유하는 규칙. 서버가 수수료 방식을 알려 준다(get_ad_performance 봉투의 fee_basis·fees,
목표 원문의 `fee_basis:` 줄·셋째 표 `| media | fee_mode | rate |`).

광고비 실적·예산·단가 목표는 모두 브랜드 설정 방식(fee_basis — net·gross)으로 온다. 그 방식이 기본 보기이고, 다른 보기는
행의 매체·달 수수료로 환산한다(마크업 Gross = Net × (1 + r/100), 커미션 Gross = Net ÷ (1 − r/100), 그 매체·달의 수수료가
없으면 수수료 없음). 수수료는 달마다 같다거나 예산이 없는 매체는 0%라는 근사는 쓰지 않는다.
fee_basis가 없는 옛 응답의 규칙은 fees_legacy.py.
"""
import re
from datetime import timedelta

from report_kit import label, period_of

TOGGLE_LABEL = "광고비·예산 기준"
_COST_PER_RE = re.compile(r"^cp[a-z]{1,2}$", re.I)   # CPM·CPC·CPV·CPA… — 광고비 ÷ 무엇 → Gross 비율만큼 커진다
_PER_COST = {"roas"}                                  # 무엇 ÷ 광고비 → Gross 비율만큼 작아진다


def nk(s):
    return str(s).strip().lower()


def money(v):
    """환산 금액 — 소수 둘째 자리까지(원 단위 통화는 정수가 된다)."""
    v = round(v, 2)
    return int(v) if float(v).is_integer() else v


def fmt_num(v):
    return str(int(v)) if float(v).is_integer() else f"{v:.4f}".rstrip("0").rstrip(".")


def scalers(metrics, metric_keys):
    """지표마다 Gross 환산 방향: +1(×비율) · -1(÷비율). 환산하지 않는 지표는 빠진다."""
    cost_like = {metric_keys.get(k) for k in ("cost", "cpm", "cpc", "cpv") if metric_keys.get(k)}
    out = {}
    for x in metrics:
        if x in cost_like or _COST_PER_RE.match(x):
            out[x] = 1
        elif x.lower() in _PER_COST:
            out[x] = -1
    return out


def eff_factors(pairs, metric_keys):
    """[(환산 전 봉투, 같은 순서의 환산한 봉투, 기간 키 함수)] → 실효 비율 {(기간 또는 None, 매체 또는 None): Σ 환산 ÷ Σ 환산 전}
    (서버 방식 → 다른 보기). None 기간 = 모든 기간 합, None 매체 = 모든 매체 합. 덜 잘게 받은 응답을 같은 숫자로
    환산할 때 convert_envelope(eff=...)(옛 응답은 fees_legacy.gross_envelope)에 넘긴다."""
    cost = metric_keys.get("cost")
    acc = {}
    for net, gross, key in pairs:
        if not net or not gross:
            continue
        for a, b in zip(net.get("rows") or [], gross.get("rows") or []):
            v, w = a.get(cost), b.get(cost)
            if not isinstance(v, (int, float)) or not isinstance(w, (int, float)):
                continue
            m = nk(label(a.get("media"))) if a.get("media") is not None else None
            p = key(a)
            for k in {(p, m), (None, m), (p, None), (None, None)}:
                s = acc.setdefault(k, [0.0, 0.0])
                s[0] += w
                s[1] += v
    return {k: g / n for k, (g, n) in acc.items() if n}


def net_only(net, gross):
    """Net 섹션 묶음에서 Gross와 같은 섹션을 뺀다 — 화면은 빠진 섹션을 기본(Gross) 묶음에서 가져온다."""
    return {k: v for k, v in net.items() if v != gross.get(k)}


LABEL = {"gross": "Gross", "net": "Net"}
MODE_LABEL = {"markup": "마크업", "commission": "커미션"}
_BASIS_LINE = re.compile(r"^fee_basis:\s*(\S+)\s*$", re.M)
_MONTH_LINE = re.compile(r"^month:\s*(\d{4}-\d{2})", re.M)
_TABLE_TEXT = re.compile(r"^\|\s*(metric|media)\s*\|", re.M)   # 표가 있는 목표 원문(목표 없음 한 줄이 아니다)
_COST_GOALS = ("cost", "cpm", "cpc", "cpv")   # 목표 원문에서 광고비 기준을 따르는 목표(빌더가 읽는 것만)


def other(basis):
    return "net" if basis == "gross" else "gross"


def _basis_of(v, where):
    v = str(v).strip().lower()
    if v not in LABEL:
        raise SystemExit(f"{where}의 fee_basis가 net·gross가 아니다: {v}")
    return v


def served_basis(envs=(), texts=()):
    """응답의 광고비 기준 — "net"·"gross"(서버가 알려 준 브랜드 설정) 또는 None(옛 서버: fees_legacy).
    봉투는 fee_basis 키, 목표 원문은 `fee_basis:` 줄을 본다(표가 없는 원문 — 목표 없음 한 줄 — 은 보지 않는다).
    응답마다 다르면(fee_basis가 있는 응답과 없는 응답, 또는 net·gross가 섞였다) 멈춘다 — 기준이 다른 금액은 함께 쓸 수 없다."""
    seen = set()
    for e in envs:
        if e:
            seen.add(_basis_of(e["fee_basis"], "get_ad_performance 응답") if e.get("fee_basis") else None)
    for t in texts:
        if t and _TABLE_TEXT.search(t):
            m = _BASIS_LINE.search(t)
            seen.add(_basis_of(m.group(1), "get_target_progress_v2 응답") if m else None)
    if len(seen) > 1:
        raise SystemExit("응답마다 광고비 수수료 기준이 다르다(fee_basis가 있는 응답과 없는 응답, 또는 net·gross가 섞였다) — "
                         "서버가 바뀌는 중이면 끝난 뒤 모든 응답을 다시 받는다.")
    return next(iter(seen), None)


def _cells(ln):
    s = ln.strip()
    return [c.strip() for c in s.strip("|").split("|")] if s.startswith("|") else None


def _fee_rows(text):
    """목표 원문의 셋째 표(| media | fee_mode | rate |) → [(매체, fee_mode, rate)]."""
    out, on = [], False
    for ln in (text or "").splitlines():
        cells = _cells(ln)
        if cells is None:
            on = False
            continue
        if [c.lower() for c in cells] == ["media", "fee_mode", "rate"]:
            on = True
        elif on and len(cells) == 3 and not set(cells[0]) <= {"-", ":", " "}:
            out.append((cells[0], cells[1], cells[2]))
    return out


def fee_table(envs=(), texts=()):
    """봉투의 fees와 목표 원문의 셋째 표(그 원문 month 줄의 달) → {(매체 소문자, "YYYY-MM"): {"media": 표기, "mode", "rate"}}.
    매체는 행(셋째 표는 둘째 표) 표기 그대로 오므로 대소문자·앞뒤 공백만 무시하고 맞춘다. 표에 없는 매체·달 = 수수료 없음."""
    out = {}

    def put(media, month, mode, rate):
        mode = str(mode).strip().lower()
        if mode not in MODE_LABEL:
            raise SystemExit(f"수수료 방식(fee_mode)이 markup·commission이 아니다: {media} {month} {mode}")
        try:
            r = float(str(rate).replace(",", ""))
        except ValueError:
            raise SystemExit(f"수수료율(rate)이 숫자가 아니다: {media} {month} {rate}") from None
        if mode == "commission" and r >= 100:
            raise SystemExit(f"커미션 수수료율이 100% 이상이다: {media} {month} {r:g}")
        new = {"media": str(media).strip(), "mode": mode, "rate": r}
        old = out.setdefault((nk(media), str(month)[:7]), new)
        if (old["mode"], old["rate"]) != (mode, r):
            raise SystemExit(f"수수료가 응답마다 다르다: {old['media']} {month} — {MODE_LABEL[old['mode']]} {old['rate']:g}% / "
                             f"{MODE_LABEL[mode]} {r:g}%")

    for e in envs:
        for f in (e or {}).get("fees") or []:
            if f.get("media") is not None and f.get("month"):
                put(f["media"], f["month"], f.get("fee_mode"), f.get("rate"))
    for t in texts:
        m = _MONTH_LINE.search(t or "")
        if m:
            for media, mode, rate in _fee_rows(t):
                put(media, m.group(1), mode, rate)
    return out


def _factor(fee, served, to):
    """서버 방식(served) 금액을 보기(to)로 읽는 배수 — 수수료가 없거나 같은 방식이면 1.
    마크업: Gross = Net × (1 + r/100), 커미션: Gross = Net ÷ (1 − r/100)."""
    if not fee or served == to:
        return 1.0
    r = fee["rate"] / 100
    if fee["mode"] == "markup":
        return 1 + r if to == "gross" else 1 / (1 + r)
    return 1 / (1 - r) if to == "gross" else 1 - r


def window_months(a, b):
    """날짜 범위 [a, b] → {"YYYY-MM": 그 달에 든 일수} — total grain 봉투(달이 없는 행)를 환산할 때 convert_envelope(window=...)에 넘긴다."""
    out, d = {}, a
    while d <= b:
        out[f"{d:%Y-%m}"] = out.get(f"{d:%Y-%m}", 0) + 1
        d += timedelta(days=1)
    return out


def _row_factor(r, has_media, table, served, to, eff, key, window):
    """행 하나의 배수(None = 알 수 없다). 규칙은 convert_envelope."""
    p = period_of(r)
    month = p[:7] if p != "total" else None
    if has_media:
        m = nk(label(r.get("media")))
        if month:
            return _factor(table.get((m, month)), served, to)
        fs = {mo: _factor(table.get((m, mo)), served, to) for mo in window or {}}
        if len(set(fs.values())) == 1:
            return next(iter(fs.values()))
        f = eff.get((key(r), m))
        if f is None and fs:
            f = sum(fs[mo] * window[mo] for mo in fs) / sum(window.values())
        return f
    f = eff.get((key(r), None))
    if f is None and month and not any(mo == month for _, mo in table):
        f = 1.0
    return f


def convert_envelope(env, table, served, to, metric_keys, eff=None, eff_key=None, window=None):
    """서버 방식(served) 봉투 → 보기(to) 봉투. 광고비·CPM·CPC·CPV 등(광고비 ÷ 무엇)은 ×배수, ROAS(무엇 ÷ 광고비)는 ÷배수.
    행 순서는 그대로다. 배수 = 행의 매체 · 달(date·month) 수수료(fee_table에 없으면 수수료 없음 = 1).
    - 달이 없는 행(total grain): window(봉투 기간이 걸친 {달: 일수})의 수수료가 모두 같으면 그 배수, 다르면 eff를 (기간, 매체)로
      찾고, 없으면 window 일수로 가중 평균한다.
    - 매체 차원이 없는 봉투의 행: eff(더 잘게 받은 응답을 환산해 eff_factors로 구한 실효 배수)를 (기간, None)으로 찾는다.
      그 달에 수수료가 하나도 없으면 1. 찾지 못하면 환산할 지표를 비운다(None — 틀린 숫자 대신 빈칸). 0은 그대로 0이다.
    eff_key(행) = eff를 찾을 기간 키(기본 period_of)."""
    if not env or served == to:
        return env
    eff = eff or {}
    key = eff_key or period_of
    sc = scalers(env.get("metrics") or [], metric_keys)
    src = env.get("rows") or []
    has_media = "media" in (env.get("dimensions") or []) or any("media" in r for r in src)
    rows = []
    for r in src:
        f = _row_factor(r, has_media, table, served, to, eff, key, window)
        out = dict(r)
        for x, d in sc.items():
            v = r.get(x)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
                out[x] = None if f is None else v * f if d > 0 else v / f
        rows.append(out)
    return dict(env, rows=rows, fee_basis=to)


def convert_target_text(text, table, served, to):
    """목표 원문(서버 방식 served) → 보기(to)로 바꾼 원문(다른 파서를 그대로 쓴다). 빌더가 읽는 target 열의 cost·cpm·cpc·cpv만 바꾼다.
    둘째 표: ×배수 — 행 매체의 그 달(month 줄) 수수료(캠페인 행도 그 매체 수수료).
    첫째 표: cost를 둘째 표 매체 행 cost의 환산 합 ÷ 원값 합만큼(서버의 첫째 표 cost = 매체 예산 합). fee_basis 줄도 to로 바꾼다."""
    if not text or served == to or not _TABLE_TEXT.search(text):
        return text
    m = _MONTH_LINE.search(text)
    month = m.group(1) if m else ""
    lines, old, new = [], 0.0, 0.0
    for ln in text.splitlines():
        cells = _cells(ln)
        if cells and len(cells) >= 5 and cells[3] in _COST_GOALS:
            try:
                v = float(cells[4].replace(",", ""))
            except ValueError:
                v = None
            if v is not None:
                nv = v * _factor(table.get((nk(cells[0]), month)), served, to)
                if cells[3] == "cost" and cells[1] == "-":
                    old, new = old + v, new + nv
                cells[4] = fmt_num(nv)
                ln = "| " + " | ".join(cells) + " |"
        elif _BASIS_LINE.match(ln.strip()):
            ln = f"fee_basis: {to}"
        lines.append(ln)
    if old:
        for i, ln in enumerate(lines):
            cells = _cells(ln)
            if cells and len(cells) == 4 and cells[0] == "cost":
                try:
                    cells[1] = fmt_num(float(cells[1].replace(",", "")) * new / old)
                except ValueError:
                    continue
                lines[i] = "| " + " | ".join(cells) + " |"
    return "\n".join(lines)


def convert_budgets(budgets, table, served, to, derive=None):
    """종합 리포트 예산 목록(parse_budget — 서버 방식 served) → 보기(to)의 예산 목록. cost·cpm·cpc·cpv 목표는 ×배수 — 범위에 매체가
    있으면 그 매체의 그 달 수수료(캠페인 등 아래 범위도 그 매체 수수료), 없으면(첫째 표의 전체 합계 등) 한 단계 아래 매체 범위 cost의
    환산 합 ÷ 원값 합(서버의 첫째 표 cost = 매체 예산 합). derive(v)를 주면 서버가 준 목표(b["srv"])만 남기고 파생 목표
    (노출 = 예산/CPM 등)를 그 보기의 예산으로 다시 계산한다."""
    if served == to:
        return budgets

    def factor(b):
        sc = b["scope"]
        if "m" in sc:
            return _factor(table.get((nk(sc["m"]), b["mo"])), served, to)
        kids = [x for x in budgets if x["mo"] == b["mo"] and set(x["scope"]) == set(sc) | {"m"}
                and all(x["scope"][k] == sc[k] for k in sc) and x["v"].get("cost")]
        old = sum(x["v"]["cost"] for x in kids)
        return sum(x["v"]["cost"] * factor(x) for x in kids) / old if old else 1.0

    out = []
    for b in budgets:
        f = factor(b)
        v = {k: x for k, x in b["v"].items() if k in b["srv"]} if derive and "srv" in b else dict(b["v"])
        for k in ("cost", "cpm", "cpc", "cpv"):
            if isinstance(v.get(k), (int, float)):
                v[k] = money(v[k] * f)
        if derive:
            derive(v)
        out.append(dict(b, v=v))
    return out


def add_cost_views(rows, table, served):
    """종합 리포트 원자 행(cost = 서버 방식 served) → cost = Net, cost_g = Gross(행 매체 · 그 날 달의 수수료, 소수 둘째 자리).
    표·엑셀·Comment는 이 두 열을 옛 응답(fees_legacy.add_gross)과 같은 뜻으로 쓴다."""
    for r in rows:
        fee = table.get((nk(r["m"]), f"{r['day']:%Y-%m}"))
        if served == "net":
            r["cost_g"] = money(r["cost"] * _factor(fee, "net", "gross"))
        else:
            r["cost_g"] = r["cost"]
            r["cost"] = money(r["cost"] * _factor(fee, "gross", "net"))


def served_ui(served, note=""):
    """토글 문구 — 기본 보기 = 브랜드 설정(served, 서버 값 그대로), 다른 보기 = 매체·달별 수수료로 환산한 값."""
    how = {served: "브랜드 설정 기준(서버 값 그대로)", other(served): "매체·달별 수수료로 환산"}
    return {"label": TOGGLE_LABEL, "default": served, **({"note": note} if note else {}), "options": [
        {"key": "gross", "label": "Gross", "title": f"광고비·예산 = Gross(매체 집행액 + 수수료) — {how['gross']}"},
        {"key": "net", "label": "Net", "title": f"광고비·예산 = Net(매체 집행액) — {how['net']}"}]}


def served_bundle(served, sections, alt, summary_note, note=""):
    """Weekly·Monthly report["basis"] — 기본 보기(served) 섹션은 report.sections, 다른 보기는 기본과 달라진 섹션만(alt에서),
    summary_note = 다른 보기에서 s2(모델 요약) 아래 각주, note = 토글 옆 문구(served_fee_note)."""
    o = other(served)
    return dict(served_ui(served, note), sections={o: net_only(alt, sections)}, notes={o: {"s2": summary_note}})


def _next_month(mo):
    y, m = int(mo[:4]), int(mo[5:7])
    return f"{y + (m == 12):04d}-{m % 12 + 1:02d}"


def _mon(mo, years):
    return (f"{mo[2:4]}년 " if years else "") + f"{int(mo[5:7])}월"


def _span(a, b, years):
    if a == b:
        return _mon(a, years)
    return f"{_mon(a, years)[:-1]}~{int(b[5:7])}월" if a[:4] == b[:4] else f"{_mon(a, years)}~{_mon(b, years)}"


def served_fee_note(table, served, months):
    """토글 옆 문구 — '브랜드 기준 Net · 수수료 Meta 마크업 15% · Google(9월 커미션 10%, 10~11월 커미션 12%)'.
    months("YYYY-MM" 목록 — 보고서가 다루는 달)에 든 수수료만 적는다. 매체 표기는 처음 나온 표기. 한 수수료가 months 전체에 이어지면 달 없이,
    아니면 같은 수수료가 이어지는 달을 묶어 달과 함께 적는다(적히지 않은 달 = 그 달 수수료 없음)."""
    names, by = {}, {}
    for (m, mo), f in table.items():
        if mo in months:
            names.setdefault(m, f["media"])
            by.setdefault(m, []).append((mo, f"{MODE_LABEL[f['mode']]} {f['rate']:g}%"))
    years = len({mo[:4] for v in by.values() for mo, _ in v}) > 1
    parts = []
    for m, name in names.items():
        runs = []
        for mo, t in sorted(by[m]):
            if runs and runs[-1][2] == t and _next_month(runs[-1][1]) == mo:
                runs[-1][1] = mo
            else:
                runs.append([mo, mo, t])
        if len(runs) == 1 and len(by[m]) == len(set(months)):
            parts.append(f"{name} {runs[0][2]}")
        else:
            parts.append(f"{name}(" + ", ".join(f"{_span(a, b, years)} {t}" for a, b, t in runs) + ")")
    return f"브랜드 기준 {LABEL[served]}" + (" · 수수료 " + " · ".join(parts) if parts else "")


def served_digest_note(served, fee):
    """digest의 '광고비·예산 기준' — 요약 숫자가 어느 기준인지."""
    b = LABEL[served]
    return f"{b}(브랜드 설정 기준 — 광고비·예산·CPM·CPC·CPV 모두 {b})" if fee else f"{b}(수수료 없음 — Gross = Net)"

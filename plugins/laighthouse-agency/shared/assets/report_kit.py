"""보고서 공용 킷 — 빌더가 공유하는 계산 부품(Copilot 스킬과 같은 원본 — Copilot 전용 부품(stash)은 이 플러그인에서 쓰지 않는다).

각 스킬의 `assets/build_report.py`·`assets/discover.py`·`assets/rank_creatives.py`가 import 한다(모델이
직접 import 하지 않는다). 찾는 위치: `<스킬>/shared/assets`(zip 번들) → `<src>/shared/assets`(개발 트리).

이 킷은 HTML을 만들지 않는다 — 섹션별 **뷰 모델(JSON)**만 계산하고, 그리기는 `report_kit.js`, 모양은
`report_kit.css`가 맡는다. 매출·Organic·모드 분기는 없다(매출 없는 브랜드 전제).

부품:
- `resolve_roles`        디스커버리 봉투 → 매체·상품 목록, 고정 7 역할 키, 통화
- `load_envelopes`       봉투 원문(문자열/dict/리스트/{"json": ...}/{"json_files": ...}) → dict 리스트
- `index_rows`           봉투 → {기간: {차원값 튜플: {지표: 값}}}
- `delta`                증감 텍스트·방향 (단위 % 는 %p)
- `additive_metrics`     총계 = 그룹 합인 지표 집합(비중 % 표시 대상)
- `parse_target_progress` get_target_progress_v2 원문 → 예산 목표
- `metric_meta`          봉투 지표 → [{"key","label","unit","additive"}]
- `fmt_metric`, `js_json`, `inline_assets`, `chart_js`, `read_payload`
"""
import json
import os
import re

KIT_DIR = os.path.dirname(os.path.abspath(__file__))

PRODUCT_DIM = "상품"
UNSET_LABEL = "(미지정)"

# 상단 KPI 카드의 고정 7 역할 (순서 = 카드 순서)
ROLES = ("cost", "impression", "click", "ctr", "views", "cpm", "cpv")
ROLE_LABELS = {"cost": "광고비", "impression": "노출", "click": "클릭", "ctr": "CTR",
               "views": "조회수", "cpm": "CPM", "cpv": "CPV", "vtr": "VTR"}
# 있으면 쓰는 역할 — 없어도 missing으로 묻지 않는다
OPTIONAL_ROLES = ("vtr",)
# daily·weekly 상단 KPI 카드의 기본 순서(VTR은 서빙될 때만)
KPI_ROLES = ("cost", "impression", "click", "ctr", "vtr", "views", "cpm", "cpv")
# 역할별 후보 (대소문자 무시, 정확 일치만).
ROLE_CANDIDATES = {
    "cost": ["광고비", "cost", "spend", "spending"],
    "impression": ["노출", "impression", "impressions", "imps"],
    "click": ["클릭", "click", "clicks"],
    "ctr": ["CTR"],
    "views": ["조회수", "조회", "views", "video_views", "view"],
    "cpm": ["CPM"],
    "cpv": ["CPV"],
    "vtr": ["VTR"],
}
RATIO_ROLES = ("ctr", "cpm", "cpv")
MONEY_ROLES = ("cost", "cpm", "cpv")

CURRENCY_UNITS = {"₩", "$", "€", "£", "¥", "원", "KRW", "USD", "JPY", "EUR"}
ZERO_DECIMAL_CURRENCIES = {"₩", "¥", "원", "KRW", "JPY"}
SUFFIX_CURRENCIES = {"원", "KRW", "USD", "JPY", "EUR"}


# ── 입력 ─────────────────────────────────────────────────────────────────────


def read_payload(argv=None, stdin=None):
    """asset 스크립트 입력 JSON — 인자로 파일 경로를 주면 그 파일, 없으면 stdin."""
    import sys as _sys
    argv = _sys.argv if argv is None else argv
    if len(argv) > 1 and argv[1] not in ("-", ""):
        with open(os.path.expanduser(argv[1]), encoding="utf-8-sig") as f:
            payload = json.load(f)
    else:
        payload = json.load(stdin or _sys.stdin)
    return merge_base(payload)


def merge_base(payload):
    """{"base": <prepare.py가 만든 build.json 경로>, ...} → base 내용에 입력 키를 덮어쓴 dict(입력 키가 우선)."""
    if not isinstance(payload, dict) or not payload.get("base"):
        return payload
    with open(os.path.expanduser(payload["base"]), encoding="utf-8-sig") as f:
        merged = json.load(f)
    merged.update({k: v for k, v in payload.items() if k != "base"})
    return merged


def _unwrap_tool_result(obj):
    """MCP CallToolResult 래퍼({"content": [...], "structuredContent": ..., "isError": ...}) → 봉투 dict.
    Copilot은 큰 도구 응답을 /app/data/*-copilot-tool-output-*.txt 에 이 래퍼 그대로 저장한다."""
    if obj.get("isError"):
        texts = [c.get("text", "") for c in obj.get("content") or [] if isinstance(c, dict)]
        raise SystemExit("MCP 도구 오류: " + " ".join(texts)[:500])
    sc = obj.get("structuredContent")
    if isinstance(sc, dict):
        sc = sc.get("result", sc) if "rows" not in sc else sc
        if isinstance(sc, dict) and "rows" in sc:
            return sc
    for c in obj.get("content") or []:
        text = c.get("text") if isinstance(c, dict) else None
        if text and "{" in text:
            # 앞에 붙는 "Title: …" / "ReferenceId: …" 머리말을 떼고 첫 줄 시작 '{'부터 읽는다
            i = text.find("\n{")
            body = text[i + 1:] if i >= 0 else text[text.find("{"):]
            env = json.loads(body)
            if isinstance(env, dict) and "rows" in env:
                return env
    raise SystemExit("도구 응답 래퍼에서 get_ad_performance 봉투를 찾지 못했다")


def load_envelopes(obj):
    """봉투 원문 문자열 / 봉투 dict / 그 리스트 / {"json": ..., "json_files": [...]} → 봉투 dict 리스트.
    json_files 에는 Copilot이 저장한 도구 응답 파일(/app/data/…)을 그대로 넣어도 된다(래퍼를 벗긴다)."""
    if obj is None:
        return []
    if isinstance(obj, str):
        return load_envelopes(json.loads(obj))
    if isinstance(obj, dict) and "rows" not in obj and ("content" in obj or "structuredContent" in obj):
        return [_unwrap_tool_result(obj)]
    if isinstance(obj, list):
        out = []
        for item in obj:
            out.extend(load_envelopes(item))
        return out
    if isinstance(obj, dict) and "rows" not in obj and ("json" in obj or "json_files" in obj):
        out = []
        for path in obj.get("json_files") or []:
            with open(os.path.expanduser(path), encoding="utf-8-sig") as f:
                out.extend(load_envelopes(json.load(f)))
        out.extend(load_envelopes(obj.get("json")))
        return out
    if isinstance(obj, dict):
        return [obj]
    raise SystemExit(f"봉투 형식이 아니다: {type(obj).__name__}")


def section_envelope(section):
    """빌더 섹션 입력 → 봉투 하나. 섹션이 dict면 그 안의 "json"(원문)·"json_files"(파일 경로)만 읽는다 — 다른 키
    (target_progress·thumbnails 등)는 무시. 문자열·리스트면 그대로 원문으로 본다. 입력이 없으면 None."""
    if not section:
        return None
    if isinstance(section, dict) and "rows" not in section:
        section = {k: section[k] for k in ("json", "json_files") if section.get(k)}
        if not section:
            return None
    return merged_envelope(section)


def first_envelope(obj):
    envs = load_envelopes(obj)
    return envs[0] if envs else None


# ── 디스커버리 ────────────────────────────────────────────────────────────────


def _resolve_role(role, metrics):
    """대소문자 무시 정확 일치만. 접두 일치는 쓰지 않는다(cost_per_view → cost 같은 오탐) — 못 찾으면 missing."""
    lower = {m.lower(): m for m in metrics}
    for cand in ROLE_CANDIDATES[role]:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def _label(value):
    return UNSET_LABEL if value is None or value == "" else str(value)


def resolve_roles(envelope):
    """디스커버리 봉투(total, group_by ["media","상품"], metrics 생략) → 실행 설정."""
    metrics = list(envelope.get("metrics") or [])
    media_list, products = [], {}
    for r in envelope.get("rows") or []:
        m = _label(r.get("media"))
        if m not in media_list:
            media_list.append(m)
            products[m] = []
        p = _label(r.get(PRODUCT_DIM))
        if PRODUCT_DIM in r and p not in products[m]:
            products[m].append(p)
    keys = {}
    for role in ROLES + OPTIONAL_ROLES:
        k = _resolve_role(role, metrics)
        if k:
            keys[role] = k
    units = envelope.get("metric_units") or {}
    cur = units.get(keys.get("cost")) if keys.get("cost") else None
    return {"media_list": media_list, "products": products, "metric_keys": keys,
            "metric_names": metrics, "metric_units": units,
            "currency": cur if cur in CURRENCY_UNITS else "₩",
            "missing": [r for r in ROLES if r not in keys]}


def discover_main(stdin, stdout):
    payload = read_payload(stdin=stdin)
    env = first_envelope(payload) or {}
    json.dump(resolve_roles(env), stdout, ensure_ascii=False)


# ── 봉투 인덱싱 ──────────────────────────────────────────────────────────────


def period_of(row):
    return str(row.get("date") or row.get("month") or "total")


_RATIO_NAMES = {c.lower() for r in RATIO_ROLES for c in ROLE_CANDIDATES[r]}


def _is_ratio(metric, unit):
    return unit == "%" or metric.lower() in _RATIO_NAMES


def index_rows(env, dims):
    """{기간: {차원값 튜플: {지표: 값}}}. 같은 키가 중복되면(예: 상품 null과 ""가 모두 (미지정)) 가산 지표만
    더하고, 비율 지표(단위 % 또는 CTR·CPM·CPV)는 합칠 수 없으므로 None으로 둔다."""
    out = {}
    if not env:
        return out
    metrics = env.get("metrics") or []
    units = env.get("metric_units") or {}
    for row in env.get("rows") or []:
        key = tuple(_label(row.get(d)) for d in dims)
        per = out.setdefault(period_of(row), {})
        dup = key in per
        bucket = per.setdefault(key, {})
        for m in metrics:
            v = row.get(m)
            if dup and _is_ratio(m, units.get(m)):
                bucket[m] = None
                continue
            if not isinstance(v, (int, float)):
                continue
            prev = bucket.get(m)
            bucket[m] = v if m not in bucket else (prev + v if isinstance(prev, (int, float)) else None)
    return out


def metrics_units(*envs):
    metrics, units = [], {}
    for env in envs:
        if not env:
            continue
        for m in env.get("metrics") or []:
            if m not in metrics:
                metrics.append(m)
        for k, v in (env.get("metric_units") or {}).items():
            if v is not None or k not in units:
                units[k] = v
    return metrics, units


# ── 계산 ─────────────────────────────────────────────────────────────────────


def delta_value(cur, base, unit):
    """증감 숫자(단위 % 는 %p 차, 그 외 변화율 %). 비교 불가면 None — 화면에서 임계치로 다시 칠할 때 쓴다."""
    if not isinstance(cur, (int, float)) or not isinstance(base, (int, float)):
        return None
    if unit == "%":
        return cur - base
    return None if base == 0 else (cur / base - 1) * 100


def delta(cur, base, unit):
    """증감 텍스트와 방향. 단위 '%'는 %p 차이, 그 외는 변화율 %. 비교 불가면 '-'."""
    if not isinstance(cur, (int, float)) or not isinstance(base, (int, float)):
        return {"text": "-", "dir": "flat"}
    if unit == "%":
        x, dec, suf = cur - base, 2, "%p"
    else:
        if base == 0:
            return {"text": "-", "dir": "flat"}
        x, dec, suf = (cur / base - 1) * 100, 1, "%"
    if abs(x) < 0.5 * 10 ** -dec:
        return {"text": f"– {0:.{dec}f}{suf}", "dir": "flat"}
    return {"text": f"{'▲' if x > 0 else '▼'} {x:+.{dec}f}{suf}", "dir": "up" if x > 0 else "down"}


def additive_metrics(total_idx, group_idx, metrics, units, metric_keys):
    """총계 값 ≈ 그룹 값 합(0.5% 이내)인 지표 = 가산 지표. 같은 기간이 없어 판정 못 하면
    단위 '%'와 비율 역할(ctr/cpm/cpv)을 비가산으로 본다."""
    ratio_keys = {metric_keys.get(r) for r in RATIO_ROLES if metric_keys.get(r)}
    fallback = {m for m in metrics if units.get(m) != "%" and m not in ratio_keys}
    periods = [p for p in total_idx if p in group_idx]
    if not periods:
        return fallback
    out = set()
    for m in metrics:
        ok, seen = True, False
        for p in periods:
            tot = next(iter(total_idx[p].values()), {}).get(m)
            parts = [v.get(m) for v in group_idx[p].values() if isinstance(v.get(m), (int, float))]
            if not isinstance(tot, (int, float)) or not parts:
                continue
            seen = True
            s = sum(parts)
            if abs(s - tot) > max(abs(tot) * 0.005, 1e-9):
                ok = False
                break
        if ok and seen:
            out.add(m)
    return out


def _target_row(text, metric):
    m = re.search(r"^\|\s*" + metric + r"\s*\|\s*([0-9][0-9.,]*)\s*\|", text or "", re.M)
    v = float(m.group(1).replace(",", "")) if m else None   # 천 단위 콤마도 읽는다
    return v if v else None


def parse_target_progress(text):
    """get_target_progress_v2 원문 → {"cost_target", "cpv_target"}. 표가 아니거나 0이면 None(목표 없음).
    cpv 행은 현재 서버에 없다 — 서버가 CPV 목표를 내려주게 되면 그대로 읽는다."""
    return {"cost_target": _target_row(text, "cost"), "cpv_target": _target_row(text, "cpv")}


# 목표 표의 행 이름(서버) 후보 — 역할마다. 현재 서버는 cost(·revenue·roas)만 준다. 다른 행이 오면 그대로 읽는다.
TARGET_ROW_NAMES = {"cost": ["cost"], "impression": ["impression", "impressions"], "click": ["click", "clicks"],
                    "ctr": ["ctr"], "views": ["views", "view", "video_views"], "cpm": ["cpm"], "cpv": ["cpv"]}


def parse_targets(text, metric_keys):
    """get_target_progress_v2 원문 → {지표 키: 월 목표}. 목표 행이 있는 역할만 담는다(없는 지표는 조용히 빠진다).
    행 이름은 역할 이름(cost·cpv 등) 또는 그 지표 키 그대로."""
    out = {}
    for role, names in TARGET_ROW_NAMES.items():
        k = metric_keys.get(role)
        if not k:
            continue
        for n in names + [k]:
            v = _target_row(text, re.escape(n))
            if v:
                out[k] = v
                break
    return out


def parse_media_targets(text, metric_keys):
    """get_target_progress_v2(media 생략) 원문의 둘째 표 → {매체: {지표 키: 월 목표}}. 매체 행(campaign_name `-`)만 읽는다
    — 매체마다 따로 부르지 않아도 된다. 행 이름 규칙은 parse_targets와 같다."""
    out = {}
    for ln in (text or "").splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[1] != "-" or cells[0] in ("media", "") or set(cells[0]) <= {"-", " "}:
            continue
        try:
            v = float(cells[4].replace(",", ""))
        except ValueError:
            continue
        for role, names in TARGET_ROW_NAMES.items():
            k = metric_keys.get(role)
            if k and v and cells[3] in names + [k]:
                out.setdefault(cells[0], {})[k] = v
    return out


def digest_fmt(metric_keys, units, currency):
    """요약 근거(digest)용 포맷터 — (역할 지표 → 한글 라벨, 값 dict 포맷, 두 값 dict 증감) 세 가지를 돌려준다.
    daily·weekly·monthly 빌더의 digest가 같은 규칙으로 숫자를 쓰게 한다."""
    labels = {metric_keys[r]: ROLE_LABELS[r] for r in ROLES + OPTIONAL_ROLES if metric_keys.get(r)}
    money = {metric_keys.get(r) for r in MONEY_ROLES}
    unit_of = lambda k: units.get(k) or (currency if k in money else None)  # noqa: E731

    def fmt(vals):
        return {labels[k]: fmt_metric(vals.get(k), unit_of(k), currency) for k in labels}

    def change(a, b):
        return {labels[k]: delta(a.get(k), b.get(k), unit_of(k))["text"] for k in labels}

    return labels, fmt, change


DIGEST_TOP = 15   # 요약 근거의 상세 행(매체-상품 등) 상한 — 광고비 상위만. 요약 규칙은 상위 항목만 쓴다
DIGEST_MOVERS = 10   # 캠페인·광고그룹·광고 단위: 광고비 상위 + 광고비 변동(절대액) 상위 각 이만큼
# 요약 근거의 세부 단위(이름, 차원, 상한) — 응답에 없는 차원이 든 단위는 건너뛴다. 광고는 행이 많아 상한을 줄인다
DIGEST_LEVELS = (("매체-캠페인", ["media", "campaign_name"], DIGEST_MOVERS),
                 ("매체-캠페인-광고그룹", ["media", "campaign_name", "ad_group_name"], DIGEST_MOVERS),
                 ("매체-캠페인-광고그룹-광고", ["media", "campaign_name", "ad_group_name", "ad_name"], 5))


def digest_levels(envs, levels, metrics, units, metric_keys, row):
    """요약 근거의 세부 단위 표. envs = [기준 기간 봉투, 비교 기간 봉투, ...](첫째와 둘째를 비교해 변동을 잰다).
    단위(이름, 차원, 상한 top)마다 광고비 상위 top개와 광고비 변동(절대액) 상위 top개를 합쳐 기준 기간 광고비 순으로 돌려준다 —
    작아도 크게 움직인 항목(급등·급감, 신규·중단)이 빠지지 않게 한다. row(이름, 기준 값, *비교 값) → dict.
    → {단위 이름: [row...], "<단위 이름> 생략": "..."}"""
    cost = metric_keys.get("cost")
    dims = set((envs[0] or {}).get("dimensions") or [])
    out = {}
    for name, ds, top in levels:
        if any(d not in dims for d in ds):
            continue
        g = [group_values(e, ds, metrics, units, metric_keys) for e in envs]
        names = set(g[0]) | set(g[1] if len(g) > 1 else {})
        c = lambda k, i: (g[i].get(k) or {}).get(cost) or 0  # noqa: E731
        by_cost = sorted(names, key=lambda k: -c(k, 0))[:top]
        by_move = sorted(names, key=lambda k: -abs(c(k, 0) - (c(k, 1) if len(g) > 1 else 0)))[:top]
        pick = sorted(set(by_cost) | set(by_move), key=lambda k: (-c(k, 0), k))
        out[name] = [row(" / ".join(k), *[x.get(k) or {} for x in g]) for k in pick]
        if len(names) > len(pick):
            out[name + " 생략"] = f"광고비 상위 {top}개 + 광고비 변동 상위 {top}개만 — 나머지 {len(names) - len(pick)}개"
    return out


def metric_meta(metrics, units, currency, additive, metric_keys):
    """봉투 지표 → 표시 메타. 단위가 null인 금액 역할(광고비·CPM·CPV)에는 보고서 통화를 붙인다."""
    money = {metric_keys.get(r) for r in MONEY_ROLES if metric_keys.get(r)}
    labels = {v: ROLE_LABELS[k] for k, v in metric_keys.items() if k in ROLE_LABELS}
    out = []
    for m in metrics:
        u = units.get(m)
        if u is None and m in money:
            u = currency
        out.append({"key": m, "label": labels.get(m, m), "unit": u, "additive": m in additive})
    return out


# ── 포맷 ─────────────────────────────────────────────────────────────────────


def fmt_money(v, currency="₩"):
    if currency in ZERO_DECIMAL_CURRENCIES:
        body = f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}"
    else:
        body = f"{v:,.2f}"
    return f"{body}{currency}" if currency in SUFFIX_CURRENCIES else f"{currency}{body}"


def fmt_metric(v, unit, currency="₩"):
    """metric_units 값으로 표시. 단위를 지표명으로 추측하지 않는다."""
    if not isinstance(v, (int, float)):
        return "-"
    if unit == "%":
        return f"{v:,.2f}%"
    if unit in CURRENCY_UNITS:
        return fmt_money(v, unit)
    body = f"{v:,.0f}" if float(v).is_integer() or abs(v) >= 100 else f"{v:,.2f}"
    return f"{body}{unit}" if unit else body


# ── 출력 ─────────────────────────────────────────────────────────────────────


def js_json(value):
    """<script> 안에 삽입할 JSON — </script> 조기 종료 방지."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _read_first(dirpath, names):
    for n in names:
        p = os.path.join(dirpath, n)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return f.read()
    raise SystemExit(f"{names} 중 어느 것도 {dirpath}에 없다")


def inline_assets(html):
    """__REPORT_KIT_CSS__ / __REPORT_KIT_JS__ 치환. zip 번들은 JS를 report_kit_js.txt로 싣는다."""
    if "__REPORT_KIT_CSS__" in html:
        html = html.replace("__REPORT_KIT_CSS__", _read_first(KIT_DIR, ["report_kit.css"]))
    if "__REPORT_KIT_JS__" in html:
        html = html.replace("__REPORT_KIT_JS__", _read_first(KIT_DIR, ["report_kit_js.txt", "report_kit.js"]))
    return html


def chart_js(assets_dir):
    """Chart.js UMD 본문. zip 번들은 chart.umd.min.txt로 싣는다. 스킬 폴더에 없으면 킷 폴더(플러그인 공용 한 벌)에서 읽는다."""
    names = ["chart.umd.min.txt", "chart.umd.min.js"]
    if not any(os.path.exists(os.path.join(assets_dir, n)) for n in names):
        assets_dir = KIT_DIR
    return _read_first(assets_dir, names)


def load_kit_from(assets_dir):
    """빌더용: <스킬>/shared/assets → <src>/shared/assets 순으로 킷 디렉터리를 찾는다(빌더가 복사해 씀)."""
    for cand in (os.path.join(assets_dir, "..", "shared", "assets"),
                 os.path.join(assets_dir, "..", "..", "..", "shared", "assets")):
        if os.path.exists(os.path.join(cand, "report_kit.py")):
            return os.path.normpath(cand)
    return None


# ── 뷰 모델 (빌더 공용) ───────────────────────────────────────────────────────

# dataviz 분류형 팔레트(기존 킷과 같은 순서) — 매체 순서대로 고정 배정
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                 "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
BAR_COLOR = "#93c5fd"
LINE_COLOR = "#ef4444"
WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def media_colors(names):
    return {n: SERIES_COLORS[i % len(SERIES_COLORS)] for i, n in enumerate(names)}


def ordered_names(idx, pos=0):
    """인덱스에 나타난 순서대로 차원 값(pos번째)을 중복 없이."""
    out = []
    for bucket in idx.values():
        for key in bucket:
            if key[pos] not in out:
                out.append(key[pos])
    return out


def meta_map(meta):
    return {m["key"]: m for m in meta}


def role_key(role, metric_keys, meta):
    """역할 → 지표 키. metric_keys에 없는 선택 역할(VTR — 예전 build.json)은 봉투 지표에서 찾는다."""
    return metric_keys.get(role) or (_resolve_role(role, [m["key"] for m in meta]) if role in OPTIONAL_ROLES else None)


def kpi_cards(cur, bases, metric_keys, meta, roles=ROLES):
    """역할 카드(기본 = 고정 7 역할, roles 순서). cur = {지표: 값}, bases = [(key, label, {지표: 값})]. 카드마다 "key" = 지표 키."""
    mm = meta_map(meta)
    cards = []
    for role in roles:
        k = role_key(role, metric_keys, meta)
        if not k:
            continue
        cards.append(_metric_card(k, ROLE_LABELS[role], cur, bases, (mm.get(k) or {}).get("unit")))
    return cards


def _metric_card(k, label, cur, bases, unit):
    return {"key": k, "label": label, "value": fmt_metric(cur.get(k), unit),
            "deltas": [dict(key=bk, label=bl, x=delta_value(cur.get(k), (bv or {}).get(k), unit), pp=unit == "%",
                            **delta(cur.get(k), (bv or {}).get(k), unit))
                       for bk, bl, bv in bases]}


def kpi_more(cards, cur, bases, meta, store, sub_label=None, default=None):
    """지표를 고를 수 있는 KPI 카드(LHKit.kpiPick). cards = 스킬이 만든 기본 카드(각자 "key" — 지표 키 또는 '__budget' 같은
    이름)는 처음부터 켜 두고, 그 밖의 봉투 지표마다 비교 카드를 덧붙여 메뉴에서 켤 수 있게 한다.
    sub_label이 있으면 덧붙인 카드 아래에 '{sub_label} {첫 비교 기간 값}'을 적는다(전월 등).
    default = 처음 켤 카드 key(순서대로) — 없으면 cards 전부.
    → {"cards", "default": [기본 카드 key], "store"}"""
    have = {c.get("key") for c in cards}
    extra = []
    for m in meta:
        if m["key"] in have:
            continue
        c = _metric_card(m["key"], m["label"], cur, bases, m.get("unit"))
        if sub_label and bases:
            c["sub"] = f"{sub_label} {fmt_metric((bases[0][2] or {}).get(m['key']), m.get('unit'))}"
        extra.append(c)
    out = list(cards) + extra
    have = {c["key"] for c in out}
    return {"cards": out, "default": [k for k in (default or [c["key"] for c in cards]) if k in have], "store": store}


def kpi_pick(cur, bases, metric_keys, meta, store="default"):
    """KPI_ROLES 카드(VTR 포함)를 기본으로, 봉투 지표 전부를 고를 수 있는 KPI 카드(daily)."""
    return kpi_more(kpi_cards(cur, bases, metric_keys, meta, KPI_ROLES), cur, bases, meta, store)


def series_values(idx, periods, key, metrics):
    return {m: [((idx.get(p) or {}).get(key) or {}).get(m) for p in periods] for m in metrics}


def share_legend(cur_by_name, meta, currency):
    """범례 값: 지표별 '값 · 비중%'(비중은 가산 지표만)."""
    out = {}
    for m in meta:
        k = m["key"]
        tot = sum(v.get(k) or 0 for v in cur_by_name.values()) if m["additive"] else None
        for name, vals in cur_by_name.items():
            v = vals.get(k)
            text = fmt_metric(v, m["unit"], currency)
            if tot and isinstance(v, (int, float)):
                text += f" · {v / tot * 100:.1f}%"
            out.setdefault(name, {})[k] = text
    return out


def day_label(d):
    return f"{d.month}/{d.day}"


def kdate(d, weekday=True):
    s = f"{d.year}년 {d.month}월 {d.day}일"
    return s + f" ({WEEKDAY_KO[d.weekday()]})" if weekday else s


_PLACEHOLDER = re.compile(r"__[A-Z0-9]+(?:_[A-Z0-9]+)*__")


def build_html(assets_dir, replacements, report, out, chart_dir=None):
    """템플릿 치환 + 킷 CSS/JS·Chart.js 인라인 + 저장. 반환: (절대경로, 바이트).
    chart_dir: Chart.js가 템플릿과 다른 폴더에 있을 때(샘플 빌드용)."""
    with open(os.path.join(assets_dir, "report-template.html"), encoding="utf-8") as f:
        template = f.read()
    import html as _html
    values = {k: _html.escape(str(v)) for k, v in replacements.items()}
    values["__REPORT_JSON__"] = js_json(report)
    values["__CHART_JS_INLINE__"] = chart_js(chart_dir or assets_dir)
    values["__REPORT_KIT_CSS__"] = _read_first(KIT_DIR, ["report_kit.css"])
    values["__REPORT_KIT_JS__"] = _read_first(KIT_DIR, ["report_kit_js.txt", "report_kit.js"])
    left = set(_PLACEHOLDER.findall(template)) - set(values)
    if left:
        raise SystemExit(f"치환되지 않은 placeholder: {sorted(left)}")
    # 템플릿을 한 번만 훑어 치환한다 — 삽입된 값(데이터·자산) 안의 '__X__'는 다시 치환·검사되지 않는다.
    html = _PLACEHOLDER.sub(lambda m: values.get(m.group(0), m.group(0)), template)
    path = os.path.abspath(os.path.expanduser(out))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path, os.path.getsize(path)


def bullets_of(s2):
    """s2 = {"bullets": [{"head","text","tone"}]} 또는 문자열 리스트 → 불릿 리스트 | None."""
    if not s2:
        return None
    items = s2.get("bullets") if isinstance(s2, dict) else s2
    out = []
    for it in items or []:
        if isinstance(it, str):
            out.append({"text": it, "tone": "neutral"})
        elif it.get("text"):
            out.append({"head": it.get("head"), "text": it["text"], "tone": it.get("tone") or "neutral"})
    return out or None


# ── 소재 랭킹 ────────────────────────────────────────────────────────────────

CREATIVE_DIMS = ["media", PRODUCT_DIM, "ad_id", "ad_name"]
DEFAULT_MIN_SPEND = 1000000


NO_NAME = {"", "-", "(미지정)"}   # 서버가 소재명을 비워 둔 행(쇼핑 검색 등) — 랭킹·상위 5에서 뺀다
CREATIVE_KEY = ["media", PRODUCT_DIM, "ad_name"]   # ad_id가 없는 서버에서 소재를 가르는 키


def creative_rows(env, metric_keys=None):
    """total 봉투 → 소재 행 리스트(원 행 dict, 상품 null은 (미지정)).
    서버에 ad_id가 없으면(캠페인·광고그룹까지 쪼갠 행) 매체·상품·소재명으로 합친다 — 가산 지표 합, CTR·CPM·CPV 재계산."""
    rows = (env or {}).get("rows") or []
    if rows and metric_keys is not None and not any("ad_id" in r for r in rows):
        metrics, units = metrics_units(env)
        g = group_values(env, CREATIVE_KEY, metrics, units, metric_keys)
        return [dict(zip(CREATIVE_KEY, k), **v) for k, v in g.items()]
    out = []
    for r in (env or {}).get("rows") or []:
        row = dict(r)
        row["media"] = _label(r.get("media"))
        row[PRODUCT_DIM] = _label(r.get(PRODUCT_DIM))
        row["ad_name"] = _label(r.get("ad_name"))
        out.append(row)
    return out


def rank_creatives(env, metric_keys, min_spend=DEFAULT_MIN_SPEND):
    """CPV 오름차순 2 · CTR 내림차순 2 (7일 광고비 ≥ min_spend, 동점은 광고비 큰 순), 광고비 상위 5 ad_id.
    하한선을 넘는 소재가 없으면 그 랭킹은 전체 소재로 폴백한다."""
    rows = [r for r in creative_rows(env, metric_keys) if str(r.get("ad_name") or "").strip() not in NO_NAME]   # 이름 없는 행은 소재가 아니다
    cost, cpv, ctr = metric_keys.get("cost"), metric_keys.get("cpv"), metric_keys.get("ctr")
    num = lambda r, k: r.get(k) if isinstance(r.get(k), (int, float)) else None  # noqa: E731
    sp = lambda r: num(r, cost) or 0  # noqa: E731

    def pick(key, asc):
        valid = [r for r in rows if key and num(r, key) is not None and (num(r, key) > 0 or not asc)]
        elig = [r for r in valid if sp(r) >= min_spend]
        pool, fb = (elig, False) if elig else (valid, True)
        pool = sorted(pool, key=lambda r: ((num(r, key) if asc else -num(r, key)), -sp(r)))
        return pool[:2], fb and bool(valid)

    best_cpv, fb_cpv = pick(cpv, True)
    best_ctr, fb_ctr = pick(ctr, False)
    top5_rows = sorted(rows, key=lambda r: -sp(r))[:5]
    by_id = any("ad_id" in r for r in rows)
    top5 = [r.get("ad_id") if by_id else r.get("ad_name") for r in top5_rows]
    return {"cpv": best_cpv, "ctr": best_ctr, "fallback": {"cpv": fb_cpv, "ctr": fb_ctr}, "top5": top5, "rows": rows,
            "top5_rows": top5_rows, "top5_filter": {("ad_id" if by_id else "ad_name"): list(dict.fromkeys(top5))}}


def rank_lookups(ranked):
    out = []
    for g in ("cpv", "ctr"):
        for i, r in enumerate(ranked[g]):
            out.append({"slot": f"{g}{i + 1}", "ad_name": r.get("ad_name"), "ad_id": r.get("ad_id")})
    return out


def merged_envelope(obj):
    """날짜를 쪼개 여러 번 받은 같은 조건의 봉투들 → 행을 이어 붙인 봉투 하나. 없으면 None."""
    envs = load_envelopes(obj)
    if not envs:
        return None
    if len(envs) > 1:
        if any(e.get("time_grain") == "total" or not any(("date" in r or "month" in r) for r in e.get("rows") or [{}])
               for e in envs):
            raise SystemExit("total grain 응답은 나눠 받을 수 없다 — 기간 합계가 조각마다 따로 온다. 한 번에 다시 받는다.")
        seen = set()
        for e in envs:
            for p in {period_of(r) for r in e.get("rows") or []}:
                if p in seen:
                    raise SystemExit(f"분할 응답의 기간이 겹친다({p}) — 겹치지 않게 나눠 다시 받는다.")
            seen |= {period_of(r) for r in e.get("rows") or []}
    out = dict(envs[0])
    metrics, units = metrics_units(*envs)
    out.update(metrics=metrics, metric_units=units, rows=[r for e in envs for r in (e.get("rows") or [])])
    out["row_count"] = len(out["rows"])
    return out


# ── 브랜드 간 합산 (서버 총계가 없는 집계 전용) ─────────────────────────────────


def aggregate(values_list, metrics, units, metric_keys):
    """여러 그룹 값({지표: 값})을 합친다 — 서버가 그 단위 총계를 줄 수 없을 때만(예: 여러 브랜드 합계).
    가산 지표(단위 % 아님·비율 역할 아님)는 더하고, CTR·CPM·CPV는 합친 원자 지표로 다시 계산한다.
    그 밖의 비율 지표(VTR 등)는 계산 근거가 없으므로 None."""
    ratio_keys = {metric_keys.get(r) for r in RATIO_ROLES if metric_keys.get(r)}
    out = {}
    for m in metrics:
        if units.get(m) == "%" or m in ratio_keys:
            continue
        nums = [v.get(m) for v in values_list if isinstance(v.get(m), (int, float))]
        out[m] = sum(nums) if nums else None
    k = metric_keys
    cost, imp, clk, views = (out.get(k.get(r)) for r in ("cost", "impression", "click", "views"))
    if k.get("ctr"):
        out[k["ctr"]] = clk / imp * 100 if imp and clk is not None else None
    if k.get("cpm"):
        out[k["cpm"]] = cost / imp * 1000 if imp and cost is not None else None
    if k.get("cpv"):
        out[k["cpv"]] = cost / views if views and cost is not None else None
    for m in metrics:
        out.setdefault(m, None)
    return out


# ── 계층 표 (매체 → 캠페인 → 광고그룹 → 광고) — Claude/GPT판 build_tree와 같은 규칙 ─────────

LEVEL_DIMS = ["media", "campaign_name", "ad_group_name", "ad_name"]
LEVEL_LABELS = ["매체", "캠페인", "광고그룹", "광고"]


def _level_of(env):
    dims = env.get("dimensions") or []
    present = [d for d in LEVEL_DIMS if d in dims]
    if not present or present != LEVEL_DIMS[:len(present)]:
        return None   # 계층 표 봉투가 아니다(예: 매체-상품) — 무시
    return len(present)


def build_tree(envelopes, base_period, cur_period, meta, metric_keys):
    """레벨별 봉투(같은 두 기간, group_by가 LEVEL_DIMS의 접두 + id 차원)를 treeTable 데이터로 만든다.
    각 레벨 값은 그 레벨 group_by로 서버가 계산한 값 그대로다(비율 지표를 하위 행에서 합산하지 않기 위해 레벨마다
    따로 조회한다). 같은 이름이 중복된 행(드묾)은 가산 지표만 더하고 비율 지표는 비운다.
    반환: {"levels", "metrics": [{key,label,unit}], "cost", "base", "cur", "nodes": [[name, cur[], base[], kids[]], ...]}"""
    base_period, cur_period = str(base_period), str(cur_period)
    keys = [m["key"] for m in meta]
    units = {m["key"]: m["unit"] for m in meta}
    values, depth = {}, 0
    for env in envelopes or []:
        lvl = _level_of(env)
        if not lvl:
            continue
        depth = max(depth, lvl)
        dims = LEVEL_DIMS[:lvl]
        for row in env.get("rows") or []:
            p = period_of(row)
            slot = "cur" if p.startswith(cur_period) else "base" if p.startswith(base_period) else None
            if not slot:
                continue
            path = tuple(_label(row.get(d)) for d in dims)
            bucket = values.setdefault(path, {"cur": {}, "base": {}})[slot]
            for k in keys:
                v = row.get(k)
                if not isinstance(v, (int, float)):
                    continue
                if k in bucket:   # 같은 경로 중복 — 가산 지표만 더하고 비율 지표는 비운다
                    bucket[k] = None if _is_ratio(k, units.get(k)) or bucket[k] is None else bucket[k] + v
                else:
                    bucket[k] = v
    for path in list(values):   # 조상 경로 보장
        for i in range(1, len(path)):
            values.setdefault(path[:i], {"cur": {}, "base": {}})
    cost = metric_keys.get("cost")
    children = {}
    for path in values:
        children.setdefault(path[:-1], []).append(path)

    def sort_key(path):
        v = values[path]["cur"].get(cost) if cost else None
        return (-(v or 0), path[-1])

    def node(path):
        v = values[path]
        return [path[-1], [v["cur"].get(k) for k in keys], [v["base"].get(k) for k in keys],
                [node(c) for c in sorted(children.get(path, []), key=sort_key)]]

    return {"levels": LEVEL_LABELS[:max(depth, 1)], "cost": cost, "base": base_period, "cur": cur_period,
            "metrics": [{"key": m["key"], "label": m["label"], "unit": m["unit"]} for m in meta],
            "nodes": [node(p) for p in sorted(children.get((), []), key=sort_key)]}


# ── Copilot 큰 응답 파일 보관 ─────────────────────────────────────────────────

TOOL_OUTPUT_GLOB = "*copilot-tool-output-*"
# 스킬 폴더는 읽기 전용일 수 있다(2026-10-07 실측) — 쓰기 가능한 첫 위치를 쓴다
STASH_DIR_CANDIDATES = ["/app/workspace/laighthouse-inputs", os.path.join(os.getcwd(), "laighthouse-inputs")]


def writable_stash_dir():
    import tempfile
    for d in STASH_DIR_CANDIDATES + [os.path.join(tempfile.gettempdir(), "laighthouse-inputs")]:
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".probe")
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
            return d
        except OSError:
            continue
    raise SystemExit("쓰기 가능한 작업 폴더를 찾지 못했다")


def stash_tool_outputs(src_dir="/app/data", dst_dir=None):
    """Copilot이 저장한 큰 도구 응답 파일을 작업 폴더로 복사하고 목록을 돌려준다(저장 파일은 곧 지워질 수 있다).
    반환: [{"file", "source", "tenant", "time_grain", "dimensions", "media", "periods", "row_count"}] — 원본 수정 시각 순.
    봉투가 아닌 응답(오류 등)은 "error"만 담는다. 이미 복사한 파일은 다시 복사하지 않는다."""
    import glob
    import shutil
    dst_dir = dst_dir or writable_stash_dir()
    os.makedirs(dst_dir, exist_ok=True)
    out = []
    for src in sorted(glob.glob(os.path.join(src_dir, TOOL_OUTPUT_GLOB)), key=os.path.getmtime):
        dst = os.path.join(dst_dir, os.path.basename(src))
        if not os.path.exists(dst):
            shutil.copyfile(src, dst)
        item = {"file": os.path.abspath(dst), "source": src}
        try:
            env = load_envelopes({"json_files": [dst]})[0]
            rows = env.get("rows") or []
            item.update(tenant=env.get("tenant"), time_grain=env.get("time_grain"), dimensions=env.get("dimensions"),
                        media=sorted({str(r.get("media")) for r in rows if "media" in r}),
                        periods=sorted({period_of(r) for r in rows}), row_count=len(rows))
        except (SystemExit, ValueError, KeyError) as e:
            item["error"] = str(e)[:300]
        out.append(item)
    return out


def stash_main(argv=None):
    import sys as _sys
    argv = _sys.argv[1:] if argv is None else argv
    src = argv[0] if argv else "/app/data"
    dst = argv[1] if len(argv) > 1 else None
    json.dump(stash_tool_outputs(src, dst), _sys.stdout, ensure_ascii=False, indent=1)


# ── 대조 검증: 상위 단위 값 = 하위 단위 합 (옮겨 적기 오류 탐지) ──────────────────

ROLLUP_ROLES = ("cost", "impression", "click", "views")


def check_rollup(parent_env, parent_dims, child_env, group_dims, metric_keys, tol=0.0001):
    """같은 기간의 상위 봉투(parent_dims 단위)와 하위 봉투를 group_dims로 묶어 더한 값을 가산 지표(광고비·노출·클릭·조회수)로
    대조한다. 작은 응답은 모델이 옮겨 적을 수밖에 없어서(Copilot) 틀린 값이 섞일 수 있다 — 파일로 받은 하위 응답과 맞춰 본다.
    반환: 어긋난 항목 [{"period", "key", "metric", "given", "expected"}] (겹치는 기간이 없으면 빈 리스트)."""
    if not parent_env or not child_env:
        return []
    metrics = [metric_keys[r] for r in ROLLUP_ROLES if metric_keys.get(r)]
    p_idx = index_rows(parent_env, parent_dims)
    sums, counts = {}, {}
    for row in child_env.get("rows") or []:
        key = tuple(_label(row.get(d)) for d in group_dims)
        b = sums.setdefault(period_of(row), {}).setdefault(key, {})
        c = counts.setdefault(period_of(row), {})
        c[key] = c.get(key, 0) + 1
        for m in metrics:
            if isinstance(row.get(m), (int, float)):
                b[m] = b.get(m, 0) + row[m]
    errs = []
    for period, groups in p_idx.items():
        if period not in sums:
            continue
        for key, vals in groups.items():
            exp = sums[period].get(key, {})
            for m in metrics:
                g, e = vals.get(m), exp.get(m, 0)
                if not isinstance(g, (int, float)):
                    continue
                # 허용치: 상대 0.01% 또는 하위 행마다 반올림 0.5 + 상위 1
                if abs(g - e) > max(abs(e) * tol, 0.5 * counts[period].get(key, 0) + 1):
                    errs.append({"period": period, "key": list(key), "metric": m, "given": g, "expected": e})
    return errs


def require_rollup(checks):
    """[(이름, 오류 리스트)] → 어긋남이 있으면 무엇이 다른지 적고 멈춘다(틀린 숫자로 보고서를 만들지 않는다)."""
    bad = [(name, e) for name, errs in checks for e in errs]
    if not bad:
        return
    lines = [f"- {name}: {e['period']} {'/'.join(e['key'])} {e['metric']} 입력 {e['given']:,} ≠ 하위 합 {e['expected']:,}"
             for name, e in bad[:20]]
    raise SystemExit("대조 검증 실패 — 옮겨 적은 응답 값이 파일로 받은 하위 단위 합과 다르다. 해당 응답을 원문 그대로 다시 넣거나 "
                     "다시 조회한다(값을 고쳐 맞추지 않는다).\n" + "\n".join(lines))


# ── 피벗 표 (차원 자유 선택) ─────────────────────────────────────────────────

DIM_LABELS = {"media": "매체", PRODUCT_DIM: "상품", "campaign_name": "캠페인", "ad_group_name": "광고그룹", "ad_name": "광고"}
PIVOT_SKIP_DIMS = {"date", "month", "source"}
# 묶은 행에서 다시 계산할 비율 지표: 결과 = 분자 ÷ 분모 × 배수
RECOMPUTE = {"ctr": ("click", "impression", 100), "cpm": ("cost", "impression", 1000), "cpv": ("cost", "views", 1)}
FINE_ORDER = ["media", PRODUCT_DIM, "campaign_name", "ad_group_name", "ad_name"]
SIZE_FALLBACK_DIMS = ("ad_name", "ad_group_name")   # 응답 크기 오류일 때만 이 순서로 뺄 수 있다(pivot-table.md 2절)


def probe_dims(text):
    """차원 확인 응답(group_by ["__list_dimensions__"] 에러 메시지 원문) → 서버가 제공하는 차원 목록. 형식이 아니면 None."""
    m = re.search(r"valid dimensions:\s*\[([^\]]*)\]", text if isinstance(text, str) else "")
    return re.findall(r"'([^']*)'", m.group(1)) if m else None


def fine_dims(valid):
    """제공 차원 → 피벗 차원(FINE_DIMS): date·month·source·*_id를 빼고 media → 상품 → 캠페인 → 광고그룹 → 광고 → 나머지 순."""
    ds = [d for d in valid if d not in PIVOT_SKIP_DIMS and not d.endswith("_id")]
    return sorted(ds, key=lambda d: (FINE_ORDER.index(d) if d in FINE_ORDER else len(FINE_ORDER), ds.index(d)))


def require_dims(probe, envs, name, need=None):
    """차원 확인 결과와 표 봉투를 맞춰 본다 — 서버가 주는 차원을 호출에서 빼먹었으면 멈춘다(매체만으로 조용히 그리지 않는다).
    envs: [(이름, 봉투|None)]. need: 꼭 받아야 할 차원 후보(기본 = FINE_DIMS에서 크기 오류로 뺄 수 있는 광고·광고그룹 제외).
    서버가 제공하지 않는 차원은 요구하지 않는다(없는 차원은 조용히 빠진다). → FINE_DIMS"""
    valid = probe_dims(probe)
    if valid is None:
        raise SystemExit(f"{name}: \"dims\"가 없다 — 차원 확인(group_by [\"__list_dimensions__\"], metrics []) 에러 메시지 "
                         "원문을 그대로 \"dims\"에 넣는다.")
    want = fine_dims(valid)
    need = [d for d in (need if need is not None else [d for d in want if d not in SIZE_FALLBACK_DIMS]) if d in want]
    for label, env in envs:
        got = (env or {}).get("dimensions") or []
        miss = [d for d in need if d not in got]
        if miss:
            raise SystemExit(f"{name}: 서버가 제공하는 차원 {miss}이(가) {label} 응답에 없다 — group_by {want}로 다시 조회해 "
                             "넣는다(응답 크기 오류일 때만 ad_name → ad_group_name 순으로 뺀다).")
    return want


def pivot_data(envs_by_period, meta, metric_keys, totals=None, default_dims=None, labels=None):
    """가장 잘게 받은 봉투들(기간 키 → 봉투) → 선택 표 데이터(열 기반·사전 인코딩, LHKit.pickTable이 묶는다).
    - dims: 봉투 차원 중 date/month/source/*_id 제외, 나타난 순서
    - metrics: meta + additive(총계 = 행 합이면 가산) — totals(기간 키 → {지표: 서버 총계})로 판정, 없으면 meta 값
    - ratio: 묶은 행에서 다시 계산할 비율 지표 {지표: [분자, 분모, 배수]} (CTR·CPM·CPV)
    - 가장 잘게 쪼갠 행(기간마다 원 행 1개)은 화면에서 서버 값을 그대로 쓴다."""
    periods = list(envs_by_period)
    dims = []
    for env in envs_by_period.values():
        for d in (env or {}).get("dimensions") or []:
            if d not in dims and d not in PIVOT_SKIP_DIMS and not d.endswith("_id"):
                dims.append(d)
    keys = [m["key"] for m in meta]
    dic = {d: {} for d in dims}
    codes = {d: [] for d in dims}
    vals = {k: [] for k in keys}
    period = []
    sums = {p: {} for p in periods}
    nrows = {p: 0 for p in periods}
    for pi, p in enumerate(periods):
        for row in (envs_by_period[p] or {}).get("rows") or []:
            for d in dims:
                codes[d].append(dic[d].setdefault(_label(row.get(d)), len(dic[d])))
            period.append(pi)
            nrows[p] += 1
            for k in keys:
                v = row.get(k)
                vals[k].append(v if isinstance(v, (int, float)) else None)
                if isinstance(v, (int, float)):
                    sums[p][k] = sums[p].get(k, 0) + v
    ratio_keys = {metric_keys.get(r) for r in RATIO_ROLES if metric_keys.get(r)}
    out_meta = []
    for m in meta:
        k = m["key"]
        # 판정은 meta의 additive를 **내리기만** 한다(비가산을 가산으로 올리지 않는다) — 총계와 안 맞으면 비가산
        add = bool(m["additive"]) and m["unit"] != "%" and k not in ratio_keys
        if add and totals:
            checks = [(sums[p].get(k), (totals.get(p) or {}).get(k), nrows[p]) for p in periods]
            checks = [(a, b, n) for a, b, n in checks if isinstance(a, (int, float)) and isinstance(b, (int, float))]
            add = all(abs(a - b) <= max(abs(b) * 0.0001, 0.5 * n + 1) for a, b, n in checks)
        out_meta.append(dict(m, additive=bool(add)))
    ratio = {}
    for role, (num, den, mul) in RECOMPUTE.items():
        k, a, b = metric_keys.get(role), metric_keys.get(num), metric_keys.get(den)
        if k in keys and a in keys and b in keys:
            ratio[k] = [a, b, mul]
    dd = [d for d in (default_dims or ["media", PRODUCT_DIM]) if d in dims] or dims[:1]
    lab = dict(DIM_LABELS, **(labels or {}))
    return {"dims": [{"key": d, "label": lab.get(d, d)} for d in dims], "default_dims": dd,
            "dict": {d: list(dic[d]) for d in dims}, "codes": codes, "period": period, "periods": periods,
            "metrics": out_meta, "vals": vals, "ratio": ratio, "cost": metric_keys.get("cost"),
            "totals": {p: {k: (totals.get(p) or {}).get(k) for k in keys} for p in periods} if totals else None}


def split_by_period(env, period_map):
    """기간이 섞인 봉투 → {기간 키: 봉투}. period_map = {행의 date/month 값: 기간 키}."""
    out = {k: dict(env, rows=[]) for k in period_map.values()}
    for r in (env or {}).get("rows") or []:
        k = period_map.get(period_of(r))
        if k:
            out[k]["rows"].append(r)
    return {k: v for k, v in out.items() if v["rows"]}


def with_period(env, field, value):
    """total grain 봉투 행에 기간 값을 붙인다(대조 검증에서 상위 봉투와 기간을 맞추기 위해)."""
    return dict(env, rows=[dict(r, **{field: value}) for r in (env or {}).get("rows") or []])


# ── 기간 묶기 (day grain → 주 단위 등) ────────────────────────────────────────


def bucket_values(env, dims, buckets, metrics, units, metric_keys):
    """day grain 봉투 → {버킷 키: {차원값 튜플: {지표: 값}}}. buckets = {날짜 문자열: 버킷 키}.
    여러 날을 묶으므로 가산 지표는 더하고 CTR·CPM·CPV는 합친 원자 지표로 다시 계산한다(aggregate) — 그 밖의 비율
    지표는 None. 한 버킷에 하루뿐이어도 같은 규칙을 쓴다(값 출처를 섞지 않기 위해)."""
    parts = {}
    for row in (env or {}).get("rows") or []:
        b = buckets.get(period_of(row))
        if b is None:
            continue
        key = tuple(_label(row.get(d)) for d in dims)
        parts.setdefault(b, {}).setdefault(key, []).append(row)
    return {b: {k: aggregate(rows, metrics, units, metric_keys) for k, rows in g.items()} for b, g in parts.items()}


# ── 목표 대비 판정 ───────────────────────────────────────────────────────────

LOWER_BETTER_ROLES = ("cpm", "cpv")
BURN_LOW, BURN_HIGH = 0.95, 1.05


def burn_status(rate):
    """목표 예산 대비 소진율 → 상태 태그. 95~105% 정상, 미만 과소, 초과 초과."""
    if rate is None:
        return None
    if rate > BURN_HIGH:
        return {"label": "초과 소진", "tone": "red"}
    if rate < BURN_LOW:
        return {"label": "과소 소진", "tone": "yellow"}
    return {"label": "정상 소진", "tone": "green"}


def burn_cards(spend, prev_spend, budget, currency, missing=None):
    """[목표 대비 광고비 소진율, 광고비(전월 대비)] 카드 2개. 예산이 없으면 소진율 카드를 빼고 광고비 카드만."""
    money = lambda v: fmt_metric(v, currency)  # noqa: E731
    cards = []
    if budget and isinstance(spend, (int, float)):
        r = spend / budget
        st = burn_status(r)
        rest = (f"미소진 예산 {money(budget - spend)}" if r < 1 else f"목표 예산 초과 {money(spend - budget)}")
        if missing:
            rest += f" · 목표 없음: {', '.join(missing)} 제외"
        cards.append({"label": "목표 대비 광고비 소진율", "value": f"{r * 100:.1f}%", "tag": st, "rate": r,
                      "bar": r, "bar_cls": {"red": "up", "yellow": "warn"}.get(st["tone"], ""),
                      "lines": [{"text": f"광고비 {money(spend)} / 목표 예산 {money(budget)}"}, {"text": rest, "cls": "lh-kpi-sub"}],
                      "deltas": []})
    if isinstance(spend, (int, float)):
        d = delta(spend, prev_spend, currency)
        lines = [{"text": f"전월 대비 {d['text']}", "cls": "lh-kpi-delta " + d["dir"], "x": delta_value(spend, prev_spend, currency)}]
        if isinstance(prev_spend, (int, float)):
            diff = spend - prev_spend
            lines.append({"text": f"전월 광고비 {money(prev_spend)} · 차이 {'+' if diff >= 0 else '−'}{money(abs(diff))}",
                          "cls": "lh-kpi-sub"})
        cards.append({"label": "광고비 (전월 대비)", "value": money(spend), "lines": lines, "deltas": []})
    return cards


# ── 선택 표 (Dimension·지표 고르기 — 목업의 성과 비교 / 목표 대비 달성률 표) ─────────────


def pick_section(envs_by_period, meta, metric_keys, dots=None, default_dims=None, default_metrics=None, labels=None,
                 compare=None, goal=None, sort=None, search_dim=None, compares=None, totals=None, current=None):
    """LHKit.pickTable 데이터 = pivot_data + 표 방식.
    - compare = {"base", "cur", "base_label", "cur_label", "delta_label"} → 지표마다 [비교 기간, 기준 기간(+증감)]
    - compares = {키: compare} — 비교 기준이 여럿이면 페이지의 비교 기준 탭(LHKit.compareTabs)을 따른다(daily 전일·전주 동요일)
    - totals = {기간 키: {지표: 서버 총계}} — 가산 판정에 쓰고, 검색하지 않은 '전체' 행은 서버 총계를 그대로 보여 준다
    - goal = {"cur", "cur_label", "targets": {"levels": [[차원...], ...], "values": {"<수준 i>": {"값\u0001값": {지표: 목표}}}}}
      → 지표마다 [월 목표, 실적, 달성률]. 목표가 없는 지표는 실적 열만.
      goal["full"] = True → 모든 지표 [목표, 실적, 달성률/목표 대비](목표 없으면 '-') + 매체 소계 행(monthly).
    - current = 기간 키 → 비교 없이 그 기간 값만 지표당 1열(mtd 상세 성과). compare·goal이 없으면 마지막 기간.
    응답에 없는 차원은 dims에 나타나지 않는다(조용히 빠진다)."""
    spec = pivot_data(envs_by_period, meta, metric_keys, totals=totals, default_dims=default_dims, labels=labels)
    if not spec["dims"]:
        return None
    cost = metric_keys.get("cost")
    spec["metrics"].sort(key=lambda m: m["key"] != cost)   # 광고비는 항상 맨 앞(나머지는 서버 순서)
    keys = [m["key"] for m in spec["metrics"]]
    dm = [k for k in (default_metrics or [cost]) if k in keys] or keys[:1]   # 기본 = 광고비만(사용자가 메뉴에서 늘린다)
    lower = [metric_keys[r] for r in LOWER_BETTER_ROLES if metric_keys.get(r)]
    spec.update(default_metrics=dm, dots=dots or {}, dot_dims=["brand", "media"], lower=lower,
                cost=cost, sort=sort or "cost")
    if search_dim in [d["key"] for d in spec["dims"]]:   # 검색 차원 기본값(없는 차원이면 화면 규칙을 따른다)
        spec["search_dim"] = search_dim
    if compares:
        compare = compare or next(iter(compares.values()))
        spec["compares"] = compares
    if compare:
        spec["mode"], spec["compare"] = "compare", compare
    if goal:
        spec["mode"], spec["goal"] = "goal", goal
    if "mode" not in spec:
        spec["mode"], spec["plain"] = "plain", {"cur": current or spec["periods"][-1]}
    return spec


def group_values(env, dims, metrics, units, metric_keys):
    """가장 잘게 받은 봉투 → {차원값 튜플: {지표: 값}} (선택 표와 같은 규칙: 원 행 1개 = 서버 값, 여럿 = aggregate).
    요약 근거(digest)가 화면 표와 같은 숫자를 쓰게 하려고 둔다."""
    parts = {}
    for row in (env or {}).get("rows") or []:
        parts.setdefault(tuple(_label(row.get(d)) for d in dims), []).append(row)
    out = {}
    for k, rows in parts.items():
        out[k] = ({m: (rows[0].get(m) if isinstance(rows[0].get(m), (int, float)) else None) for m in metrics}
                  if len(rows) == 1 else aggregate(rows, metrics, units, metric_keys))
    return out

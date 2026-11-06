"""overall-summary의 목표 표(get_target_progress_v2 원문) 해석 — build_report가 쓴다."""
import json
import re

from report_kit import PRODUCT_DIM as P

# 목표 표 행 이름 → 목표 키 (cost = 예산, 나머지 = 목표 영역 e.*)
TARGET_ROWS = {"cost": "cost", "budget": "cost", "cost_net": "cost_net", "impression": "imp", "impressions": "imp", "imps": "imp",
               "click": "click", "clicks": "click", "views": "view", "view": "view", "video_views": "view",
               "ctr": "ctr", "vtr": "vtr", "cpm": "cpm", "cpc": "cpc", "cpv": "cpv"}
SCOPE_COLS = {"media": "m", "매체": "m", P: "p", "ad_type": "p", "product": "p", "campaign_name": "c", "campaign": "c", "캠페인": "c",
              "ad_group_name": "t", "ad_group": "t", "광고그룹": "t", "광고 그룹": "t"}


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
    표마다 metric·target 열을 읽는다(cost = 예산 — 서버 기준, 옛 서버는 cost = Gross·cost_net = Net. revenue·roas·actual·achievement는
    쓰지 않는다. 셋째 표 media|fee_mode|rate는 metric 열이 없어 건너뛴다 — fees.fee_table이 읽는다).
    - 첫째 표 `| metric | target | actual | progress_ratio |` = 호출 범위(media 인자, 생략 = 전체)의 합계.
    - 둘째 표 `| media | campaign_name | included | metric | … |` = 매체 행(campaign_name `-`)과 캠페인 행(dashboard 브랜드).
      범위 열 값이 `-`·all이면 그 차원은 범위에 넣지 않는다. 캠페인 행의 included(Y/N)는 "inc"로 남긴다.
    표가 아니면(한 줄 '목표 없음' 메시지·에러) 빈 리스트."""
    text = entry.get("target_progress") or ""
    m = re.search(r"^month:\s*(\d{4}-\d{2})", text, re.M)
    month = str(entry.get("month") or (m.group(1) if m else ""))[:7]
    base = {SCOPE_COLS[k]: str(entry[k]) for k in ("media", "ad_type", P, "campaign_name", "ad_group_name") if entry.get(k)}
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
        e["srv"] = sorted(e["v"])   # 서버가 준 목표 — Net 보기에서 파생 목표를 Net 예산으로 다시 계산할 때 쓴다(fees.net_budgets)
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

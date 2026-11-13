"""외부 요인 skill 4개가 함께 쓰는 HTML 한 장 — 파트별 요약 → 비교 차트(1개 이상) → 근거 목록.

Chart.js는 같은 폴더의 ``chart.umd.min.js``를 인라인한다. 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import os
from datetime import date
from html import escape

HERE = os.path.dirname(os.path.abspath(__file__))
DOW = "월화수목금토일"
# 차트 색: 자사는 강조색, 경쟁사는 채도를 낮춘 색(테마 토큰에서 읽는다).
BRAND_TOKENS = ["--own", "--c1", "--c2", "--c3", "--c4"]


def md(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{x.month}/{x.day}({DOW[x.weekday()]})"


def md_short(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{x.month}/{x.day}"


def span(start: str, end: str) -> str:
    """차트 제목용 범위 "M/D~M/D"(하루면 "M/D")."""
    return md_short(start) if start == end else f"{md_short(start)}~{md_short(end)}"


def token(i: int) -> str:
    return BRAND_TOKENS[i] if i < len(BRAND_TOKENS) else "--c1"


PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
/* 레이아웃: 960px 한 단 보고서 — 파트별 요약 → 비교 차트 → 근거 순 */
:root {{
  --bg:#f6f8fb; --card:#ffffff; --fg:#1e293b; --muted:#64748b; --line:#e2e8f0; --chip:#eef2f7;
  --own:#0b57d0; --c1:#94a3b8; --c2:#c08457; --c3:#7c9a7e; --c4:#b08fc7; --warn:#b45309;
  --rain:#38bdf8; --temp:#ef4444; --di:#f59e0b; --wknd:rgba(100,116,139,.12); --rainband:rgba(56,189,248,.18);
  --sans:'Pretendard','Noto Sans KR',-apple-system,BlinkMacSystemFont,sans-serif;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#0f141b; --card:#161d27; --fg:#e2e8f0; --muted:#94a3b8; --line:#2a3442; --chip:#1f2935;
  --own:#7aa7ff; --c1:#64748b; --c2:#d19a6c; --c3:#8fb592; --c4:#c3a5da; --warn:#f59e0b; --wknd:rgba(148,163,184,.14); --rainband:rgba(56,189,248,.16); color-scheme:dark; }} }}
:root[data-theme="dark"] {{
  --bg:#0f141b; --card:#161d27; --fg:#e2e8f0; --muted:#94a3b8; --line:#2a3442; --chip:#1f2935;
  --own:#7aa7ff; --c1:#64748b; --c2:#d19a6c; --c3:#8fb592; --c4:#c3a5da; --warn:#f59e0b; --wknd:rgba(148,163,184,.14); --rainband:rgba(56,189,248,.16); color-scheme:dark; }}
body {{ background:var(--bg); color:var(--fg); font-family:var(--sans); line-height:1.6;
  padding-block:28px; padding-left:max(16px, env(safe-area-inset-left, 0px)); padding-right:max(16px, env(safe-area-inset-right, 0px)); }}
.wrap {{ max-width:960px; margin:0 auto; display:flex; flex-direction:column; gap:16px; }}
.eyebrow {{ font-size:12px; letter-spacing:.06em; color:var(--muted); }}
h1 {{ font-size:22px; text-wrap:balance; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:20px; min-width:0; }}
/* 요약 카드 4가지 양식 */
.summary {{ font-size:17px; font-weight:600; }}
.summary .lab, .lab {{ display:block; font-size:12px; font-weight:600; color:var(--muted); margin-bottom:4px; letter-spacing:.04em; }}
.summary .sub {{ display:block; margin-top:8px; font-size:14px; font-weight:400; color:var(--muted); }}
.summary.rows {{ font-size:16px; }}
.summary .part {{ display:grid; grid-template-columns:112px 1fr; gap:12px; padding:10px 0; }}
.summary .part + .part {{ border-top:1px solid var(--line); }}
.summary .part .k {{ font-size:13px; color:var(--own); font-weight:700; padding-top:2px; }}
@media (max-width:560px) {{ .summary .part {{ grid-template-columns:1fr; gap:2px; }} }}
.sum3 {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:12px; font-size:15px; }}
.sum3 li {{ display:grid; grid-template-columns:104px 1fr; gap:12px; align-items:baseline; }}
.sum3 .k {{ font-size:12px; font-weight:600; color:var(--muted); background:var(--chip); border-radius:6px; padding:2px 8px; text-align:center; }}
.sum3 .v b {{ font-weight:700; }}
.sum3 .v span {{ font-weight:400; }}
@media (max-width:480px) {{ .sum3 li {{ grid-template-columns:1fr; gap:4px; }} .sum3 .k {{ justify-self:start; }} }}
.sum {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
@media (max-width:640px) {{ .sum {{ grid-template-columns:1fr; }} }}
.sum p {{ margin:0; }}
.sum .big {{ font-size:17px; font-weight:600; }}
.sum .sub {{ font-size:14px; }}
.chead {{ display:flex; justify-content:space-between; align-items:center; gap:8px 16px; flex-wrap:wrap; margin-bottom:12px; }}
.chead h2 {{ margin:0; }}
.wkey {{ display:inline-flex; align-items:center; gap:6px; font-size:12px; color:var(--muted); white-space:nowrap; margin-left:auto; }}
.wkey + .wkey {{ margin-left:0; }}
.wkey i {{ width:14px; height:14px; border-radius:3px; background:var(--wknd); border:1px solid var(--line); }}
.seg {{ display:inline-flex; background:var(--chip); border-radius:8px; padding:3px; gap:2px; }}
.seg button {{ font:inherit; font-size:12.5px; border:0; background:transparent; color:var(--muted); padding:4px 10px; border-radius:6px; cursor:pointer; }}
.seg button[aria-pressed="true"] {{ background:var(--card); color:var(--fg); font-weight:600; box-shadow:0 1px 2px rgba(0,0,0,.08); }}
.seg button:focus-visible {{ outline:2px solid var(--own); outline-offset:1px; }}
.chart {{ position:relative; height:320px; }}
.take {{ font-size:13px; color:var(--muted); margin:0 0 12px; white-space:pre-line; }}
.wkey i.rb {{ background:var(--rainband); }}
.card .note {{ margin-top:8px; }}
.note {{ font-size:12px; color:var(--muted); }}
.warn {{ font-size:13px; color:var(--warn); font-weight:600; }}
ul.docs {{ list-style:none; display:flex; flex-direction:column; gap:10px; }}
ul.docs li {{ display:grid; grid-template-columns:72px 1fr; gap:10px; font-size:14px; }}
ul.docs .d {{ color:var(--muted); font-variant-numeric:tabular-nums; font-size:13px; }}
ul.docs .n {{ color:var(--muted); font-size:12px; margin-left:6px; }}
a {{ color:var(--own); text-decoration:none; }} a:hover, a:focus-visible {{ text-decoration:underline; }}
h2 {{ font-size:14px; margin-bottom:12px; }}
</style>
<div class="wrap">
  <div class="eyebrow">외부 요인 · {skill}</div>
  <h1>{title}</h1>
  {banner}
  {summary}
  {charts}
  {note}
  {extra}
</div>
<script>{chartjs}</script>
<script>
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const charts = {specs};
// 토·일 세로 음영(라벨이 "M/D(토)"·"M/D(일)"인 칸)
const weekendBands = {{ id:'weekendBands', beforeDatasetsDraw(ch) {{
  const {{ ctx, chartArea:a, scales:{{ x }} }} = ch; const labels = ch.data.labels;
  const step = labels.length > 1 ? x.getPixelForValue(1) - x.getPixelForValue(0) : a.right - a.left;
  ctx.save(); ctx.fillStyle = css('--wknd');
  labels.forEach((l, i) => {{ if (!/\\((토|일)\\)/.test(l)) return;
    const c = x.getPixelForValue(i), l0 = Math.max(a.left, c - step/2), r0 = Math.min(a.right, c + step/2);
    ctx.fillRect(l0, a.top, r0 - l0, a.bottom - a.top); }});
  ctx.restore(); }} }};
// 지정한 칸(c.bands.idx)에 세로 음영(비 온 날 등)
const bandsOf = b => ({{ id:'bands', beforeDatasetsDraw(ch) {{
  const {{ ctx, chartArea:a, scales:{{ x }} }} = ch, n = ch.data.labels.length;
  const step = n > 1 ? x.getPixelForValue(1) - x.getPixelForValue(0) : a.right - a.left;
  ctx.save(); ctx.fillStyle = css(b.tok);
  b.idx.forEach(i => {{ const c = x.getPixelForValue(i), l0 = Math.max(a.left, c - step/2), r0 = Math.min(a.right, c + step/2);
    ctx.fillRect(l0, a.top, r0 - l0, a.bottom - a.top); }});
  ctx.restore(); }} }});
const live = [], pick = charts.map(() => 0);
function draw(i) {{
  const c = charts[i], spec = JSON.parse(JSON.stringify(c.spec));
  if (c.metrics) {{ const m = c.metrics[pick[i]];
    // 지표 하나에 데이터셋 여럿(매체별 막대): sets[k]가 k번째 데이터셋 값
    m.sets.forEach((s, k) => {{ spec.data.datasets[k].data = s; }}); spec.options.scales.y.title.text = m.unit;
    const el = document.querySelector(`[data-c="${{i}}"] .mname`); if (el) el.textContent = m.name;
    const tk = document.querySelector(`[data-c="${{i}}"] .take`); if (tk && c.take) tk.textContent = c.take[pick[i]];
    document.querySelectorAll(`[data-c="${{i}}"] .seg button`).forEach((b, j) => b.setAttribute('aria-pressed', j === pick[i])); }}
  spec.data.datasets.forEach(d => {{ if (d.tok) {{ d.borderColor = css(d.tok); d.backgroundColor = d.fill ? css(d.tok) + '55' : css(d.tok); }}
    if (d.toks) d.backgroundColor = d.toks.map(css); }});
  spec.plugins = c.bands ? [weekendBands, bandsOf(c.bands)] : [weekendBands];
  if (live[i]) live[i].destroy();
  live[i] = new Chart(document.querySelector(`[data-c="${{i}}"] canvas`), spec);
}}
function drawAll() {{
  Chart.defaults.color = css('--muted'); Chart.defaults.borderColor = css('--line');
  Chart.defaults.font.family = css('--sans'); charts.forEach((_, i) => draw(i));
}}
charts.forEach((c, i) => (c.metrics && c.metrics.length > 1 ? c.metrics : []).forEach((m, j) => {{
  const b = document.createElement('button'); b.type = 'button'; b.textContent = m.button;
  b.addEventListener('click', () => {{ pick[i] = j; draw(i); }});
  document.querySelector(`[data-c="${{i}}"] .seg`).appendChild(b); }}));
drawAll();
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', drawAll);
</script>
"""


def render(charts: list, **kw) -> str:
    """``PAGE``를 채운다. ``charts``는 ``{title, spec, metrics?}`` 목록이고 ``spec``은 Chart.js 스펙 dict다.
    ``metrics``(``[{name, button, unit, sets}]``, ``sets[k]``는 k번째 데이터셋 값)가 있으면 앞 데이터셋들을
    그 지표로 바꾼다. 지표가 둘 이상일 때만 토글 버튼을 단다.
    차트마다 ``note``(카드 안 각주)·``take``(지표별 해석, ``metrics``와 같은 순서, 줄바꿈 가능)·``height``(px)·
    ``bands``(``{idx, tok}``: 그 칸들에 세로 음영)를 줄 수 있다.
    ``summary``는 ``summary_html``이 만든 조각, ``note``(차트 아래 공통 각주 평문, 선택)·``extra``는 HTML 조각."""
    kw["note"] = f'<p class="note">{escape(kw["note"])}</p>' if kw.get("note") else ""
    kw.setdefault("banner", "")
    kw.setdefault("extra", "")
    kw["charts"] = "\n  ".join(chart_card(i, c) for i, c in enumerate(charts))
    kw["specs"] = json.dumps(
        [{"spec": c["spec"], "metrics": c.get("metrics"), "take": c.get("take"), "bands": c.get("bands")}
         for c in charts],
        ensure_ascii=False,
    ).replace("<", "\\u003c")  # 외부 글자(브랜드명·라벨)가 script를 닫거나 주석 상태로 바꾸지 못하게
    with open(os.path.join(HERE, "chart.umd.min.js"), encoding="utf-8") as f:
        kw["chartjs"] = f.read()
    return PAGE.format(**kw)


def chart_card(i: int, c: dict) -> str:
    title = escape(c["title"])
    if c.get("metrics"):
        title = title.replace("{metric}", f'<span class="mname">{escape(c["metrics"][0]["name"])}</span>')
    side = '<div class="seg" role="group" aria-label="성과 지표 선택"></div>' if len(c.get("metrics") or []) > 1 else ""
    if any(f"({DOW[5]})" in x or f"({DOW[6]})" in x for x in c["spec"]["data"]["labels"]):
        side += '<span class="wkey"><i></i>음영 = 주말(토·일)</span>'
    if c.get("key"):
        swatch = '<i class="rb"></i>' if c.get("bands") else ""
        side += f'<span class="wkey">{swatch}{escape(c["key"])}</span>'
    take = '<p class="take"></p>' if c.get("metrics") and c.get("take") else ""
    style = f' style="height:{int(c["height"])}px"' if c.get("height") else ""
    note = f'<p class="note">{escape(c["note"])}</p>' if c.get("note") else ""
    return (
        f'<div class="card" data-c="{i}"><div class="chead"><h2>{title}</h2>{side}</div>{take}'
        f'<div class="chart"{style}><canvas role="img" aria-label="{escape(c["title"].replace("{metric}", "성과 지표"))}">'
        f"</canvas></div>{note}</div>"
    )


class SummaryError(ValueError):
    """요약 입력이 파트 구성과 맞지 않는다(모델에게 그대로 돌려줄 메시지)."""


# 요약 양식(skill마다 하나)
#   lead : 굵은 결론 + 회색 보조 문단들(검색량). 파트는 문자열, ``prefix``에 든 라벨은 "라벨: "을 앞에 붙인다.
#   rows : 파란 라벨 + 본문, 행 사이 구분선(뉴스). 파트는 문자열.
#   chips: 회색 칩 라벨 + 굵은 결론 + 근거(블로그). 파트는 {"head", "body"}.
#   cols : "한 줄 요약" 표시 없이 2단 — 첫 파트 크게, 둘째 작게(날씨). 파트는 문자열.
STYLES = ("lead", "rows", "chips", "cols")


def parse_summary(text: str, labels: list, style: str) -> list:
    """모델 요약(JSON 배열, 파트 순서는 ``labels``) → ``[{label, head, body}]``.
    chips 양식은 파트마다 ``{"head": 굵은 결론, "body": 근거}``, 나머지는 문자열 하나(``body``에 담는다)."""
    shape = '{"head", "body"}' if style == "chips" else "문자열"
    try:
        parts = json.loads(text)
    except ValueError:
        parts = None
    ok = isinstance(parts, list) and len(parts) == len(labels)
    if ok and style == "chips":
        ok = all(isinstance(p, dict) and str(p.get("head") or "").strip() for p in parts)
    elif ok:
        ok = all(isinstance(p, str) and p.strip() for p in parts)
    if not ok:
        raise SummaryError(f"요약은 JSON 배열로, {labels} 순서의 {shape} {len(labels)}개여야 합니다.")
    if style == "chips":
        return [
            {"label": lab, "head": str(p["head"]).strip(), "body": str(p.get("body") or "").strip()}
            for lab, p in zip(labels, parts)
        ]
    return [{"label": lab, "head": "", "body": p.strip()} for lab, p in zip(labels, parts)]


def summary_html(parts: list, style: str, prefix: tuple = ()) -> str:
    """요약 카드 전체(``<div class="card …">``). 양식은 ``STYLES``."""
    e = escape
    if style == "lead":
        first, rest = parts[0], parts[1:]
        subs = "".join(
            f'<span class="sub">{e(p["label"] + ": " if p["label"] in prefix else "")}{e(p["body"])}</span>'
            for p in rest
        )
        return f'<div class="card summary"><span class="lab">한 줄 요약</span>{e(first["body"])}{subs}</div>'
    if style == "rows":
        rows = "".join(
            f'<div class="part"><span class="k">{e(p["label"])}</span><span>{e(p["body"])}</span></div>' for p in parts
        )
        return f'<div class="card summary rows"><span class="lab">한 줄 요약</span>{rows}</div>'
    if style == "chips":
        items = "".join(
            f'<li><span class="k">{e(p["label"])}</span><span class="v"><b>{e(p["head"])}</b> '
            f'<span>{e(p["body"])}</span></span></li>'
            for p in parts
        )
        return f'<div class="card summary"><span class="lab">한 줄 요약</span><ul class="sum3">{items}</ul></div>'
    big, sub = parts[0], parts[1]
    return (
        f'<div class="card sum"><div><span class="lab">{e(big["label"])}</span><p class="big">{e(big["body"])}</p></div>'
        f'<div><span class="lab">{e(sub["label"])}</span><p class="sub">{e(sub["body"])}</p></div></div>'
    )


def summary_text(parts: list) -> str:
    """숫자 대조용 평문."""
    return "\n".join(f'- **{p["label"]}**: {p["head"]} {p["body"]}'.replace("  ", " ").rstrip() for p in parts)


def docs_card(title: str, rows: list) -> str:
    """주요 기사·글 목록. ``rows``가 비면 '특이점 없음' 한 줄."""
    if not rows:
        return f'<div class="card"><h2>{escape(title)}</h2><p class="note">특이점 없음</p></div>'
    def href(link: str) -> str:
        return escape(link) if link.startswith(("http://", "https://")) else ""

    items = "".join(
        f'<li><span class="d">{md(r["date"])}</span><span><a href="{href(r["link"])}" '
        f'target="_blank" rel="noopener">{escape(r["title"])}</a>'
        f'<span class="n">{escape(r["meta"])}</span></span></li>'
        for r in rows
    )
    return f'<div class="card"><h2>{escape(title)}</h2><ul class="docs">{items}</ul></div>'

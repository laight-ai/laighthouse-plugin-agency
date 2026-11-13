"""weather-impact skill — 서울 일별 날씨(기온·강수·불쾌지수·유형) + (있으면) 광고 성과 겹치기.

skill 폴더의 ``assets/prepare.py``·``assets/build_report.py``가 부른다. 표준 라이브러리만 쓴다.

- 날씨: 저장 훅의 ``get_external_context``(``kind=weather``, ``start_date = 시작``, ``end_date = 끝``)
  응답 ``rows``. 유형·결측 규칙: 비 ≥1mm,
  폭우 ≥30mm(비 대신 표기), 폭염 최고기온 ≥30℃, 무더위 불쾌지수 최대 ≥75, 시간자료 결측이 6시간을
  넘으면 불쾌지수 없음·"(DI 결측)".
- 광고 성과: 저장 훅의 ``get_ad_performance``(같은 범위, ``time_grain: day``, ``group_by: ["media"]``,
  ``metrics``·``filters`` 생략) 응답이 있으면 매체별 날짜 값(클릭·전환·매출, 구매전환율 = 전환 ÷ 클릭)을
  겹친다. 매체끼리 더하지 않고, 범위 안 값이 0 또는 없음뿐인 매체·지표(집계 안 함)는 뺀다.
  없거나 오류(광고 mart가 없는 브랜드)면 날씨만 낸다. 가상 수치는 만들지 않는다.
- 비 온 날 차이(``rain_gap``): 매체·지표마다 비 온 날을 같은 요일 유형(평일·주말)의
  비 없는 날 평균과 비교한 변화율의 평균. 기온·불쾌지수는 지표와의 상관계수와 방향(same·opposite·none,
  연관일 뿐 원인이 아니다).
- 차트: 불쾌지수(시간자료 일평균)·평균기온·강수량 3개, 매체별 막대(나란히), 차트마다 성과 지표 토글
  (지표가 둘 이상일 때만), 강수량 차트는 비 온 날 세로 음영.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from html import escape

import page
import responses
import saved
import trend_config as config
import trend_core as core
from range_report import SHORT_RANGE_DAYS, Refusal, parse_range, write_report

SKILL = "weather-impact"
RAIN_MM = 1
HEAVY_RAIN_MM = 30
HEAT_TA = 30
MUGGY_DI = 75
MAX_DI_MISSING_HOURS = 6


# ── 날씨 유형·일 기록 ─────────────────────────────────────────────────────────


def weather_types(sum_rn: float, max_ta, di_max) -> tuple:
    """날씨 유형(한파 제외). 폭우는 비 대신 표기한다. 해당 없으면 ("보통",)."""
    types = []
    if sum_rn >= HEAVY_RAIN_MM:
        types.append("폭우")
    elif sum_rn >= RAIN_MM:
        types.append("비")
    if max_ta is not None and max_ta >= HEAT_TA:
        types.append("폭염")
    if di_max is not None and di_max >= MUGGY_DI:
        types.append("무더위")
    return tuple(types) or ("보통",)


def r1(v):
    return None if v is None else round(float(v), 1)


def weather_record(d: str, max_ta, min_ta, sum_rn, hours, di_avg, di_max, avg_ta=None) -> dict:
    """일 관측 1행 → 값·유형. 시간자료 결측이 6시간을 넘으면 불쾌지수는 None."""
    di_ok = 24 - int(hours or 0) <= MAX_DI_MISSING_HOURS
    rn = float(sum_rn or 0)
    ta = None if max_ta is None else float(max_ta)
    di = float(di_max) if di_ok and di_max is not None else None
    rec = {
        "date": d,
        "max_ta": r1(max_ta),
        "min_ta": r1(min_ta),
        "avg_ta": r1(avg_ta),
        "sum_rn": round(rn, 1),
        "di_avg": r1(di_avg) if di_ok else None,
        "di_max": r1(di) if di_ok else None,
        "di_missing": not di_ok,
        "rain": rn >= RAIN_MM,
        "heavy_rain": rn >= HEAVY_RAIN_MM,
        "heat": ta is not None and ta >= HEAT_TA,
        "muggy": di is not None and di >= MUGGY_DI,
    }
    rec["type"] = "·".join(weather_types(rn, ta, di))
    if rec["di_missing"]:
        rec["type"] += "(DI 결측)"
    return rec


# ── 날씨·클릭 ─────────────────────────────────────────────────────────────────


def records(resp: dict) -> list:
    return [
        weather_record(
            r["tm"], r["max_ta"], r["min_ta"], r["sum_rn"], r["hours"], r["di_avg"], r["di_max"],
            r.get("avg_ta"),
        )
        for r in resp["rows"]
    ]


# 성과 지표: (facts 키, 버튼, 차트 이름, 단위). 구매전환율은 전환 ÷ 클릭 × 100.
METRICS = [
    ("click", "광고 클릭", "광고 클릭", "클릭"),
    ("cvr", "구매전환율", "구매전환율(%)", "%"),
    ("revenue", "매출액", "매출액", "원"),
]


def daily_metrics(brand: str, start: date, end: date, root: str | None = None) -> tuple[dict, list]:
    """저장된 day grain 광고 성과 → ({매체: {지표: {날짜: 값}}}, 숨긴 [{media, metric}]).

    매체끼리 더하지 않는다 — 어느 매체의 행이 빠진 날이 다른 매체 값만으로 '적은 날'이 되지 않게.
    행이 없는 매체·날은 값이 없다(0으로 채우지 않는다). 범위 안에서 0보다 큰 값이 한 번도 없는
    매체·지표는 집계하지 않는 것으로 보고 뺀다(구매전환율은 전환이 집계되는 매체만 남는다).
    shortcut: 1일처럼 짧은 범위에서 실제로 전환이 0인 날도 '집계 안 함'으로 숨는다. 마트가 지표별 집계 여부를
    알려 주게 되면 그 값으로 바꾼다. 응답·클릭 키가 없으면 ({}, [])."""
    env = saved.daily_ad_envelope(brand, start.isoformat(), end.isoformat(), root)
    if not env:
        return {}, []
    keys = saved.metric_keys(list(env.get("metrics") or []))
    if not keys.get("click"):
        return {}, []
    roles = [role for role in ("click", "conversion", "revenue") if keys.get(role)]
    raw: dict = {}
    for r in env["rows"]:
        media = r.get("media")
        if media is None:  # 광고 매체 행만(Organic 제외)
            continue
        d = str(r.get("date") or "")[:10]
        series = raw.setdefault(str(media), {role: {} for role in roles})
        for role in roles:
            v = r.get(keys[role])
            if isinstance(v, (int, float)):
                series[role][d] = series[role].get(d, 0) + v
    out: dict = {}
    hidden: list = []
    for media in sorted(raw):
        s = raw[media]
        if "conversion" in s:
            s["cvr"] = {d: round(100.0 * s["conversion"].get(d, 0) / c, 2) for d, c in s["click"].items() if c}
        kept = {}
        for key, *_ in METRICS:
            if key not in s:
                continue
            if any(v > 0 for v in s[key].values()):
                kept[key] = s[key]
            else:
                hidden.append({"media": media, "metric": key})
        if "click" in kept:
            out[media] = kept
        else:  # 클릭이 없는 매체는 다른 지표가 있어도 비교 기준이 없어 통째로 뺀다
            hidden += [{"media": media, "metric": k} for k in kept]
    return out, hidden


def correlation(xs: list, ys: list) -> float | None:
    """피어슨 상관계수(둘 다 값이 있는 날만, 5일 미만이면 None). statistics.correlation은 3.10부터라 직접 계산."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 5:
        return None
    mx = sum(x for x, _ in pairs) / len(pairs)
    my = sum(y for _, y in pairs) / len(pairs)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    return round(sxy / (sxx * syy) ** 0.5, 2) if sxx and syy else None


STRONG_CORR = 0.5  # rules.md 1절과 같은 기준


def direction(r: float | None) -> str:
    """상관계수 → 방향: same(+0.5 이상, 같은 방향), opposite(-0.5 이하, 반대 방향), none(그 사이·없음)."""
    if r is None or abs(r) < STRONG_CORR:
        return "none"
    return "same" if r > 0 else "opposite"


def rain_gap(recs: list, series: dict) -> dict | None:
    """비 온 날 지표 값 vs 같은 요일 유형 비 없는 날 평균. 비교할 날이 없으면 None."""
    days = [r for r in recs if r["date"] in series]
    rain = [r for r in days if r["rain"]]
    out = []
    for r in rain:
        same = [series[x["date"]] for x in days if not x["rain"] and core.is_weekend(date.fromisoformat(x["date"])) == core.is_weekend(date.fromisoformat(r["date"]))]
        if not same:
            continue
        base = sum(same) / len(same)
        out.append(
            {
                "date": r["date"],
                "value": series[r["date"]],
                "dry_same_daytype_avg": round(base, 1),
                "change_pct": round(100.0 * (series[r["date"]] / base - 1), 1) if base else None,
            }
        )
    pcts = [x["change_pct"] for x in out if x["change_pct"] is not None]
    if not pcts:
        return None
    return {"rain_days": out, "avg_change_pct": round(sum(pcts) / len(pcts), 1)}


# 관측소 번호 → 이름(기상청 ASOS). 없는 번호는 '관측소 N'으로 표시한다.
STATION_NAMES = {108: "서울"}


def station_label(station_id) -> str:
    name = STATION_NAMES.get(station_id)
    return f"{name}({station_id})" if name else f"관측소 {station_id}"


def make_facts(brand: str, start: date, end: date, recs: list, metrics: dict, station_id, hidden: list) -> dict:
    def pick(flag):
        return [r["date"] for r in recs if r[flag]]

    di = [r["di_max"] for r in recs if r["di_max"] is not None]
    counts = {
        "rain_1mm_or_more": len(pick("rain")),  # 폭우 포함
        "rain_only": sum(r["rain"] and not r["heavy_rain"] for r in recs),
        "heavy_rain": len(pick("heavy_rain")),
        "heat": len(pick("heat")),
        "muggy": len(pick("muggy")),
        "di_missing": len(pick("di_missing")),
    }
    ta = [r["max_ta"] for r in recs if r["max_ta"] is not None]
    avg_ta = [r["avg_ta"] for r in recs if r["avg_ta"] is not None]
    di_avg = [r["di_avg"] for r in recs if r["di_avg"] is not None]

    def metric_facts(series: dict, key: str) -> dict:
        ys = [series.get(r["date"]) for r in recs]
        ta = correlation([r["avg_ta"] for r in recs], ys)
        di_r = correlation([r["di_avg"] for r in recs], ys)
        return {
            "total": round(sum(series.values()), 1) if key != "cvr" else None,
            "days_with_data": sum(r["date"] in series for r in recs),
            "rain_gap": rain_gap(recs, series),
            "corr_avg_ta": ta,
            "corr_avg_ta_direction": direction(ta),
            "corr_di_avg": di_r,
            "corr_di_avg_direction": direction(di_r),
        }
    return {
        "brand": brand,
        "skill": SKILL,
        "station": station_label(station_id),
        "station_id": station_id,
        "range": {"start": start.isoformat(), "end": end.isoformat(), "days": (end - start).days + 1},
        "observed_days": len(recs),
        "missing_dates": sorted(
            {d.isoformat() for d in core.days_between(start, end)} - {r["date"] for r in recs}
        ),
        "thresholds": {"rain_mm": RAIN_MM, "heavy_rain_mm": HEAVY_RAIN_MM, "heat_max_ta": HEAT_TA,
                       "muggy_di_max": MUGGY_DI},
        "day_counts": counts,
        "rain_days": pick("rain"),
        "heavy_rain_days": pick("heavy_rain"),
        "heat_days": pick("heat"),
        "muggy_days": pick("muggy"),
        "di_missing_days": pick("di_missing"),
        "max_ta_range": [min(ta), max(ta)] if ta else None,
        "di_max_range": [min(di), max(di)] if di else None,
        "avg_ta_range": [min(avg_ta), max(avg_ta)] if avg_ta else None,
        "di_avg_range": [min(di_avg), max(di_avg)] if di_avg else None,
        "total_rain_mm": round(sum(r["sum_rn"] for r in recs), 1),
        "ad_performance": {
            "available": bool(metrics),
            "media": {
                m: {k: metric_facts(s[k], k) for k, *_ in METRICS if k in s} for m, s in metrics.items()
            },
            "hidden": hidden,
            "rule": "매체별로 그 매체 값이 있는 날끼리 계산. rain_gap = 비 온 날 vs 같은 요일 유형(평일·주말) "
            "비 없는 날 평균, corr = 상관계수(연관), *_direction = same(+0.5 이상)·opposite(-0.5 이하)·none, "
            "hidden = 범위 안 값이 0 또는 없음뿐이라 집계하지 않는 것으로 보고 뺀 매체·지표",
        },
        "days": recs,
    }


def prepare(brand: str, rng: str, root: str | None = None) -> dict:
    start, end = parse_range(rng, config.today_kst())
    call = {"brand_name": brand, "kind": "weather", "start_date": start.isoformat(), "end_date": end.isoformat()}
    try:
        resp = responses.find_response(brand, "weather", call["start_date"], call["end_date"], root)
    except LookupError as e:
        return {"missing": [call], "note": str(e)}
    except ValueError as e:
        return {"errors": [str(e)]}
    recs = records(resp)
    if not recs:
        raise Refusal(f"{start}~{end} 날씨 관측값이 아직 없습니다. 범위 끝을 앞당겨 다시 요청하세요.")
    metrics, hidden = daily_metrics(brand, start, end, root)
    facts = make_facts(brand, start, end, recs, metrics, resp.get("station_id"), hidden)
    r = {"skill": SKILL, "facts": facts, "metrics": metrics}
    folder = saved.work_dir(brand, SKILL, f"{start}_{end}")
    path = os.path.join(folder, "report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False)
    shown = {k: v for k, v in facts.items() if k != "days"}
    return {"json": path, "facts": shown}


# ── build ─────────────────────────────────────────────────────────────────────


PARTS = {True: ["① 날씨 영향이 있었나", "② 근거"], False: ["① 특이 날씨", "② 근거"]}
# (이름, "와/과", 주격 조사, 값 키, 색, 단위, 축 최소·최대 제안, facts 상관계수 키)
FACTORS = [
    ("불쾌지수", "와", "가", "di_avg", "--di", "불쾌지수", 40, 90, "corr_di_avg"),
    ("평균기온", "과", "이", "avg_ta", "--temp", "℃", None, None, "corr_avg_ta"),
    ("강수량", "과", "이", "sum_rn", "--rain", "mm", 0, None, None),
]
NUMS = "①②③"
CHART_HEIGHT = 240
CLEAR_GAP_PCT = 10.0  # rules.md 1절과 같은 기준


def take_text(title: str, subj: str, wa: str, corr_key, metric: str, mf: dict, rain_total: int = 0) -> str:
    """지표 토글·매체마다 차트 위에 보일 해석 한 줄. facts 값으로만 만든다(모델이 쓰지 않는다).
    지표 이름(광고 클릭·구매전환율·매출액)은 모두 받침으로 끝나 조사 '은·이'를 쓴다.
    ``rain_total``(범위의 비 온 날 수)보다 비교한 날이 적으면(그 매체 행이 없거나 같은 요일 유형 비 없는 날이 없음)
    비교한 날 수를 따로 밝힌다."""
    if corr_key is None:
        g = mf.get("rain_gap")
        if not g:
            return "비 온 날과 같은 요일 유형의 비 없는 날이 함께 있지 않아 비교할 수 없습니다."
        n, p = len(g["rain_days"]), g["avg_change_pct"]
        days = f"비 온 {n}일(파란 음영)" if n >= rain_total else f"비 온 {rain_total}일 중 비교할 수 있는 {n}일"
        if abs(p) < CLEAR_GAP_PCT:
            return f"{days}의 {metric}은 같은 평일·주말의 비 없는 날과 큰 차이가 없습니다({p:+.1f}%)."
        return (f"{days}의 {metric}이 같은 평일·주말의 비 없는 날보다 평균 {abs(p):.1f}% "
                + ("높습니다." if p > 0 else "낮습니다."))
    r = mf.get(corr_key)
    if r is None:
        return f"값이 있는 날이 적어 {title}{wa} {metric}의 관계를 보지 않았습니다."
    way = mf[f"{corr_key}_direction"]
    if way != "none":
        return f"{title}{subj} 높은 날 {metric}도 {'높은' if way == 'same' else '낮은'} 경향이 보입니다(상관계수 {r:+.2f}). 요일 주기와 섞여 있을 수 있습니다."
    return f"{title}{wa} {metric} 사이에 뚜렷한 관계가 보이지 않습니다(상관계수 {r:+.2f})."


METRIC_NAMES = {k: button for k, button, _, _ in METRICS}


def hidden_text(hidden: list) -> str:
    """각주용 '집계하지 않아 뺀 지표' 문장. 없으면 빈 문자열."""
    by_media: dict = {}
    for h in hidden:
        by_media.setdefault(h["media"], []).append(METRIC_NAMES[h["metric"]])
    if not by_media:
        return ""
    items = ", ".join(f"{m} {'·'.join(names)}" for m, names in by_media.items())
    return f" 범위 안에서 값이 0이거나 없어 집계하지 않는 것으로 본 지표는 표시하지 않았습니다({items})."


def charts(recs: list, metrics: dict, label: str, media_facts: dict) -> list:
    """날씨 요인 3개 차트. 광고 성과가 있으면 앞 데이터셋들이 매체별 지표 막대(나란히, 토글)이고 요인은 오른쪽 축.
    강수량 차트는 비 온 날(1mm 이상) 칸에 세로 음영을 그린다."""
    labels = [page.md(r["date"]) for r in recs]
    rain = [r["rain"] for r in recs]
    media = list(metrics)
    keys = [k for k, *_ in METRICS if any(k in metrics[m] for m in media)]
    toggles = [
        {"name": name, "button": button, "unit": unit,
         "sets": [[metrics[m].get(k, {}).get(r["date"]) for r in recs] for m in media]}
        for k, button, name, unit in METRICS
        if k in keys
    ]
    out = []
    for num, (title, josa, subj, key, tok, unit, lo, hi, corr_key) in zip(NUMS, FACTORS):
        values = [r[key] for r in recs]
        name = title if unit == title else f"{title}({unit})"
        # suggested*: 겨울 불쾌지수(40 미만)처럼 범위를 벗어난 값도 잘리지 않게 축이 늘어난다.
        # beginAtZero False: 막대 차트의 값 축 기본값(0부터)을 끄고 기온·불쾌지수 범위에 맞춘다.
        axis = {"title": {"display": True, "text": unit}, "beginAtZero": key == "sum_rn"}
        axis |= {"suggestedMin": lo} if lo is not None else {}
        axis |= {"suggestedMax": hi} if hi is not None else {}
        if key == "sum_rn":
            factor = {"type": "bar", "label": name, "data": values, "tok": tok}
        else:
            factor = {"type": "line", "label": name, "data": values, "tok": tok,
                      "tension": 0.25, "pointRadius": 3, "borderWidth": 2, "spanGaps": False}
        if len(recs) <= SHORT_RANGE_DAYS and factor["type"] == "line":
            factor["pointRadius"] = 5  # 점 1~3개뿐이라 크게
        if toggles:
            bars = [
                {"type": "bar", "label": m, "data": toggles[0]["sets"][i], "yAxisID": "y", "order": 1,
                 "borderRadius": 3, "tok": page.token(i)}
                for i, m in enumerate(media)
            ]
            if key == "sum_rn":
                factor = {"type": "line", "label": name, "data": values, "tok": tok,
                          "showLine": False, "pointRadius": [5 if x else 0 for x in rain]}
            datasets = [*bars, factor | {"yAxisID": "y2", "order": 0}]
            scales = {"y": {"beginAtZero": True, "title": {"display": True, "text": toggles[0]["unit"]}},
                      "y2": axis | {"position": "right", "grid": {"drawOnChartArea": False}}}
        else:
            datasets, scales = [factor | {"yAxisID": "y"}], {"y": axis}
        # 짧은 범위는 점·막대가 왼쪽 끝에 붙지 않게 칸 가운데에 둔다.
        scales["x"] = {"offset": True}
        # 지표마다 매체별 한 줄(그 지표를 집계하는 매체만). 여러 줄은 화면에서 줄바꿈된다.
        takes = [
            "\n".join(
                f"{m}: {take_text(title, subj, josa, corr_key, button, media_facts[m][k], sum(rain))}"
                for m in media
                if k in media_facts.get(m, {})
            )
            for k, button, _, _ in METRICS
            if k in keys
        ]
        out.append({
            "title": f"{num} {title}{josa} {{metric}} ({label})" if toggles else f"{num} {title} ({label})",
            "height": CHART_HEIGHT,
            "take": takes or None,
            "note": "주말(토·일)은 날씨와 관계없이 성과가 평일과 다르므로, 비 온 날은 매체마다 같은 평일·주말끼리 비교했습니다."
            if toggles and key == "sum_rn"
            else None,
            "spec": {"type": "bar", "data": {"labels": labels, "datasets": datasets},
                     "options": {"maintainAspectRatio": False,
                                 "interaction": {"mode": "index", "intersect": False}, "scales": scales}},
            "metrics": toggles or None,
            "bands": {"idx": [i for i, x in enumerate(rain) if x], "tok": "--rainband"}
            if toggles and key == "sum_rn" and any(rain) else None,
            "key": f"파란 음영 = 비 {RAIN_MM}mm 이상" if toggles and key == "sum_rn" and any(rain) else None,
        })
    return out


def events_card(recs: list) -> str:
    """특이 날씨(폭우·폭염·무더위)를 유형별로 날짜와 함께 한 줄씩. 없으면 '특이점 없음'."""
    groups = [
        ("폭우", "heavy_rain", f"강수 {HEAVY_RAIN_MM}mm 이상", "sum_rn", "mm"),
        ("폭염", "heat", f"최고기온 {HEAT_TA}℃ 이상", "max_ta", "℃"),
        ("무더위", "muggy", f"불쾌지수 최대 {MUGGY_DI} 이상", "di_max", ""),
    ]
    items = []
    for name, flag, rule, key, unit in groups:
        days = [r for r in recs if r[flag]]
        if not days:
            continue
        dates = ", ".join(f"{page.md(r['date'])} {r[key]}{unit}" for r in days)
        items.append(
            f'<li><span class="d">{name} {len(days)}일</span><span>{escape(dates)}'
            f'<span class="n">{escape(rule)}</span></span></li>'
        )
    if not items:
        return '<div class="card"><h2>특이 날씨</h2><p class="note">특이점 없음</p></div>'
    return f'<div class="card"><h2>특이 날씨</h2><ul class="docs">{"".join(items)}</ul></div>'


def build(json_path: str, summary: str, out: str | None = None) -> dict:
    with open(json_path, encoding="utf-8") as f:
        r = json.load(f)
    facts, metrics = r["facts"], r["metrics"]
    brand, rng, recs = facts["brand"], facts["range"], facts["days"]
    label = page.span(rng["start"], rng["end"])
    note = (
        f"날씨: 기상청 지상관측(ASOS) {facts['station']} 일자료. 불쾌지수는 시간자료의 기온·습도로 계산한 하루 평균이며, "
        "시간자료가 6시간 넘게 빠진 날은 비웠습니다."
    )
    if metrics:
        note += " 광고 성과는 매체별 값이고(매체끼리 더하지 않음, 행이 없는 날은 비움), 구매전환율은 전환 수 ÷ 클릭 수입니다."
    note += hidden_text(facts["ad_performance"]["hidden"])
    if facts["missing_dates"]:
        note += f" 관측값이 아직 없는 날: {', '.join(page.md(d) for d in facts['missing_dates'])}."
    parts = page.parse_summary(summary, PARTS[bool(metrics)], "cols")
    html = page.render(
        charts(recs, metrics, label, facts["ad_performance"]["media"]),
        title=escape(f"{brand} 날씨 영향"),
        skill="날씨: 불쾌지수·기온·강수",
        summary=page.summary_html(parts, "cols"),
        note=note,
        extra=events_card(recs),
    )
    return write_report(f"{brand}_{SKILL}_{rng['start']}_{rng['end']}", html, parts, [facts], out)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog=SKILL)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--brand", required=True)
    p.add_argument("--range", required=True, help="YYYY-MM-DD~YYYY-MM-DD")
    p.add_argument("--responses", help="응답 폴더(기본: 저장 훅 폴더)")
    b = sub.add_parser("build")
    b.add_argument("--json", required=True)
    b.add_argument("--summary")
    b.add_argument("--out")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "prepare":
            result = prepare(args.brand, args.range, args.responses)
        else:
            summary = args.summary if args.summary is not None else sys.stdin.read()
            result = build(args.json, summary, args.out)
    except (Refusal, page.SummaryError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0

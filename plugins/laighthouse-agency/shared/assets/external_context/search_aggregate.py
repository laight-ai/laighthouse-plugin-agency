"""검색량 집계 — naver-search skill의 소스. 브랜드별 추정 검색수·점유율·급증일 JSON을 만든다.

원천은 저장 훅 응답(`responses.SearchData`)의 키워드별 일별 추정 검색수(PC+모바일)다. 기간 통계·급증
기준선은 `trend_core.py` docstring을 따른다.

- 브랜드·일 값 = 브랜드 `keywords`의 `est_volume` 합을 정수로 반올림.
- 띄어쓰기만 다른 키워드(돌체구스토·돌체 구스토)는 DataLab이 같은 값을 주므로 **공백을 지운 문자열이
  같은 키워드는 하나만 센다**(먼저 나온 표기). 이 중복 제거는 브랜드 안에서만 한다.
- 값이 없는 키워드·날(일 5건 미만이면 DataLab이 행을 주지 않음)은 0으로 더한다. 테넌트의 어떤
  키워드도 행이 없는 날은 "데이터 없음"(None)이다. 불완전(1,000건 한도) 개념은 없다.
- 범위 끝을 덮는 검색량 요청이 없는 키워드가 하나라도 있거나 범위 끝 행이 없으면 `NoDataForTarget`으로
  거부한다(검색량은 매일 10:00 수집에 어제 값이 들어온다).
- 점유율 = 브랜드 범위 합 ÷ 테넌트 브랜드 전체 합(%).
- 급증 = 같은 요일 유형 기준선의 1.5배 이상이고 그날 300건 이상(가설값).
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import search_db
import trend_config as config
import trend_core as core

KIND = "search"
SPIKE_RATIO, SPIKE_MIN = 1.5, 300
FOOTNOTES = [
    "추정 검색수는 네이버 데이터랩 검색어 트렌드(상대값)를 검색광고 키워드도구의 최근 30일 검색수 "
    "눈금에 맞춘 추정치(PC+모바일)이며, 브랜드 값은 브랜드명·대표 제품명 검색의 합입니다. 눈금은 "
    "매일 다시 맞추므로 다른 날 만든 보고의 절대값과는 비교하지 않습니다.",
    "하루 검색이 약 5건 미만인 키워드·날은 데이터랩이 값을 주지 않아 0으로 더했습니다.",
]


class NoDataForTarget(Exception):
    """기준일에 검색량 데이터가 없다(10:00 수집 전이거나 수집 실패)."""


def round_half_up(x: float) -> int:
    """est_volume은 소수 1자리라 .5가 흔하다. SQL round()와 같게 반올림한다(파이썬 round는 짝수로
    간다)."""
    return int(math.floor(x + 0.5))


def norm_keyword(k: str) -> str:
    return "".join(k.split()).lower()


def dedupe_keywords(keywords: list[str]) -> list[str]:
    """공백을 지운 문자열이 같은 키워드는 먼저 나온 표기 하나만 남긴다."""
    seen: set[str] = set()
    out = []
    for k in keywords:
        n = norm_keyword(k)
        if n not in seen:
            seen.add(n)
            out.append(k.strip())
    return out


def brand_keywords(brand: dict) -> list[str]:
    return dedupe_keywords(brand.get("keywords") or [brand["group_name"]])


def brand_daily(
    points: dict[tuple[str, date], float], keywords: list[str], days: list[date], available: set
) -> core.Values:
    """브랜드의 날짜별 추정 검색수(정수). available에 없는 날은 None(데이터 없음), 있는 날은 값이
    없는 키워드를 0으로 더한다."""
    return {
        # fsum: Python 3.12 sum()의 보정 합산과 같은 값을 3.9에서도 낸다(.5 경계 반올림).
        d: round_half_up(math.fsum(points.get((k, d), 0.0) for k in keywords))
        if d in available
        else None
        for d in days
    }


def share_pct(value: float | None, total: float | None) -> float | None:
    if value is None or not total:
        return None
    return round(100.0 * value / total, 1)


def pp(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(a - b, 1)


def shares(values: list[int | float | None]) -> list[float | None]:
    total = sum(v or 0 for v in values)
    return [share_pct(v, total) for v in values]


def refusal(target: date, uncovered: list[str], last_period: date | None) -> str:
    """기준일 데이터가 없을 때 사용자에게 줄 안내."""
    detail = (
        f"범위 끝을 덮는 검색량 요청이 없는 키워드: {', '.join(uncovered)}"
        if uncovered
        else "기준일 행이 없습니다"
    )
    if last_period is None:
        hint = "수집기가 아직 이 키워드들의 검색량을 받지 않았습니다."
    elif last_period > target:
        hint = f"그날 데이터가 결측입니다(마지막 데이터 {last_period}). 범위 끝을 다른 날로 바꿔 요청하세요."
    else:
        hint = (
            f"마지막 데이터 {last_period}. 검색량은 매일 10:00 수집 뒤에 어제 값이 들어옵니다. "
            f"10:00 이후 다시 요청하거나 범위 끝을 {last_period}까지로 바꿔 요청하세요."
        )
    return f"범위 끝 {target}의 검색량 데이터가 아직 없습니다. {detail}. {hint}"


def build(tenant: dict, target: date, db) -> dict:
    """소스 JSON. 최상위 키는 `buzz.build`와 같고 급증일에 글이 없다. 더해지는 키:
    `brands[].keywords`, 점유율 `brands[].current.share_pct`, `quality`의 `source`·`last_period`·
    `requests[]`·`missing_dates[]`·`keywords[]`·`snapshot_date`·`calibration_window`·`calibration[]`."""
    w = core.build_window(target, tenant.get("range_start"))
    kw_by_brand = {b["group_name"]: brand_keywords(b) for b in tenant["brands"]}
    all_keywords = list(dict.fromkeys(k for ks in kw_by_brand.values() for k in ks))
    load_days = core.days_between(w.load_start, target)

    rows = db.points(all_keywords, w.load_start, target)
    points = {(k, d): float(v) for k, d, v, _ in rows}
    available = {d for _, d, _, _ in rows}
    last_period = db.last_period(all_keywords)
    covered = db.covering_keywords(target)
    uncovered = [k for k in all_keywords if k not in covered]
    if uncovered or target not in available:
        raise NoDataForTarget(refusal(target, uncovered, last_period))

    brands, spikes, counts, before, oor_dates = [], [], {}, {}, {}
    for b in tenant["brands"]:
        keywords = kw_by_brand[b["group_name"]]
        values = brand_daily(points, keywords, load_days, available)
        rec = {
            "name": b["group_name"],
            "role": "자사" if b.get("own") else "경쟁",
            "keywords": keywords,
            "current": core.period_stats(values, w.current),
        }
        brands.append(rec)
        counts[rec["name"]] = [values[d] for d in w.current]
        before[rec["name"]] = [values[d] for d in load_days if d < w.current[0]]
        if oor := [d.isoformat() for d in w.current if values[d] is None]:
            oor_dates[rec["name"]] = oor
        for d in w.current:
            spike, base = core.is_spike(values, d, SPIKE_RATIO, SPIKE_MIN, True)
            if spike:
                spikes.append(
                    {
                        "brand": rec["name"],
                        "role": rec["role"],
                        "date": d.isoformat(),
                        "count": values[d],
                        "baseline_avg7": base,
                        "ratio_x": core.ratio_x(values[d], base),
                        "last_week": values.get(d - timedelta(days=7)),
                        "vs_last_week_pct": core.pct(values[d], values.get(d - timedelta(days=7))),
                    }
                )
    for b, x in zip(brands, shares([b["current"]["total"] for b in brands])):
        b["current"]["share_pct"] = x

    return {
        "tenant": {"id": tenant["tenant_id"], "name": tenant["name"]},
        "kind": KIND,
        "target": target.isoformat(),
        "generated_at": config.now_kst_text(),
        "window": w.to_json(),
        "rules": {
            "count": (
                "브랜드 keywords(띄어쓰기 변형 중복 제거)의 search_volume_daily est_volume 합, "
                "정수 반올림"
            ),
            "spike": f"{core.SPIKE_BASE} {SPIKE_RATIO:g}배 이상이고 {SPIKE_MIN}건 이상",
            "share": "브랜드 기간 합 ÷ 테넌트 브랜드 전체 합",
        },
        "brands": brands,
        "daily": {
            "dates": [d.isoformat() for d in w.current],
            "counts": counts,
            "before": before,
            "incomplete": {},
            "out_of_range": oor_dates,
        },
        "spikes": spikes,
        "quality": search_db.quality(db, kw_by_brand, target, last_period, rows, w.current, counts),
        "footnotes": FOOTNOTES,
    }

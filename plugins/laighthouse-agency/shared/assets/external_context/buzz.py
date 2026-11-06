"""글 단위 언급 소스 집계 공통 — 링크 병합, 소스 JSON 조립. 조회 객체(``docs``·``coverage``·
``fetch_info``)를 받는다.

어떤 글을 1차 건수로 세는지, 급증 기준, 급증일 글 고르는 법은 소스 모듈이 `BuzzSpec`으로 넘긴다.

- 브랜드 대표 검색어 = 설정의 `brand_query`, 없으면 `keywords` 첫 항목(`group_name`이 아니다).
  대표 검색어가 수집 범위 밖인 날은 다른 검색어 글이 있어도 그 브랜드의 날을 "범위 밖"으로 본다.
- 브랜드·일 건수 = 그 브랜드의 검색어들에 걸린 글의 **고유 링크 수**. 한 글이 여러
  검색어(띄어쓰기만 다른 표기 등)에 동시에 걸리므로 검색어별 합은 쓰지 않는다.
- 어떤 검색어라도 `is_complete = false`인 날은 그 브랜드의 그날을 "집계 불완전"으로 표시하고
  합산에서 뺀다. 모든 검색어가 수집 범위 밖인 날(행 없음)은 "수집 데이터 없음"이다.
- 급증은 범위 안의 모든 날에 판정하고(기준선은 `trend_core.py` docstring), 급증일마다 상위 글
  SPIKE_ARTICLES건을 붙인다.
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import trend_config as config
import trend_core as core

SPIKE_ARTICLES = 3
OLDEST = datetime.min.replace(tzinfo=timezone.utc)
_TAG = re.compile(r"<[^>]+>")


@dataclass
class Doc:
    query: str
    link: str
    title: str
    snippet_match: bool
    published_date: date
    published_at: datetime | None
    author: str | None = None


@dataclass
class DayValue:
    count: int | None
    covered_queries: int
    incomplete: bool

    @property
    def usable(self) -> bool:
        return self.count is not None and not self.incomplete


@dataclass
class BuzzSpec:
    """소스별 규칙. counted는 1차 건수에 셀 글, spike_doc은 급증일 글 후보이고, pick이 후보에서
    limit건을 고른다."""

    kind: str
    spike_ratio: float
    spike_min: int
    count_rule: str
    footnotes: list[str]
    counted: Callable[[Doc, list[str]], bool]
    spike_doc: Callable[[Doc, list[str]], bool]
    pick: Callable[[list[Doc], list[str], int], list[dict]]


def clean_title(title: str | None) -> str:
    return html.unescape(_TAG.sub("", title or "")).strip()


def merge_by_link(docs: list[Doc], extra: Callable[[Doc], dict] | None = None) -> list[dict]:
    """같은 링크(여러 검색어에 걸린 같은 글)를 하나로 합친다. 제목·날짜와 extra(소스 전용 값)는
    처음 나온 문서 것이고, snippet_match는 하나라도 참이면 참이다. 시각이 없으면 OLDEST."""
    by_link: dict[str, dict] = {}
    for doc in docs:
        rec = by_link.get(doc.link)
        if rec is None:
            rec = by_link[doc.link] = {
                "title": clean_title(doc.title),
                "link": doc.link,
                "date": doc.published_date,
                "published_at": doc.published_at or OLDEST,
                "snippet_match": False,
            } | (extra(doc) if extra else {})
        rec["snippet_match"] = rec["snippet_match"] or doc.snippet_match
    return list(by_link.values())


def brand_queries(brand: dict) -> list[str]:
    return [q.strip() for q in (brand.get("keywords") or [brand["group_name"]])]


def brand_query(brand: dict) -> str:
    """브랜드 대표 검색어: brand_query, 없으면 keywords 첫 항목."""
    return (brand.get("brand_query") or "").strip() or brand_queries(brand)[0]


def brand_daily(
    docs: list[Doc],
    coverage: dict[tuple[str, date], bool],
    queries: list[str],
    days: list[date],
    rep_query: str | None = None,
    counted: Callable[[Doc], bool] | None = None,
) -> dict[date, DayValue]:
    """브랜드의 날짜별 고유 글 수. coverage는 (query, date) -> is_complete(행이 있는 날만).

    rep_query(대표 검색어)가 범위 밖인 날은 다른 검색어가 있어도 범위 밖이다. counted는 셀 글을
    고르는 조건이며 기본은 snippet_match다.
    """
    counted = counted or (lambda doc: doc.snippet_match)
    by_day: dict[date, set[str]] = defaultdict(set)
    qset = set(queries)
    for doc in docs:
        if doc.query in qset and counted(doc):
            by_day[doc.published_date].add(doc.link)
    out: dict[date, DayValue] = {}
    for d in days:
        covered = [q for q in queries if (q, d) in coverage]
        if not covered or (rep_query is not None and (rep_query, d) not in coverage):
            out[d] = DayValue(None, 0, False)
            continue
        incomplete = any(not coverage[(q, d)] for q in covered)
        out[d] = DayValue(len(by_day.get(d, ())), len(covered), incomplete)
    return out


def usable_values(daily: dict[date, DayValue]) -> core.Values:
    return {d: v.count if v.usable else None for d, v in daily.items()}


def incomplete_days(daily: dict[date, DayValue]) -> set[date]:
    return {d for d, v in daily.items() if v.count is not None and v.incomplete}


def build(tenant: dict, target: date, db, spec: BuzzSpec) -> dict:
    """소스 JSON(범위는 `tenant["range_start"]`~target). 키: `tenant`, `kind`, `target`, `generated_at`,
    `window`(`current`·`spike_from`·`spike_to`), `rules`, `brands[]`(`name`·`role`·`queries`·`current`
    기간 통계), `daily`(`dates[]`, 브랜드별 값 배열 `counts`, 범위 앞 7일 `before`, 해당 날짜만 담은
    `incomplete`·`out_of_range`), `spikes[]`(날짜·브랜드·건수·같은 요일 유형 평균·배수 `ratio_x`(평균이
    0이면 null)·상위 글), `quality`(`warnings`, 공통 `last_fetched_at`, 검색어별 `queries[]`),
    `footnotes`."""
    w = core.build_window(target, tenant.get("range_start"))
    brands = tenant["brands"]
    all_queries = [q for b in brands for q in brand_queries(b)]
    docs = db.docs(all_queries, w.load_start, target)
    coverage = db.coverage(all_queries, w.load_start, target)
    fetch_info = db.fetch_info(all_queries)
    load_days = core.days_between(w.load_start, target)

    result_brands, spikes = [], []
    counts: dict[str, list[int | None]] = {}
    before: dict[str, list[int | None]] = {}
    inc_dates: dict[str, list[str]] = {}
    oor_dates: dict[str, list[str]] = {}
    warnings = []
    for b in brands:
        name, queries, rep_q = b["group_name"], brand_queries(b), brand_query(b)
        qset = set(queries)
        role = "자사" if b.get("own") else "경쟁"
        daily = brand_daily(
            docs, coverage, queries, load_days, rep_q, lambda x, qs=queries: spec.counted(x, qs)
        )
        values, partial = usable_values(daily), incomplete_days(daily)
        brand_docs = [x for x in docs if x.query in qset]
        in_range = {d for d in w.current if daily[d].count is not None}
        rec = {
            "name": name,
            "role": role,
            "queries": queries,
            "current": core.period_stats(values, w.current, partial),
        }
        if not in_range:
            warnings.append(f"{name}: 보고 기간 전체가 대표 검색어 '{rep_q}' 수집 범위 밖입니다.")
        result_brands.append(rec)
        counts[name] = [values[d] for d in w.current]
        before[name] = [values[d] for d in load_days if d < w.current[0]]
        if inc := [d.isoformat() for d in w.current if daily[d].incomplete]:
            inc_dates[name] = inc
        if oor := [d.isoformat() for d in w.current if daily[d].count is None]:
            oor_dates[name] = oor
        for d in w.current:
            spike, base = core.is_spike(values, d, spec.spike_ratio, spec.spike_min, True)
            if spike:
                day_docs = [
                    x for x in brand_docs if x.published_date == d and spec.spike_doc(x, queries)
                ]
                spikes.append(
                    {
                        "brand": name,
                        "role": role,
                        "date": d.isoformat(),
                        "count": values[d],
                        "baseline_avg7": base,
                        "ratio_x": core.ratio_x(values[d], base),
                        "last_week": values.get(d - timedelta(days=7)),
                        "vs_last_week_pct": core.pct(values[d], values.get(d - timedelta(days=7))),
                        "articles": spec.pick(day_docs, queries, SPIKE_ARTICLES),
                    }
                )

    warnings += fetch_warnings(all_queries, fetch_info, target)
    latest = max(
        (i["last_fetched_at"] for i in fetch_info.values() if i.get("last_fetched_at")),
        default=None,
    )
    return {
        "tenant": {"id": tenant["tenant_id"], "name": tenant["name"]},
        "kind": spec.kind,
        "target": target.isoformat(),
        "generated_at": config.now_kst_text(),
        "window": w.to_json(),
        "rules": {
            "count": spec.count_rule,
            "spike": f"{core.SPIKE_BASE} {spec.spike_ratio:g}배 이상이고 {spec.spike_min}건 이상",
        },
        "brands": result_brands,
        "daily": {
            "dates": [d.isoformat() for d in w.current],
            "counts": counts,
            "before": before,
            "incomplete": inc_dates,
            "out_of_range": oor_dates,
        },
        "spikes": spikes,
        "quality": {
            "warnings": warnings,
            "last_fetched_at": latest,
            "queries": [query_info(q, brands, fetch_info.get(q, {}), latest) for q in all_queries],
        },
        "footnotes": spec.footnotes,
    }


def fetch_warnings(queries: list[str], fetch_info: dict[str, dict], target: date) -> list[str]:
    """수집 기록이 없는 검색어, 기준일보다 이른 마지막 수집, 오래된 수집."""
    out, last_dates = [], []
    for q in queries:
        info = fetch_info.get(q)
        if not info:
            out.append(f"검색어 '{q}'는 수집 기록이 없습니다.")
        else:
            last_dates.append(date.fromisoformat(info["last_fetched_at"][:10]))
    if last_dates and target > max(last_dates):
        out.append(
            f"기준일 {target}이 마지막 수집일 {max(last_dates)}보다 늦습니다. "
            "수집기가 아직 그 날짜를 받지 않았습니다."
        )
    if last_dates and min(last_dates) < config.today_kst() - timedelta(days=1):
        out.append(
            f"가장 오래된 마지막 수집일이 {min(last_dates)}입니다"
            "(정기 수집 대상이 아닌 테넌트는 수동 재수집 필요)."
        )
    return out


def query_info(q: str, brands: list[dict], info: dict, latest: str | None) -> dict:
    """검색어별 수집 시작일. 마지막 수집 시각은 공통값(latest)과 다를 때만 남긴다."""
    rec = {
        "query": q,
        "brand": next(b["group_name"] for b in brands if q in brand_queries(b)),
        "first_date": info.get("first_date"),
    }
    if info.get("last_fetched_at") != latest:
        rec["last_fetched_at"] = info.get("last_fetched_at")
    return rec

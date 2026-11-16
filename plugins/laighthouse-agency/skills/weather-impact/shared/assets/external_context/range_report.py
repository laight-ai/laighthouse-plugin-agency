"""외부 요인 skill(naver-search·naver-news·naver-blog)의 날짜 범위 보고 — prepare·build 본체.

skill 폴더의 ``assets/prepare.py``·``assets/build_report.py``가 이 모듈을 부른다. 표준 라이브러리만 쓴다.

prepare: 저장 훅 응답(``get_external_context``, ``start_date = 시작 − 7일``, ``end_date = 끝``) →
소스 집계(``search_aggregate``·``news_trend``·``blog_trend``의 ``build``) → 통합 JSON(``trend_report.combine``)과
facts. facts는 모델이 파트별 요약을 쓰는 유일한 근거다.

- 범위 합계·순위: 브랜드별 범위 합(쓸 수 있는 날이 절반 미만이면 None).
- 끝 7일 vs 앞 7일: 범위가 14일 이상일 때만(범위 안의 끝 7일과 그 앞 7일). 값이 있는 날이 4일 미만이면 합계·변화율이 없고, 날 수(``last7_days``·``prev7_days``)를 함께 낸다.
- 점유율(검색만): 끝 7일, 14일 이상이면 앞 7일 대비 pp. 14일 미만이면 범위 전체.
- 급증: 소스별 배수·최소 건수, 기준선은 직전 7일 중 같은 요일 유형(평일·주말) 평균(범위 안 모든 날).
  급증마다 지난주 같은 요일 값·변화율, 뉴스·블로그는 급증일 상위 기사·글 제목 SPIKE_DOCS건.
- 브랜드별 평일·주말 평균과 지난주 같은 요일 대비 변화율이 가장 큰·작은 날(특이사항 판단용).
- 주요 기사·글 4건: 뉴스·블로그 모두 자사 글 ``topic_clusters``(제목에 대표 검색어가 든 글, 같은 주제
  묶음 크기 순). 없으면 빈 목록 → 화면은 '특이점 없음'.
  같은 규칙으로 TITLE_SAMPLE건까지 제목 표본(광고 성과 영향·평판 위험 판단용)도 facts에 넣는다.

build: 통합 JSON + 모델의 파트별 요약(JSON 배열, 파트는 SKILLS ``parts``) → HTML(``page.py``)을
``~/Downloads/laighthouse-reports/{브랜드}_{skill}_{시작}_{끝}.html``에 쓰고, 요약의 숫자를 JSON·facts와
대조한다(``check_citations``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from html import escape

import blog_trend
import buzz
import check_citations
import news_trend
import page
import responses
import saved
import search_aggregate
import trend_config as config
import trend_core as core
import trend_report

LOOKBACK_DAYS = 7
COMPARE_DAYS = 7
MAX_RANGE_DAYS = 92
TOP_DOCS = 4
# 이 일수 이하 범위는 세 skill 모두 브랜드별 가로 누적 막대, 넘으면 날짜별 꺾은선(11/04 사용자 결정)
SHORT_RANGE_DAYS = 3
SPIKE_DOCS = 3
# 요약 판단(광고 성과 영향·평판 위험)용 자사 제목 표본 수
TITLE_SAMPLE = {"naver-news": 20, "naver-blog": 40}
# 평일·주말 변화율 최대·최소 날을 고르는 최소 건수(소스의 급증 최소 건수)
MIN_COUNT = {
    "search": search_aggregate.SPIKE_MIN,
    "news": news_trend.SPIKE_MIN,
    "blog": blog_trend.SPIKE_MIN,
}
REPORT_DIR = os.path.expanduser("~/Downloads/laighthouse-reports")

SKILLS = {
    "naver-search": {
        "source": "search",
        "kind": "search_volume",
        "module": search_aggregate,
        "label": "네이버 검색량",
        "title": "{brand} 네이버 검색량",
        "chart_title": "브랜드별 일별 추정 검색수",
        "short_title": "브랜드별 추정 검색수",
        "docs": None,
        "parts": ["결론", "근거", "수치"],
        "style": "lead",
    },
    "naver-news": {
        "source": "news",
        "kind": "news",
        "module": news_trend,
        "label": "네이버 뉴스 언급·요약",
        "title": "{brand} 네이버 뉴스 언급",
        "chart_title": "브랜드별 일별 뉴스 기사 수",
        "short_title": "브랜드별 뉴스 기사 수",
        "docs": "{brand} 주요 기사",
        "parts": ["① 언급량 특이사항", "② 광고 성과 영향"],
        "style": "rows",
    },
    "naver-blog": {
        "source": "blog",
        "kind": "blog",
        "module": blog_trend,
        "label": "네이버 블로그 언급·요약",
        "title": "{brand} 네이버 블로그 언급",
        "chart_title": "브랜드별 일별 블로그 글 수",
        "short_title": "브랜드별 블로그 글 수",
        "docs": "{brand} 주요 블로그 글",
        "parts": ["언급량", "광고성과 영향", "평판 리스크"],
        "style": "chips",
    },
}


class Refusal(Exception):
    """사용자에게 그대로 전할 거부(범위 오류, 응답 없음, 기준일 데이터 없음)."""


def parse_range(text: str, today: date) -> tuple[date, date]:
    """``YYYY-MM-DD~YYYY-MM-DD``. 끝은 어제(KST)까지, 길이는 MAX_RANGE_DAYS일까지."""
    try:
        start, end = (date.fromisoformat(x.strip()) for x in text.split("~"))
    except ValueError:
        raise Refusal(f"범위는 YYYY-MM-DD~YYYY-MM-DD로 주세요: {text}") from None
    yesterday = today - timedelta(days=1)
    if start > end:
        raise Refusal(f"범위 시작({start})이 끝({end})보다 늦습니다.")
    if end > yesterday:
        raise Refusal(f"범위 끝은 어제({yesterday})까지만 가능합니다: {end}")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise Refusal(f"범위는 최대 {MAX_RANGE_DAYS}일입니다: {(end - start).days + 1}일")
    return start, end


def tool_call(brand: str, kind: str, start: date, end: date) -> dict:
    """skill이 보내는 MCP 호출 인자."""
    return {
        "brand_name": brand,
        "kind": kind,
        "start_date": (start - timedelta(days=LOOKBACK_DAYS)).isoformat(),
        "end_date": end.isoformat(),
    }


# ── facts ─────────────────────────────────────────────────────────────────────


def _share(values: dict) -> dict:
    total = sum(v or 0 for v in values.values())
    return {b: search_aggregate.share_pct(v, total) for b, v in values.items()}


def daytype_stats(dates: list[str], before: list, values: list, minimum: int) -> dict:
    """범위 안 평일·주말 평균(그 유형 날의 절반 미만만 쓸 수 있으면 None)과, 그날이나 지난주 같은 요일 값이
    ``minimum``(그 소스의 급증 최소 건수) 이상인 날 중 지난주 같은 요일 대비 변화율이 가장 큰·작은 날
    (앞 7일 값으로 첫 주도 계산)."""
    days = [date.fromisoformat(d) for d in dates]
    full = dict(zip([days[0] - timedelta(days=len(before) - i) for i in range(len(before))], before))
    full |= dict(zip(days, values))

    def avg(weekend: bool):
        same = [d for d in days if core.is_weekend(d) == weekend]
        v = [full[d] for d in same if full[d] is not None]
        return (round(sum(v) / len(v), 1) if v and 2 * len(v) >= len(same) else None), len(v)

    changes = []
    for d in days:
        last = full.get(d - timedelta(days=7))
        p = core.pct(full[d], last)
        if p is not None and max(full[d], last) >= minimum:
            changes.append({"date": d.isoformat(), "count": full[d], "last_week": last, "pct": p})
    (wd, wd_days), (we, we_days) = avg(False), avg(True)
    return {
        "weekday_avg": wd,
        "weekday_days": wd_days,
        "weekend_avg": we,
        "weekend_days": we_days,
        "vs_last_week_same_day_max": max(changes, key=lambda x: x["pct"], default=None),
        "vs_last_week_same_day_min": min(changes, key=lambda x: x["pct"], default=None),
    }


def make_facts(r: dict, skill: str, top_docs: list, titles: list, brand: str) -> dict:
    """``brand``는 호출의 brand_name(제목·파일명에 그대로 쓴다)."""
    spec = SKILLS[skill]
    source = spec["source"]
    dates = r["daily"]["dates"]
    counts = r["daily"]["counts"][source]
    before = r["daily"]["before"]
    brands = [b for b in r["brands"] if b.get(source)]
    rows = []
    for b in brands:
        cur = b[source]["current"]
        rows.append(
            {
                "name": b["name"],
                "role": b["role"],
                "total": cur["total"],
                "days_with_data": cur["days"],
                "daily_avg": cur["avg"],
                "peak": cur["peak"],
            }
            | daytype_stats(dates, before.get(b["name"], []), counts[b["name"]], MIN_COUNT[source])
        )
    by_name = {x["name"]: x for x in rows}

    def daytype_x(name: str, d: str, count) -> float | None:
        """그날 값 ÷ 그 브랜드의 범위 평일(주말이면 주말) 평균."""
        x = by_name.get(name) or {}
        base = x.get("weekend_avg" if core.is_weekend(date.fromisoformat(d)) else "weekday_avg")
        return core.ratio_x(count, base)

    for x in rows:
        pk = x["peak"]
        x["peak_vs_range_daytype_avg_x"] = daytype_x(x["name"], pk["date"], pk["count"]) if pk else None
    # 날 수가 다른 합계는 비교하지 않는다(뉴스·블로그는 언급이 많아 1,000건 한도에 걸린 날이 빠진다).
    # 브랜드마다 날 수가 같으면 범위 합계, 다르면 일평균으로 순위를 매긴다.
    have = [x for x in rows if x["total"] is not None]
    rank_basis = None if not have else "total" if len({x["days_with_data"] for x in have}) == 1 else "daily_avg"
    ranked = sorted(have, key=lambda x: -x[rank_basis]) if have else []
    for i, x in enumerate(ranked, 1):
        x["rank"] = i
    facts = {
        "brand": brand,
        "skill": skill,
        "metric": trend_report.LABEL[source],
        "range": {"start": dates[0], "end": dates[-1], "days": len(dates)},
        "brands": rows,
        "brand_count": len(rows),
        "leader": ranked[0]["name"] if ranked else None,
        "rank_basis": rank_basis,
        "rank_rule": "브랜드마다 쓸 수 있는 날 수가 같으면 범위 합계(total), 다르면 일평균(daily_avg) 순위",
        "last7_vs_prev7": None,
        "spike_rule": r["sources"][source]["spike"],
        "spikes": [
            {
                "date": s["date"],
                "brand": s["brand"],
                "count": s["count"],
                "baseline_same_daytype_avg": s["baseline_avg7"],
                "ratio_x": s["ratio_x"],
                "last_week_same_day": s["last_week"],
                "vs_last_week_pct": s["vs_last_week_pct"],
                "vs_range_daytype_avg_x": daytype_x(s["brand"], s["date"], s["count"]),
            }
            | ({"articles": [a["title"] for a in s["articles"][:SPIKE_DOCS]]} if "articles" in s else {})
            for s in r["spikes"][source]
        ],
        "top_docs": top_docs,
        "title_sample": titles,
        "data_status": r["quality"]["notes"],
    }
    if len(dates) >= 2 * COMPARE_DAYS:
        days = [date.fromisoformat(d) for d in dates]
        last_days, prev_days = days[-COMPARE_DAYS:], days[-2 * COMPARE_DAYS : -COMPARE_DAYS]
        stats = {}
        for b, v in counts.items():
            values = dict(zip(days, v))
            stats[b] = (core.period_stats(values, last_days), core.period_stats(values, prev_days))
        last = {b: s[0]["total"] for b, s in stats.items()}
        prev = {b: s[1]["total"] for b, s in stats.items()}
        facts["last7_vs_prev7"] = {
            "last7": {"start": dates[-COMPARE_DAYS], "end": dates[-1]},
            "prev7": {"start": dates[-2 * COMPARE_DAYS], "end": dates[-COMPARE_DAYS - 1]},
            "rule": "7일 중 값이 있는 날이 4일 미만이면 합계 없음, 두 구간의 날 수가 다르면 변화율 없음",
            "brands": {
                b: {
                    "last7": last[b],
                    "last7_days": stats[b][0]["days"],
                    "prev7": prev[b],
                    "prev7_days": stats[b][1]["days"],
                    "change_pct": core.pct(last[b], prev[b])
                    if stats[b][0]["days"] == stats[b][1]["days"]
                    else None,
                }
                for b in counts
            },
        }
        if all(
            last[b] is not None and prev[b] is not None and stats[b][0]["days"] == stats[b][1]["days"]
            for b in counts
        ):
            total_last, total_prev = sum(last.values()), sum(prev.values())
            facts["last7_vs_prev7"]["all_brands"] = {
                "last7": total_last, "prev7": total_prev, "change_pct": core.pct(total_last, total_prev),
            }
        if source == "search":
            now, before = _share(last), _share(prev)
            facts["share_last7_pct"] = {
                b: {"share_pct": now[b], "change_pp": search_aggregate.pp(now[b], before[b])}
                for b in counts
            }
    elif source == "search":
        facts["share_range_pct"] = _share({x["name"]: x["total"] for x in rows})
    return facts


# 주제 묶음 핵심어에서 빼는 흔한 말(어느 주제에나 붙어 묶음을 잘못 잇는다)
TOPIC_STOP = {
    "진행", "출시", "돌파", "기념", "관련", "위한", "대한", "이벤트", "혜택", "방법", "정리", "후기",
    "총정리", "확인", "신청", "안내", "추천", "최대", "까지", "부터", "만에", "했다", "한다", "있다",
    "오늘", "카드", "증가", "감소", "상승", "하락", "발표", "개최", "실시",
}
TOPIC_SHARED = 2  # 묶음 첫 글과 겹쳐야 하는 핵심어 수


def topic_words(title: str, brand_query: str) -> set:
    t = buzz.clean_title(title).replace(brand_query, " ")
    return {w for w in re.findall(r"[0-9A-Za-z가-힣]+", t) if len(w) >= 2 and w not in TOPIC_STOP}


def topic_clusters(docs: list, brand_query: str, limit: int) -> list[dict]:
    """제목에 브랜드 대표 검색어가 든 글만, 최신 글부터 핵심어가 가장 많이 겹치는 묶음의 첫 글과
    TOPIC_SHARED개 이상 겹치면 같은 주제로 묶는다. 묶음 크기 → 최신순, 대표는 가장 최신 글.

    shortcut: 핵심어는 공백·기호로 자른 낱말이라 조사가 붙은 표기는 다른 낱말로 본다. 묶음이 갈리는
    사례가 많으면 형태소 단위로 바꾼다. 첫 글하고만 비교해 다른 주제가 사슬처럼 이어지지 않게 했다.
    """
    recs = [r for r in buzz.merge_by_link(docs) if brand_query in r["title"]]
    recs.sort(key=lambda r: (r["published_at"], r["date"], r["link"]), reverse=True)
    groups: list[dict] = []
    for r in recs:
        words = topic_words(r["title"], brand_query)
        best = max(groups, key=lambda g: len(words & g["words"]), default=None)
        if best is not None and len(words & best["words"]) >= TOPIC_SHARED:
            best["members"].append(r)
        else:
            groups.append({"words": words, "members": [r]})
    groups.sort(key=lambda g: (len(g["members"]), g["members"][0]["published_at"]), reverse=True)
    return [
        {
            "title": g["members"][0]["title"],
            "link": g["members"][0]["link"],
            "date": g["members"][0]["date"].isoformat(),
            "same_topic": len(g["members"]),
        }
        for g in groups[:limit]
    ]


def own_docs(db, tenant: dict, skill: str, start: date, end: date) -> tuple[list, list]:
    """자사 주요 기사·글 TOP_DOCS건(근거 카드)과 요약 판단용 제목 표본 TITLE_SAMPLE건(범위 전체에서).
    둘 다 ``topic_clusters``(제목에 브랜드 대표 검색어가 든 글, 같은 주제 묶음 크기 순)다."""
    own = next(b for b in tenant["brands"] if b["own"])
    queries = [q.strip() for q in own["keywords"]]
    picked = topic_clusters(db.docs(queries, start, end), buzz.brand_query(own), TITLE_SAMPLE[skill])
    top = [
        {**{k: a[k] for k in ("title", "link", "date")}, "meta": f"같은 주제 {a['same_topic']}건"}
        for a in picked[:TOP_DOCS]
    ]
    return top, [{k: a[k] for k in ("date", "title", "same_topic")} for a in picked]


def prepare(skill: str, brand: str, rng: str, root: str | None = None) -> dict:
    spec = SKILLS[skill]
    start, end = parse_range(rng, config.today_kst())
    call = tool_call(brand, spec["kind"], start, end)
    try:
        resp = responses.find_response(brand, spec["kind"], call["start_date"], call["end_date"], root)
    except LookupError as e:
        return {"missing": [call], "note": str(e)}
    except ValueError as e:
        return {"errors": [str(e)]}
    own = next((b for b in resp["brands"] if b["role"] == "own"), None)
    if own is None:
        raise Refusal(f"{brand}의 외부 맥락 설정에 자사 브랜드가 없습니다.")
    if spec["source"] == "search" and not own.get("collect_search", True):
        raise Refusal(f"{brand}는 검색량 수집 대상이 아닙니다.")
    tenant = responses.tenant_of(resp, start)
    db = responses.data_of(resp)
    try:
        sub = spec["module"].build(tenant, end, db)
    except search_aggregate.NoDataForTarget as e:
        raise Refusal(str(e)) from None
    r = trend_report.combine({spec["source"]: sub}, tenant)
    r["skill"] = skill
    r["daily"]["before"] = sub["daily"]["before"]
    top, titles = own_docs(db, tenant, skill, start, end) if spec["docs"] else ([], [])
    r["facts"] = make_facts(r, skill, top, titles, brand)
    folder = saved.work_dir(brand, skill, f"{start}_{end}")
    path = os.path.join(folder, "report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False)
    return {"json": path, "facts": r["facts"]}


# ── build ─────────────────────────────────────────────────────────────────────


def brand_total_spec(r: dict, source: str) -> dict:
    """브랜드별 가로 누적 막대(누적 칸 = 날짜). SHORT_RANGE_DAYS 이하 범위."""
    counts, dates = r["daily"]["counts"][source], r["daily"]["dates"]
    names = list(counts)
    toks = [page.token(i) for i in range(len(names))]
    return {
        "type": "bar",
        "data": {
            "labels": [b + (" (자사)" if b == r["own"] else "") for b in names],
            "datasets": [
                {"label": page.md(d), "data": [counts[b][i] for b in names], "toks": toks, "borderWidth": 0}
                for i, d in enumerate(dates)
            ],
        },
        "options": {
            "maintainAspectRatio": False,
            "indexAxis": "y",
            "plugins": {"legend": {"display": False}},
            "scales": {
                "x": {"stacked": True, "title": {"display": True,
                      "text": f"건 ({' + '.join(page.md_short(d) for d in dates)})"}},
                "y": {"stacked": True},
            },
        },
    }


def chart_spec(r: dict, skill: str) -> dict:
    spec = SKILLS[skill]
    source = spec["source"]
    counts = r["daily"]["counts"][source]
    if len(r["daily"]["dates"]) <= SHORT_RANGE_DAYS:
        return brand_total_spec(r, source)
    names = list(counts)
    datasets = []
    for i, b in enumerate(names):
        own = b == r["own"]
        datasets.append(
            {"label": b + (" (자사)" if own else ""), "data": counts[b], "tok": page.token(i),
             "borderWidth": 3 if own else 1.5, "pointRadius": 2 if own else 0, "tension": 0.25}
        )
    return {
        "type": "line",
        "data": {"labels": [page.md(d) for d in r["daily"]["dates"]], "datasets": datasets},
        "options": {
            "maintainAspectRatio": False,
            "interaction": {"mode": "index", "intersect": False},
            "scales": {"y": {"beginAtZero": True, "title": {"display": True, "text": "건"}}},
        },
    }


def build(json_path: str, summary: str, out: str | None = None) -> dict:
    with open(json_path, encoding="utf-8") as f:
        r = json.load(f)
    skill, facts = r["skill"], r["facts"]
    spec = SKILLS[skill]
    brand, rng = facts["brand"], facts["range"]
    label = page.span(rng["start"], rng["end"])
    parts = page.parse_summary(summary, spec["parts"], spec["style"])
    chart_title = spec["short_title"] if rng["days"] <= SHORT_RANGE_DAYS else spec["chart_title"]
    html = page.render(
        [{"title": f"{chart_title} ({label})", "spec": chart_spec(r, skill), "note": " ".join(r["footnotes"])}],
        title=escape(spec["title"].format(brand=brand)),
        skill=escape(spec["label"]),
        summary=page.summary_html(parts, spec["style"], ("수치",)),
        extra=page.docs_card(spec["docs"].format(brand=brand), facts["top_docs"])
        if spec["docs"]
        else "",
    )
    return write_report(f"{brand}_{skill}_{rng['start']}_{rng['end']}", html, parts, [facts], out)


def write_report(name: str, html: str, parts: list, cite_docs: list, out: str | None) -> dict:
    """HTML을 ``out``(없으면 REPORT_DIR/name.html)에 쓰고 요약 숫자를 ``cite_docs``와 대조한다."""
    summary = page.summary_text(parts)
    # 브랜드명은 응답에서 온 글자라 경로 구분자를 지워 REPORT_DIR 밖으로 나가지 않게 한다
    path = out or os.path.join(REPORT_DIR, re.sub(r"[^\w.-]", "_", name) + ".html")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    cited = check_citations.cited_numbers(summary)
    missing = check_citations.missing_numbers(cited, check_citations.allowed_values(cite_docs))
    return {"out": path, "cited_numbers": len(cited), "unmatched_numbers": missing}


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(skill: str, argv: list[str] | None = None) -> int:
    """``prepare --brand B --range S~E`` | ``build --json P [--summary 텍스트|stdin] ``."""
    ap = argparse.ArgumentParser(prog=skill)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--brand", required=True)
    p.add_argument("--range", required=True, help="YYYY-MM-DD~YYYY-MM-DD")
    p.add_argument("--responses", help="응답 폴더(기본: 저장 훅 폴더)")
    b = sub.add_parser("build")
    b.add_argument("--json", required=True, help="prepare가 준 json 경로")
    b.add_argument("--summary", help="SKILL.md 4단계 형식의 요약 JSON 배열(없으면 stdin)")
    b.add_argument("--out", help="HTML 경로(기본 ~/Downloads/laighthouse-reports/…)")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "prepare":
            result = prepare(skill, args.brand, args.range, args.responses)
        else:
            summary = args.summary if args.summary is not None else sys.stdin.read()
            result = build(args.json, summary, args.out)
    except (Refusal, page.SummaryError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0

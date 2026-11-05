"""외부 요인 skill(naver-search·naver-news·naver-blog)의 소스 JSON을 통합 JSON으로 묶는다.

`range_report.prepare`가 소스 JSON(`search_aggregate`·`news_trend`·`blog_trend`의 `build`)을
`combine`에 넘긴다.

통합 JSON 키: `tenant`, `kind`(external-trend), `target`, `generated_at`, `window`, `own`(자사 브랜드
이름), `sources{k: label·count·spike 규칙}`, `brands[]`(`name`·`role`과 소스별 `current` 기간 통계),
`daily`(`dates[]`, 소스별 브랜드별 값 배열 `counts`, 해당 날짜만 담은 `incomplete`·`out_of_range`),
`spikes{k: []}`, `quality`(`warnings`, 모델용 `notes`), `footnotes`. 소스가 없는 브랜드 기록은 null이다.
"""

from __future__ import annotations

import trend_core as core

KIND = "external-trend"
SOURCES = ("search", "news", "blog")
LABEL = {"search": "추정 검색수", "news": "뉴스 기사", "blog": "블로그 글"}
SHORT = {"search": "검색", "news": "뉴스", "blog": "블로그"}
CALIBRATION_WARN_PCT = 10


def source_warnings(subs: dict[str, dict]) -> list[str]:
    return [f"{SHORT[k]}: {w}" for k, r in subs.items() for w in r["quality"]["warnings"]]


def model_notes(subs: dict[str, dict]) -> list[str]:
    """모델만 읽는 데이터 상태: 소스별 경고, 집계 불완전 날, 검색 결측일·눈금 대조."""
    out = source_warnings(subs)
    for k, r in subs.items():
        if inc := r["daily"].get("incomplete"):
            out.append(
                f"{SHORT[k]} 집계 불완전(합산 제외): "
                + "; ".join(f"{b} {', '.join(core.md(d) for d in ds)}" for b, ds in inc.items())
            )
        if k == "search":
            q = r["quality"]
            if q.get("missing_dates"):
                out.append(
                    "검색 표 기간 중 데이터 없는 날: "
                    + ", ".join(core.md(d) for d in q["missing_dates"])
                )
            off = [
                c
                for c in q.get("calibration", [])
                if c["diff_pct"] is not None and abs(c["diff_pct"]) > CALIBRATION_WARN_PCT
            ]
            if off:
                out.append(
                    f"검색 눈금 대조 차이 ±{CALIBRATION_WARN_PCT}% 초과(그 브랜드의 검색수 변화는 "
                    "인용하지 않는다): "
                    + ", ".join(f"{c['brand']} {c['diff_pct']:+,.1f}%" for c in off)
                )
    return out


def combine(subs: dict[str, dict], tenant: dict) -> dict:
    base = next(iter(subs.values()))
    names = [b["group_name"] for b in tenant["brands"]]
    brands = []
    for name in names:
        row: dict = {"name": name}
        for k in SOURCES:
            sb = next((x for x in subs.get(k, {}).get("brands", []) if x["name"] == name), None)
            if sb is not None:
                row["role"] = sb["role"]
            row[k] = {"current": sb["current"]} if sb else None
        brands.append(row)
    own = next((b["name"] for b in brands if b["role"] == "자사"), names[0])
    footnotes = list(dict.fromkeys(f for r in subs.values() for f in r["footnotes"]))
    return {
        "tenant": base["tenant"],
        "kind": KIND,
        "target": base["target"],
        "generated_at": base["generated_at"],
        "window": base["window"],
        "own": own,
        "sources": {
            k: {
                "label": LABEL[k],
                "count": subs[k]["rules"]["count"],
                "spike": subs[k]["rules"]["spike"],
            }
            for k in SOURCES
            if k in subs
        },
        "brands": brands,
        "daily": {
            "dates": base["daily"]["dates"],
            "counts": {k: subs[k]["daily"]["counts"] for k in SOURCES if k in subs},
            "incomplete": {k: subs[k]["daily"]["incomplete"] for k in SOURCES if k in subs},
            "out_of_range": {k: subs[k]["daily"]["out_of_range"] for k in SOURCES if k in subs},
        },
        "spikes": {k: subs[k]["spikes"] for k in SOURCES if k in subs},
        "quality": {"warnings": source_warnings(subs), "notes": model_notes(subs)},
        "footnotes": footnotes,
    }

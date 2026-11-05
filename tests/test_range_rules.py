#!/usr/bin/env python3
"""날짜 범위 보고의 같은 요일 유형 급증 기준선·평일/주말 통계·요약 파트 검증 자체 검사(표준 라이브러리만).

    python3 tests/test_range_rules.py      # 성공하면 "ok"
값은 검사용 고정값이다(보고서에 쓰는 수치가 아니다).
"""

import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "plugins", "laighthouse-agency", "shared", "assets")
sys.path[:0] = [os.path.normpath(os.path.join(KIT, "external_context")), os.path.normpath(KIT)]

import buzz  # noqa: E402
import page  # noqa: E402
import range_report  # noqa: E402
import trend_core as core  # noqa: E402

MON = date(2026, 10, 26)  # 월요일


def week(weekday: int, weekend: int, start: date) -> dict:
    return {start + timedelta(days=i): (weekend if (start + timedelta(days=i)).weekday() >= 5 else weekday)
            for i in range(7)}


def test_monday_after_weekend_is_not_spike():
    values = week(100, 40, MON - timedelta(days=7)) | {MON: 120}
    # 직전 7일 전체 평균(82.9)으로는 1.45배지만, 평일 평균 100 기준으로는 1.2배다.
    assert core.same_daytype_avg(values, MON) == 100.0
    assert core.is_spike(values, MON, 1.4, 10) == (True, core.trailing_avg(values, MON))
    assert core.is_spike(values, MON, 1.4, 10, same_daytype=True) == (False, 100.0)
    sun = MON + timedelta(days=6)
    values = week(100, 40, MON - timedelta(days=7)) | week(100, 40, MON) | {sun: 100}
    assert core.same_daytype_avg(values, sun) == 40.0  # 10/25(일)·10/31(토)
    assert core.is_spike(values, sun, 2.0, 10, same_daytype=True)[0]


def test_daytype_stats_uses_lookback_for_first_week():
    before = [100, 100, 100, 100, 100, 40, 40]  # 10/19(월)~10/25(일)
    dates = [(MON + timedelta(days=i)).isoformat() for i in range(7)]
    got = range_report.daytype_stats(dates, before, [150, 100, 100, 100, 100, 40, 20], 30)
    assert got["weekday_avg"] == 110.0 and got["weekend_avg"] == 30.0, got
    assert got["vs_last_week_same_day_max"] == {"date": "2026-10-26", "count": 150, "last_week": 100, "pct": 50.0}
    assert got["vs_last_week_same_day_min"] == {"date": "2026-11-01", "count": 20, "last_week": 40, "pct": -50.0}
    # 최소 건수 50이면 주말(40·20건, 지난주 40건)은 후보에서 빠진다.
    small = range_report.daytype_stats(dates, before, [150, 100, 100, 100, 100, 40, 20], 50)
    assert small["vs_last_week_same_day_min"]["pct"] == 0.0 and small["vs_last_week_same_day_min"]["date"] < "2026-10-31"
    # 평일 5일 중 2일만 값이 있으면 평균을 내지 않는다.
    sparse = range_report.daytype_stats(dates, before, [150, None, None, None, 100, 40, 20], 30)
    assert sparse["weekday_avg"] is None and sparse["weekday_days"] == 2


def test_summary_parts_must_match_labels_and_style():
    labels = ["언급량", "광고성과 영향"]
    chips = page.parse_summary('[{"head": "없음.", "body": "근거"}, {"head": "없음."}]', labels, "chips")
    assert [p["label"] for p in chips] == labels and chips[1]["body"] == ""
    rows = page.parse_summary('["첫째 문장", "둘째 문장"]', labels, "rows")
    assert rows[0]["body"] == "첫째 문장" and rows[0]["head"] == ""
    for bad, style in (("한 줄 문장", "rows"), ('["하나뿐"]', "rows"), ('[{"head": "x"}, {"head": "y"}]', "rows"),
                       ('["x", "y"]', "chips"), ('[{"body": "x"}, {"head": "y"}]', "chips")):
        try:
            page.parse_summary(bad, labels, style)
        except page.SummaryError:
            continue
        raise AssertionError((bad, style))
    lead = page.summary_html(page.parse_summary('["결론", "근거", "숫자"]', ["결론", "근거", "수치"], "lead"),
                             "lead", ("수치",))
    assert '<span class="sub">근거</span><span class="sub">수치: 숫자</span>' in lead, lead
    cols = page.summary_html(page.parse_summary('["큰 결론", "근거"]', ["① 영향", "② 근거"], "cols"), "cols")
    assert 'class="card sum"' in cols and "한 줄 요약" not in cols and '<p class="big">큰 결론</p>' in cols
    assert "<b>&lt;b&gt;</b>" in page.summary_html([{"label": "x", "head": "<b>", "body": ""}], "chips")


def test_topic_clusters_keep_brand_titles_and_group_topics():
    def doc(i, title, day):
        return buzz.Doc("q", f"https://x/{i}", title, True, date(2026, 10, day), None)

    docs = [
        doc(1, "현대카드 알파벳카드 15만장 돌파", 22),
        doc(2, "현대카드, 독자브랜드 알파벳카드 15만장 넘어", 21),
        doc(3, "인스파이어 아레나 이름 변경", 21),          # 브랜드명이 제목에 없다 → 제외
        doc(4, "현대카드 3분기 순익 2758억 증가", 23),
        doc(5, "현대카드 3분기 민원 증가", 24),             # '3분기·증가'만 겹침 → 증가는 흔한 말이라 따로
        doc(1, "현대카드 알파벳카드 15만장 돌파", 22),      # 같은 링크는 한 건
    ]
    got = __import__("range_report").topic_clusters(docs, "현대카드", 10)
    assert [(g["same_topic"], g["link"]) for g in got][0] == (2, "https://x/1"), got
    assert all("현대카드" in g["title"] for g in got) and len(got) == 3, got


def _spec(labels):
    return {"type": "bar", "data": {"labels": labels, "datasets": [{"label": "a", "data": [1] * len(labels)}]}}


def test_chart_json_cannot_break_out_of_script():
    html = page.render([{"title": "t", "spec": _spec(["<!--<script", "</script><b>x"])}],
                       title="t", skill="s", summary="")
    specs = html.split("const charts = ", 1)[1].split(";\n", 1)[0]
    assert "<" not in specs, specs[:200]


def test_weekend_key_only_for_weekend_date_labels():
    assert "음영 = 주말" not in page.chart_card(0, {"title": "t", "spec": _spec(["일동제약", "토스"])})
    assert "음영 = 주말" in page.chart_card(0, {"title": "t", "spec": _spec(["10/31(토)", "11/1(일)"])})


def test_report_file_stays_in_report_folder():
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        before = range_report.REPORT_DIR
        range_report.REPORT_DIR = os.path.join(root, "reports")
        try:
            out = range_report.write_report("../../evil/A/B_naver-news_x", "<html></html>", [], [{}], None)
        finally:
            range_report.REPORT_DIR = before
        assert os.path.dirname(out["out"]) == os.path.join(root, "reports"), out
        assert os.path.exists(out["out"])


def _range_report(counts: dict) -> dict:
    """make_facts 입력: 14일 범위(10/21~11/3) 뉴스, 브랜드별 일별 값(None = 쓸 수 없는 날)."""
    dates = [(date(2026, 10, 21) + timedelta(days=i)).isoformat() for i in range(14)]
    days = [date.fromisoformat(d) for d in dates]
    brands = []
    for name, v in counts.items():
        stats = core.period_stats(dict(zip(days, v)), days)
        brands.append({"name": name, "role": "자사" if name == "A" else "경쟁", "news": {"current": stats}})
    return {"daily": {"dates": dates, "counts": {"news": counts}, "before": {}}, "brands": brands, "own": "A",
            "sources": {"news": {"spike": "규칙"}}, "spikes": {"news": []}, "quality": {"notes": []}}


def test_unequal_usable_days_are_not_compared():
    full = [10] * 14
    gap = [None] + [12] * 13  # 10/21 하루 빠짐(앞 7일은 6일치), 합계 156 > A 140이지만 날 수가 다르다
    facts = range_report.make_facts(_range_report({"A": full, "B": gap}), "naver-news", [], [], "A")
    cmp = facts["last7_vs_prev7"]
    assert cmp["brands"]["A"]["change_pct"] == 0.0
    assert cmp["brands"]["B"]["prev7_days"] == 6 and cmp["brands"]["B"]["change_pct"] is None
    assert "all_brands" not in cmp
    ranks = {x["name"]: x.get("rank") for x in facts["brands"]}
    assert facts["rank_basis"] == "daily_avg" and ranks == {"B": 1, "A": 2}, ranks  # 일평균 12 > 10
    assert facts["brand"] == "A"

    same = range_report.make_facts(_range_report({"A": [10] * 14, "B": [12] * 14}), "naver-news", [], [], "A")
    assert same["rank_basis"] == "total" and same["last7_vs_prev7"]["all_brands"]["change_pct"] == 0.0

    empty = range_report.make_facts(_range_report({"A": [None] * 14}), "naver-news", [], [], "A")
    assert empty["rank_basis"] is None and empty["leader"] is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

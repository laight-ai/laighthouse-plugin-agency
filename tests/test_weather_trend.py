#!/usr/bin/env python3
"""weather_trend의 유형 판정·비 온 날 지표 차이·저장된 광고 성과 읽기·상관계수 자체 검사(표준 라이브러리만).

    python3 tests/test_weather_trend.py      # 성공하면 "ok"
값은 검사용 고정값이다(보고서에 쓰는 수치가 아니다).
"""

import json
import os
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "plugins", "laighthouse-agency", "shared", "assets")
sys.path[:0] = [os.path.normpath(os.path.join(KIT, "external_context")), os.path.normpath(KIT)]

import saved  # noqa: E402
import weather_trend as wt  # noqa: E402


def test_types_and_missing_discomfort_index():
    assert wt.weather_record("2026-07-09", 28.0, 22.0, 45.0, 24, 76.0, 79.0)["type"] == "폭우·무더위"
    assert wt.weather_record("2026-07-01", 31.0, 24.0, 0.5, 24, 74.0, 74.97)["type"] == "폭염"
    rec = wt.weather_record("2026-07-02", 25.0, 20.0, 3.0, 17, 70.0, 80.0)
    assert rec["type"] == "비(DI 결측)" and rec["di_max"] is None and not rec["muggy"]


def test_rain_gap_compares_same_day_type():
    # 2026-07-06(월)·07(화) 평일, 11(토)·12(일) 주말. 비는 07(평일)·12(주말).
    recs = [wt.weather_record(d, 25, 20, rn, 24, 70, 72) for d, rn in
            [("2026-07-06", 0), ("2026-07-07", 5), ("2026-07-11", 0), ("2026-07-12", 2)]]
    clicks = {"2026-07-06": 100, "2026-07-07": 80, "2026-07-11": 50, "2026-07-12": 45}
    gap = wt.rain_gap(recs, clicks)
    assert [x["change_pct"] for x in gap["rain_days"]] == [-20.0, -10.0]
    assert gap["avg_change_pct"] == -15.0
    assert wt.rain_gap(recs, {}) is None


def test_daily_clicks_from_saved_ad_performance():
    before = saved.ROOT
    try:
        _daily_clicks_case()
    finally:
        saved.ROOT = before


def _daily_clicks_case():
    with tempfile.TemporaryDirectory() as root:
        saved.ROOT = root
        os.makedirs(os.path.join(root, "s1"))
        env = {"metrics": ["클릭", "노출"], "metric_units": {}, "rows": [
            {"date": "2026-07-06", "media": "네이버", "클릭": 60, "노출": 1000},
            {"date": "2026-07-06", "media": "구글", "클릭": 40, "노출": 900},
            {"date": "2026-07-07", "media": "네이버", "클릭": 80, "노출": 1100},
            {"date": "2026-07-07", "media": None, "클릭": 999, "노출": 1},
        ]}
        rec = {"tool_name": "mcp__laighthouse__get_ad_performance", "saved_at": 1,
               "tool_input": {"brand_name": "라형식품", "start_date": "2026-07-06",
                              "end_date": "2026-07-07", "time_grain": "day", "group_by": ["media"]},
               "response": json.dumps(env, ensure_ascii=False)}
        with open(os.path.join(root, "s1", "1_get_ad_performance.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        # 매체끼리 더하지 않는다: 구글은 07-07 행이 없으니 그날 값도 없다(0이 아니다). Organic(media=None)은 뺀다.
        metrics, hidden = wt.daily_metrics("라형식품", date(2026, 7, 6), date(2026, 7, 7))
        assert metrics == {"구글": {"click": {"2026-07-06": 40}},
                           "네이버": {"click": {"2026-07-06": 60, "2026-07-07": 80}}}, metrics
        assert hidden == []
        assert wt.daily_metrics("현대카드", date(2026, 7, 6), date(2026, 7, 7)) == ({}, [])


def test_conversion_rate_and_correlation():
    before = saved.ROOT
    try:
        _conversion_case()
    finally:
        saved.ROOT = before


def _conversion_case():
    with tempfile.TemporaryDirectory() as root:
        saved.ROOT = root
        os.makedirs(os.path.join(root, "s1"))
        # 구글은 전환·매출이 0 또는 값 없음뿐(집계 안 함), 메타는 클릭까지 0뿐(매체째 빠진다).
        env = {"metrics": ["클릭", "전환", "매출"], "metric_units": {}, "rows": [
            {"date": "2026-07-06", "media": "네이버", "클릭": 200, "전환": 4, "매출": 1000},
            {"date": "2026-07-07", "media": "네이버", "클릭": 100, "전환": 3, "매출": 500},
            {"date": "2026-07-06", "media": "구글", "클릭": 50, "전환": 0, "매출": 0},
            {"date": "2026-07-07", "media": "구글", "클릭": 70, "전환": 0, "매출": None},
            {"date": "2026-07-06", "media": "메타", "클릭": 0, "전환": 0, "매출": 0},
        ]}
        rec = {"tool_name": "mcp__laighthouse__get_ad_performance", "saved_at": 1,
               "tool_input": {"brand_name": "라형식품", "start_date": "2026-07-06",
                              "end_date": "2026-07-07", "time_grain": "day", "group_by": ["media"]},
               "response": json.dumps(env, ensure_ascii=False)}
        with open(os.path.join(root, "s1", "1_get_ad_performance.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        m, hidden = wt.daily_metrics("라형식품", date(2026, 7, 6), date(2026, 7, 7))
        assert m["네이버"]["cvr"] == {"2026-07-06": 2.0, "2026-07-07": 3.0}, m
        assert m["네이버"]["revenue"] == {"2026-07-06": 1000, "2026-07-07": 500}
        assert "conversion" not in m["네이버"]
        assert m["구글"] == {"click": {"2026-07-06": 50, "2026-07-07": 70}}, m  # 구매전환율·매출 숨김
        assert "메타" not in m
        assert {(h["media"], h["metric"]) for h in hidden} == {
            ("구글", "cvr"), ("구글", "revenue"), ("메타", "click"), ("메타", "cvr"), ("메타", "revenue")}, hidden
    assert wt.correlation([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == 1.0
    assert wt.correlation([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == -1.0
    assert wt.correlation([1, 2, None, 4], [1, 2, 3, 4]) is None  # 5일 미만


def _weather_root(root: str, rows: list, station_id: int) -> None:
    resp = {"kind": "weather", "tenant": "t", "brand_name": "자사", "start": "2026-07-06", "end": "2026-07-07",
            "source": "kma_asos", "station_id": station_id, "rows": rows}
    rec = {"tool_name": "x__get_external_context", "saved_at": 1, "response": json.dumps(resp),
           "tool_input": {"brand_name": "자사", "kind": "weather",
                          "start_date": "2026-07-06", "end_date": "2026-07-07"}}
    with open(os.path.join(root, "1_get_external_context.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f)


ROW = {"tm": "2026-07-06", "max_ta": 25.0, "min_ta": 20.0, "sum_rn": 0.0, "hours": 24,
       "di_avg": 70.0, "di_max": 72.0, "avg_ta": 22.0}


def test_prepare_refuses_when_no_observation_in_range():
    before = saved.ROOT
    try:
        with tempfile.TemporaryDirectory() as root:
            _weather_root(root, [], 108)
            try:
                wt.prepare("자사", "2026-07-06~2026-07-07", root)
            except wt.Refusal:
                return
    finally:
        saved.ROOT = before
    raise AssertionError("관측값이 없으면 거부해야 한다")


def test_station_label_follows_response():
    before = saved.ROOT
    try:
        for sid, label in ((108, "서울(108)"), (159, "관측소 159")):
            with tempfile.TemporaryDirectory() as root:
                _weather_root(root, [ROW], sid)
                out = wt.prepare("자사", "2026-07-06~2026-07-07", root)
                assert out["facts"]["station"] == label and out["facts"]["station_id"] == sid, out["facts"]
                html_path = os.path.join(root, "r.html")
                wt.build(out["json"], '["a", "b"]', html_path)
                with open(html_path, encoding="utf-8") as f:
                    assert f"(ASOS) {label} 일자료" in f.read()
    finally:
        saved.ROOT = before


def test_prepare_reads_old_ad_performance_from_the_given_folder():
    """--responses 폴더를 주면 광고 성과도 날씨처럼 저장 시각과 상관없이 그 폴더에서 읽는다."""
    with tempfile.TemporaryDirectory() as root:
        _weather_root(root, [ROW], 108)
        env = {"metrics": ["클릭"], "metric_units": {},
               "rows": [{"date": "2026-07-06", "media": "네이버", "클릭": 50}]}
        rec = {"tool_name": "x__get_ad_performance", "saved_at": 1,
               "tool_input": {"brand_name": "자사", "start_date": "2026-07-06",
                              "end_date": "2026-07-07", "time_grain": "day", "group_by": ["media"]},
               "response": json.dumps(env, ensure_ascii=False)}
        path = os.path.join(root, "2_get_ad_performance.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        two_days_ago = os.path.getmtime(path) - 2 * 24 * 3600
        os.utime(path, (two_days_ago, two_days_ago))
        out = wt.prepare("자사", "2026-07-06~2026-07-07", root)
        with open(out["json"], encoding="utf-8") as f:
            metrics = json.load(f)["metrics"]
        assert metrics == {"네이버": {"click": {"2026-07-06": 50}}}, metrics


def test_correlation_direction_follows_sign():
    # rules.md: +0.5 이상 같은 방향, -0.5 이하 반대 방향, 그 사이·없음은 관계 없음
    assert [wt.direction(r) for r in (0.5, 0.9, -0.5, -0.9, 0.49, -0.49, None)] == [
        "same", "same", "opposite", "opposite", "none", "none", "none"]
    mf = {"corr_avg_ta": -0.6, "corr_avg_ta_direction": "opposite"}
    assert "높은 날 광고 클릭도 낮은 경향" in wt.take_text("평균기온", "이", "과", "corr_avg_ta", "광고 클릭", mf)
    mf = {"corr_avg_ta": 0.4, "corr_avg_ta_direction": "none"}
    assert "뚜렷한 관계가 보이지 않습니다" in wt.take_text("평균기온", "이", "과", "corr_avg_ta", "광고 클릭", mf)


def _ad_root(root: str, rows: list, metrics: list) -> None:
    rec = {"tool_name": "x__get_ad_performance", "saved_at": 1,
           "tool_input": {"brand_name": "자사", "start_date": "2026-07-06",
                          "end_date": "2026-07-07", "time_grain": "day", "group_by": ["media"]},
           "response": json.dumps({"metrics": metrics, "metric_units": {}, "rows": rows}, ensure_ascii=False)}
    with open(os.path.join(root, "2_get_ad_performance.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)


def test_missing_media_row_does_not_shrink_baseline():
    """07-06(월) 맑음, 07-07(화) 비. 메타는 07-06 행이 없다.
    합산하면 07-06=100, 07-07=130으로 비 온 날이 +30%가 되지만, 매체별로는 구글 -20%이고 메타는 비교할 날이 없다."""
    with tempfile.TemporaryDirectory() as root:
        _weather_root(root, [ROW, dict(ROW, tm="2026-07-07", sum_rn=5.0)], 108)
        _ad_root(root, [
            {"date": "2026-07-06", "media": "구글", "클릭": 100},
            {"date": "2026-07-07", "media": "구글", "클릭": 80},
            {"date": "2026-07-07", "media": "메타", "클릭": 50},
        ], ["클릭"])
        media = wt.prepare("자사", "2026-07-06~2026-07-07", root)["facts"]["ad_performance"]["media"]
        assert media["구글"]["click"]["rain_gap"]["avg_change_pct"] == -20.0, media
        assert media["메타"]["click"]["rain_gap"] is None, media
        assert media["메타"]["click"]["days_with_data"] == 1


def test_all_media_untracked_falls_back_to_weather_only():
    with tempfile.TemporaryDirectory() as root:
        _weather_root(root, [ROW], 108)
        _ad_root(root, [{"date": "2026-07-06", "media": "구글", "클릭": 0}], ["클릭"])
        ad = wt.prepare("자사", "2026-07-06~2026-07-07", root)["facts"]["ad_performance"]
        assert ad["available"] is False and ad["media"] == {}, ad
        assert ad["hidden"] == [{"media": "구글", "metric": "click"}]


def test_html_draws_one_bar_per_media_and_hides_untracked_metrics():
    with tempfile.TemporaryDirectory() as root:
        _weather_root(root, [ROW, dict(ROW, tm="2026-07-07", sum_rn=5.0)], 108)
        _ad_root(root, [
            {"date": "2026-07-06", "media": "구글", "클릭": 100, "매출": 0},
            {"date": "2026-07-07", "media": "구글", "클릭": 80, "매출": 0},
            {"date": "2026-07-06", "media": "메타", "클릭": 30, "매출": 0},
        ], ["클릭", "매출"])
        out = wt.prepare("자사", "2026-07-06~2026-07-07", root)
        html_path = os.path.join(root, "r.html")
        wt.build(out["json"], '["a", "b"]', html_path)
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
    start = html.index("const charts = ") + len("const charts = ")
    charts = json.loads(html[start:html.index(";\n", start)])
    rain = charts[2]
    assert [d["label"] for d in rain["spec"]["data"]["datasets"] if d["type"] == "bar"] == ["구글", "메타"]
    assert [m["name"] for m in rain["metrics"]] == ["광고 클릭"]  # 매출은 0뿐이라 토글에서 빠진다
    assert rain["metrics"][0]["sets"] == [[100, 80], [30, None]]  # 메타 07-07은 행이 없어 비움
    assert rain["bands"]["idx"] == [1]  # 비 온 07-07 칸에 음영
    assert rain["take"][0].splitlines()[0].startswith("구글: ")
    assert 'class="seg"' not in html  # 지표가 하나면 토글 버튼이 없다
    assert "구글 매출액, 메타 매출액" in html  # 숨긴 지표는 각주에 밝힌다


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

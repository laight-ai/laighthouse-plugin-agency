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
        metrics = wt.daily_metrics("라형식품", date(2026, 7, 6), date(2026, 7, 7))
        assert metrics == {"click": {"2026-07-06": 100, "2026-07-07": 80}}, metrics
        assert wt.daily_metrics("현대카드", date(2026, 7, 6), date(2026, 7, 7)) == {}


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
        env = {"metrics": ["클릭", "전환", "매출"], "metric_units": {}, "rows": [
            {"date": "2026-07-06", "media": "네이버", "클릭": 200, "전환": 4, "매출": 1000},
            {"date": "2026-07-07", "media": "네이버", "클릭": 100, "전환": 3, "매출": 500},
        ]}
        rec = {"tool_name": "mcp__laighthouse__get_ad_performance", "saved_at": 1,
               "tool_input": {"brand_name": "라형식품", "start_date": "2026-07-06",
                              "end_date": "2026-07-07", "time_grain": "day", "group_by": ["media"]},
               "response": json.dumps(env, ensure_ascii=False)}
        with open(os.path.join(root, "s1", "1_get_ad_performance.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        m = wt.daily_metrics("라형식품", date(2026, 7, 6), date(2026, 7, 7))
        assert m.get("cvr") == {"2026-07-06": 2.0, "2026-07-07": 3.0}, m
        assert "conversion" not in m
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

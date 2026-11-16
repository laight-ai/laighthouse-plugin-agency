#!/usr/bin/env python3
"""responses.tenant_of·range_report.parse_range 자체 검사(표준 라이브러리만). 성공하면 "ok"."""

import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "plugins", "laighthouse-agency", "shared", "assets")
sys.path[:0] = [os.path.normpath(os.path.join(KIT, "external_context")), os.path.normpath(KIT)]

import range_report  # noqa: E402
import responses  # noqa: E402

BRANDS = [
    {"name": "자사", "role": "own", "collect_search": True, "keywords": ["자사"], "brand_query": "자사"},
    {"name": "경쟁", "role": "competitor", "collect_search": False, "keywords": ["경쟁"], "brand_query": "경쟁"},
]


def test_search_tenant_keeps_collect_search_companies_only():
    search = responses.tenant_of({"kind": "search_volume", "tenant": "t", "brands": BRANDS})
    news = responses.tenant_of({"kind": "news", "tenant": "t", "brands": BRANDS})
    assert [b["group_name"] for b in search["brands"]] == ["자사"]
    assert [b["group_name"] for b in news["brands"]] == ["자사", "경쟁"]
    assert news["name"] == "자사" and news["brands"][0]["own"]


def test_search_refuses_when_no_company_collects_search():
    import json, tempfile
    resp = {"kind": "search_volume", "tenant": "t", "start": "2026-10-14", "end": "2026-11-03",
            "brands": [dict(b, collect_search=False) for b in BRANDS]}
    rec = {"tool_name": "x__get_external_context", "saved_at": 1, "response": json.dumps(resp),
           "tool_input": {"brand_name": "자사", "kind": "search_volume",
                          "start_date": "2026-10-14", "end_date": "2026-11-03"}}
    with tempfile.TemporaryDirectory() as root:
        with open(os.path.join(root, "1_get_external_context.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        try:
            range_report.prepare("naver-search", "자사", "2026-10-21~2026-11-03", root)
        except range_report.Refusal:
            return
    raise AssertionError("거부해야 한다")


def test_parse_range_limits():
    today = date(2026, 11, 4)
    assert range_report.parse_range("2026-10-21~2026-11-03", today) == (date(2026, 10, 21), date(2026, 11, 3))
    for bad in ("2026-11-03~2026-10-21", "2026-10-21~2026-11-04", "2026-01-01~2026-11-03", "어제"):
        try:
            range_report.parse_range(bad, today)
        except range_report.Refusal:
            continue
        raise AssertionError(bad)


def test_find_response_picks_latest_same_call_and_rejects_error_text():
    import json, tempfile
    ti = {"brand_name": "자사", "kind": "news", "start_date": "2026-10-14", "end_date": "2026-11-03"}
    with tempfile.TemporaryDirectory() as root:
        for name, saved_at, body in (
            ("1_get_external_context.json", 1, {"start": "2026-10-14", "mark": "old"}),
            ("2_get_external_context.json", 2, {"start": "2026-10-14", "mark": "new"}),
            ("3_get_external_context.json", 3, {"start": "2026-10-14", "mark": "other call"}),
        ):
            call = dict(ti, end_date="2026-11-02") if saved_at == 3 else ti
            rec = {"tool_name": "x__get_external_context", "saved_at": saved_at,
                   "response": json.dumps(body), "tool_input": call}
            with open(os.path.join(root, name), "w", encoding="utf-8") as f:
                json.dump(rec, f)
        assert responses.find_response("자사", "news", "2026-10-14", "2026-11-03", root)["mark"] == "new"
        with open(os.path.join(root, "4_get_external_context.json"), "w", encoding="utf-8") as f:
            json.dump({"tool_name": "x__get_external_context", "saved_at": 4,
                       "response": "Error: brand not found", "tool_input": ti}, f)
        try:
            responses.find_response("자사", "news", "2026-10-14", "2026-11-03", root)
        except ValueError:
            return
    raise AssertionError("오류 문자열 응답은 ValueError여야 한다")


def test_search_refusal_hint_fits_range_request():
    import search_aggregate
    msg = search_aggregate.refusal(date(2026, 11, 3), [], date(2026, 11, 2))
    assert "--target" not in msg and "범위 끝을 2026-11-02까지" in msg, msg


def test_search_refuses_when_own_brand_is_not_collected():
    import json, tempfile
    brands = [dict(BRANDS[0], collect_search=False), dict(BRANDS[1], collect_search=True)]
    resp = {"kind": "search_volume", "tenant": "t", "start": "2026-10-14", "end": "2026-11-03", "brands": brands}
    rec = {"tool_name": "x__get_external_context", "saved_at": 1, "response": json.dumps(resp),
           "tool_input": {"brand_name": "자사", "kind": "search_volume",
                          "start_date": "2026-10-14", "end_date": "2026-11-03"}}
    with tempfile.TemporaryDirectory() as root:
        with open(os.path.join(root, "1_get_external_context.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        try:
            range_report.prepare("naver-search", "자사", "2026-10-21~2026-11-03", root)
        except range_report.Refusal:
            return
    raise AssertionError("자사가 검색량 수집 대상이 아니면 거부해야 한다(경쟁사를 자사로 보고하면 안 된다)")


def test_news_refuses_when_no_own_brand():
    """자사 없이 저장된 설정(ELT require_own=False)이면 traceback 대신 거부 안내로 끝난다."""
    import json, tempfile
    resp = {"kind": "news", "tenant": "t", "start": "2026-10-14", "end": "2026-11-03",
            "brands": [BRANDS[1]], "coverage": [], "documents": [], "fetch_info": []}
    rec = {"tool_name": "x__get_external_context", "saved_at": 1, "response": json.dumps(resp),
           "tool_input": {"brand_name": "자사", "kind": "news",
                          "start_date": "2026-10-14", "end_date": "2026-11-03"}}
    with tempfile.TemporaryDirectory() as root:
        with open(os.path.join(root, "1_get_external_context.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        try:
            range_report.prepare("naver-news", "자사", "2026-10-21~2026-11-03", root)
        except range_report.Refusal:
            return
    raise AssertionError("자사 브랜드가 없으면 거부해야 한다")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

#!/usr/bin/env python3
"""get_target_progress_v2 응답 읽기(target_response.target_text) 자체 검사(표준 라이브러리만). 빌더 연결은 test_fee_builders.py.
새 서버는 JSON 객체 하나, 옛 서버는 markdown 원문을 준다 — 같은 내용이면 같은 원문으로 읽혀 목표 파서가 같은 값을 낸다.
JSON 고정값은 같은 내용의 원문에서 손으로 옮겼고('-' 칸 = null, included Y/N = true/false) 기대값은 손으로 계산한 값이다. 성공하면 "ok"."""

import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", "plugins", "laighthouse-agency"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PLUGIN, "shared", "assets"))

import fees  # noqa: E402
import report_kit as kit  # noqa: E402
import target_response  # noqa: E402
import saved_responses as sr  # noqa: E402
from test_fees import KEYS, OVERALL_TP, OVERALL_TP_JSON, budget_targets  # noqa: E402
from test_fee_builders import MONTH_TP, MONTH_TP_JSON, NEW_TP, NEW_TP_JSON, OLD_TP  # noqa: E402

_spec = importlib.util.spec_from_file_location("save_responses_hook", os.path.join(PLUGIN, "hooks", "save_responses.py"))
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)

CAMPAIGN = "2609_가상카드 런칭_VRC ~10/5"
TP = f"""month: 2026-10
as_of_date: 2026-10-31
media: all
fee_basis: net

| metric | target | actual | progress_ratio |
| --- | --- | --- | --- |
| cost | 161400000 | 190828604 | 1.1823 |
| revenue | 0 | 0 | 0.0 |
| roas | 0.0 | 0.0 | 0.0 |

| media | campaign_name | included | metric | target | actual | achievement |
| --- | --- | --- | --- | --- | --- | --- |
| Google | - | - | cost | 31300000 | 65858985 | 2.1041 |
| Google | - | - | cpm | 2500 | 2400 | 0.96 |
| Google | {CAMPAIGN} | Y | cpv | 30 | - | - |
| Google | {CAMPAIGN} | Y | cost | 12000000 | 9000000 | 0.75 |
| Google | 브랜드 검색 | N | cost | 5000000 | 4000000 | 0.8 |
| Meta | - | - | cost | 130100000 | 124969619 | 0.9606 |

| media | fee_mode | rate |
| --- | --- | --- |
| Google | commission | 10 |
| Meta | markup | 12.5 |"""
TP_JSON = {
    "status": "ok", "message": None, "month": "2026-10", "as_of_date": "2026-10-31", "media": "all", "fee_basis": "net",
    "summary": [{"metric": "cost", "target": 161400000, "actual": 190828604, "progress_ratio": 1.1823},
                {"metric": "revenue", "target": 0, "actual": 0, "progress_ratio": 0.0},
                {"metric": "roas", "target": 0.0, "actual": 0.0, "progress_ratio": 0.0}],
    "scopes": [
        {"media": "Google", "campaign_name": None, "included": None, "metric": "cost", "target": 31300000, "actual": 65858985,
         "achievement": 2.1041},
        {"media": "Google", "campaign_name": None, "included": None, "metric": "cpm", "target": 2500, "actual": 2400, "achievement": 0.96},
        {"media": "Google", "campaign_name": CAMPAIGN, "included": True, "metric": "cpv", "target": 30, "actual": None, "achievement": None},
        {"media": "Google", "campaign_name": CAMPAIGN, "included": True, "metric": "cost", "target": 12000000, "actual": 9000000,
         "achievement": 0.75},
        {"media": "Google", "campaign_name": "브랜드 검색", "included": False, "metric": "cost", "target": 5000000, "actual": 4000000,
         "achievement": 0.8},
        {"media": "Meta", "campaign_name": None, "included": None, "metric": "cost", "target": 130100000, "actual": 124969619,
         "achievement": 0.9606}],
    "fees": [{"media": "Google", "fee_mode": "commission", "rate": 10}, {"media": "Meta", "fee_mode": "markup", "rate": 12.5}]}
PAIRS = ((TP, TP_JSON), (NEW_TP, NEW_TP_JSON), (MONTH_TP, MONTH_TP_JSON), (OVERALL_TP, OVERALL_TP_JSON))
PLAIN = "No all budget/target available for 2026-10."


def test_json_reads_as_the_same_markdown():
    """JSON 객체 → 옛 서버가 같은 내용으로 내던 원문 그대로(머리 줄·표·빈칸 '-'·Y/N·숫자 표기·수수료가 있을 때만 셋째 표)."""
    for md, obj in PAIRS:
        assert target_response.target_text(obj) == md, obj["as_of_date"]
    assert target_response.target_text(dict(NEW_TP_JSON, fees=[])) == NEW_TP.split("\n\n| media | fee_mode")[0]
    for md in (TP, OLD_TP, PLAIN, ""):   # 옛 서버 원문(cost·cost_net 포함)·한 줄 평문·에러(빈 문자열)는 그대로
        assert target_response.target_text(md) == md
    assert target_response.target_text(None) == ""


def test_wrapped_shapes():
    """호스트·훅이 넘기는 모양 — JSON 문자열(들여쓰기 포함), {"result": …}, content 블록, CallToolResult — 모두 같은 원문."""
    blocks = [{"type": "text", "text": json.dumps(TP_JSON, ensure_ascii=False, indent=2)}]
    for shape in (json.dumps(TP_JSON, ensure_ascii=False), json.dumps(TP_JSON, indent=2), {"result": TP_JSON},
                  json.dumps({"result": TP_JSON}), blocks, json.dumps(blocks),
                  {"content": blocks, "structuredContent": TP_JSON, "isError": False}):
        assert target_response.target_text(shape) == TP, shape
    old = [{"type": "text", "text": OLD_TP}]
    for shape in ({"result": OLD_TP}, json.dumps({"result": OLD_TP}), old, {"content": old}):
        assert target_response.target_text(shape) == OLD_TP, shape
    assert target_response.target_text('{"error": "x"}') == '{"error": "x"}'   # 새 형식도 래퍼도 아닌 JSON 문자열은 그대로(표가 없으니 목표 없음)


NOT_OK = {
    "no_target": PLAIN,
    "no_cost_metric": "No cost metric in the brand's data mart (looked for 광고비, cost); available metrics: impressions.",
    "no_media_dimension": "No 'media' dimension in the brand's data mart, so Meta-only actuals cannot be computed."}


def test_status_not_ok_and_plain_line_mean_no_target():
    """status가 ok가 아닌 응답(키는 모두 있고 목록은 빈다)과 옛 서버의 한 줄 평문은 같은 목표 없음 — 목표·수수료·기준 모두 없다."""
    for status, line in NOT_OK.items():
        obj = dict(TP_JSON, status=status, message=line, summary=[], scopes=[], fees=[])
        for raw in (obj, json.dumps(obj, ensure_ascii=False), line):
            t = target_response.target_text(raw)
            assert t == line, (status, raw)
            assert kit.parse_targets(t, KEYS) == {} and kit.parse_target_progress(t)["cost_target"] is None
            assert budget_targets.parse_budget({"month": "2026-10", "target_progress": t}) == []
            assert fees.served_basis([], [t]) is None and fees.fee_table([], [t]) == {}


def test_saved_hook_response_reads_back():
    """저장 훅(hooks/save_responses.extract_text) → prepare(saved_responses.response_text) → target_text: 도구 응답이 dict(구조화 응답)·
    content 블록·{"result": 원문}(옛 서버 구조화 출력)이어도 같은 원문."""
    cases = [(TP_JSON, TP), ({"content": [{"type": "text", "text": json.dumps(TP_JSON, indent=2)}]}, TP),
             ([{"type": "text", "text": json.dumps(TP_JSON, ensure_ascii=False)}], TP), ({"result": OLD_TP}, OLD_TP), (OLD_TP, OLD_TP)]
    for resp, want in cases:
        saved = hook.extract_text(resp)
        assert isinstance(saved, str) and saved, resp
        assert target_response.target_text(sr.response_text({"response": saved})) == want, resp


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

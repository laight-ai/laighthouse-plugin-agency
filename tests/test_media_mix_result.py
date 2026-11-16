#!/usr/bin/env python3
"""nextmonth-budget-planning 스킬 자체 검사(표준 라이브러리 + node). 성공하면 "ok".

- build_report.py: 저장 훅이 남긴 get_media_mix_job 응답 중 무엇을 고르는지(끝난 응답, 없으면 부를 호출,
  도구 에러), 그리고 응답을 <script> 안에 안전하게 넣는지.
- mm_view.js: 웹 결과 화면(laighthouse-web src/lib/mediaMix.ts)과 같은 계산인지 — 기대값은 손으로 계산한 값이다.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", "plugins", "laighthouse-agency"))
ASSETS = os.path.join(PLUGIN, "skills", "nextmonth-budget-planning", "assets")
FIXTURES = os.path.join(HERE, "fixtures", "media_mix")
sys.path.insert(0, ASSETS)

import build_report  # noqa: E402
import saved_responses as saved  # noqa: E402

BRAND = "테스트"
JOB_ID = "00000002-mock-4000-8000-000000000002"


def fixture(name="job-even.json"):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def polled(job):
    """기본 인자(배분 행 · 진단 없이)로 받은 같은 job 응답."""
    return {k: v for k, v in job.items() if k not in ("allocation", "diagnostics")}


def with_records(records, fn):
    """records = [(tool_input 추가 인자, 응답 본문 str)] 를 오래된 순으로 저장 훅 폴더에 남기고 fn() 결과를 돌려준다."""
    before = saved.ROOT
    root = tempfile.mkdtemp()
    try:
        saved.ROOT = root
        folder = os.path.join(root, "session-1")
        os.makedirs(folder)
        now = time.time()
        for i, (extra, body) in enumerate(records):
            rec = {"tool_name": "mcp__laighthouse__get_media_mix_job", "saved_at": now - 100 + i,
                   "tool_input": dict({"brand_name": BRAND, "job_id": JOB_ID}, **extra), "response": body}
            with open(os.path.join(folder, f"{i}_get_media_mix_job.json"), "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False)
        return fn()
    finally:
        saved.ROOT = before
        shutil.rmtree(root, ignore_errors=True)


def test_a_finished_job_polled_with_default_arguments_is_enough():
    job = polled(fixture())
    picked, as_of, problem = with_records([({}, json.dumps(job))], lambda: build_report.pick_job(BRAND, JOB_ID))
    assert problem is None and picked == job, problem


def test_keeps_a_finished_response_when_a_tool_error_came_after_it():
    # 끝난 job 은 결과가 더 바뀌지 않는다 — 뒤의 호출이 에러여도 받아 둔 결과로 보고서를 만든다
    job = polled(fixture())
    picked, as_of, problem = with_records(
        [({}, json.dumps(job)), ({}, "Upstream timeout.\nmore")], lambda: build_report.pick_job(BRAND, JOB_ID)
    )
    assert problem is None and picked == job, problem


def test_no_response_for_the_job_asks_for_the_call():
    other = "00000003-mock-4000-8000-000000000003"
    picked, as_of, problem = with_records(
        [({}, json.dumps(polled(fixture())))], lambda: build_report.pick_job(BRAND, other)
    )
    assert picked is None
    assert problem == {"missing": f'get_media_mix_job(brand_name="{BRAND}", job_id="{other}")'}, problem


def test_a_running_job_is_reported_as_of_when_it_was_received():
    job = dict(polled(fixture()), status="running", finished_at=None)
    picked, as_of, problem = with_records([({}, json.dumps(job))], lambda: build_report.pick_job(BRAND, JOB_ID))
    assert problem is None and picked["status"] == "running"
    # with_records 는 하나뿐인 기록을 지금으로부터 100초 전에 저장했다
    assert abs(time.time() - 100 - as_of) < 5, as_of


def test_an_older_running_poll_does_not_hide_that_the_job_finished():
    job = fixture()
    running = dict(polled(job), status="running", finished_at=None)
    picked, as_of, problem = with_records(
        [({}, json.dumps(running)), ({}, json.dumps(polled(job)))], lambda: build_report.pick_job(BRAND, JOB_ID)
    )
    assert problem is None and picked["status"] == "succeeded", problem


def test_a_tool_error_is_passed_on():
    picked, as_of, problem = with_records(
        [({}, "Media-mix job not found.\nmore")], lambda: build_report.pick_job(BRAND, JOB_ID)
    )
    assert picked is None and problem == {"error": "Media-mix job not found."}, problem


def test_a_tool_error_after_a_running_poll_is_passed_on():
    # 가장 최근 호출이 에러면 그 전에 받은 진행 중 상태는 지금 상태가 아니다
    running = dict(polled(fixture()), status="running", finished_at=None)
    picked, as_of, problem = with_records(
        [({}, json.dumps(running)), ({}, "Upstream timeout.\nmore")], lambda: build_report.pick_job(BRAND, JOB_ID)
    )
    assert picked is None and problem == {"error": "Upstream timeout."}, problem


def test_no_saved_responses_is_a_note():
    before = saved.ROOT
    try:
        saved.ROOT = tempfile.mkdtemp()
        picked, as_of, problem = build_report.pick_job(BRAND, JOB_ID)
    finally:
        shutil.rmtree(saved.ROOT, ignore_errors=True)
        saved.ROOT = before
    assert picked is None and set(problem) == {"note"}


def test_render_keeps_markup_in_the_data_inside_its_string():
    job = fixture()
    job["warnings"] = ["</script><b>x</b>", "<!--<script>"]
    html = build_report.render(job, "A&lt;B", 1_700_000_000.5)
    # 템플릿의 <script> 둘만 닫히고, 데이터의 < 는 모두 \u003c 로 들어간다(<!--<script 가 블록을 삼키지 못한다)
    assert html.count("</script>") == 2, html.count("</script>")
    assert "\\u003c/script>\\u003cb>x\\u003c/b>" in html and "\\u003c!--\\u003cscript>" in html
    assert "<title>A&amp;lt;B 미디어믹스 2026-04 예산 제안</title>" in html
    assert "window.__MM_AS_OF__ = 1700000000500" in html
    for slot in ("__TITLE__", "__MM_VIEW_CSS__", "__MM_JOB_JSON__", "__MM_AS_OF_MS__", "__MM_VIEW_JS__"):
        assert slot not in html, slot


def test_default_out_names_the_proposal_month():
    out = build_report.default_out("다라 세제/A", fixture())
    assert os.path.basename(out) == "다라_세제_A_media-mix_2026-04_00000002.html", out


def node_eval(expr):
    script = f"const v = require({json.dumps(os.path.join(ASSETS, 'mm_view.js'))}); console.log(JSON.stringify({expr}))"
    return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)


def test_view_calculations_match_the_web_screen():
    if shutil.which("node") is None:
        print("skip: node 없음 — mm_view.js 계산 검사를 건너뛴다")
        return
    summary = [
        {"kind": "optimized", "media": "A", "cost": 100, "revenue": 0, "roas": None},
        {"kind": "optimized", "media": "C", "cost": 300, "revenue": 0, "roas": None},
        {"kind": "optimized", "media": "B", "cost": 300, "revenue": 0, "roas": None},
        {"kind": "optimized", "media": "*", "cost": 700, "revenue": 0, "roas": None},
    ]
    # 제안 비용이 큰 순, 같으면 이름순
    assert node_eval(f"v.summaryTable({json.dumps(summary)}).media") == ["B", "C", "A"]
    # 금액: ROAS 배수 ×100 정수 % / 개수: 성과당 비용 = 1 ÷ 0.01 = ₩100 / 단위 없음: 배수 그대로 유효숫자 세 자리
    assert node_eval("[v.efficiencyText(2.5, '₩'), v.efficiencyText(0.01, '회'), v.efficiencyText(0.00388, null)]") == [
        "250%", "₩100", "0.00388"]
    assert node_eval("[v.outcomeText(1234.4, ' 회 '), v.outcomeText(1234.5, 'KRW'), v.outcomeText(null, '₩')]") == [
        "1,234회", "₩1,235", "–"]
    # 증감률: (110 − 100) ÷ 100 = 10%, 기준 0 이면 없음
    assert node_eval("[v.changeRate(110, 100), v.changeRate(1, 0)]") == [10, None]
    # 초안(draft)은 보이지 않는다 — 현재와 제안만 견준다
    assert node_eval("v.KINDS") == ["current", "optimized"]
    # 제안받을 달의 전월(기준 달) — 1월이면 해가 바뀐다
    assert node_eval("[v.prevMonth('2026-04'), v.prevMonth('2027-01')]") == ["2026-03", "2026-12"]


def test_view_reads_outcome_names_and_the_old_revenue_names():
    if shutil.which("node") is None:
        print("skip: node 없음 — mm_view.js 계산 검사를 건너뛴다")
        return
    # 서버는 성과를 outcome · outcome_per_cost · outcome_unit · outcome_metric 으로 주고, 예전 서버는
    # revenue · roas · revenue_unit · revenue_metric 으로 준다. 어느 쪽이든 같은 값을 읽는다.
    summary = [
        {"kind": "optimized", "media": "*", "cost": 100, "outcome": 250, "outcome_per_cost": 2.5},
        {"kind": "current", "media": "*", "cost": 100, "revenue": 300, "roas": 3},
        {"kind": "current", "media": "A", "cost": 0, "outcome": 5, "outcome_per_cost": None, "roas": 9},
    ]
    table = f"v.summaryTable({json.dumps(summary)})"
    assert node_eval(f"[{table}.total('optimized'), {table}.total('current'), {table}.cell('current', 'A')]") == [
        {"cost": 100, "outcome": 250, "perCost": 2.5},
        {"cost": 100, "outcome": 300, "perCost": 3},
        {"cost": 0, "outcome": 5, "perCost": None},
    ]
    new_job = {"request": {"outcome_metric": "구매수"}, "outcome_unit": "회"}
    old_job = {"request": {"revenue_metric": "매출"}, "revenue_unit": "₩"}
    # 금액이어도 ROAS · 매출이라 부르지 않고 지표 이름으로 부른다
    assert node_eval(f"[v.outcome({json.dumps(new_job)}).eff, v.outcome({json.dumps(old_job)}).eff, "
                     f"v.outcome({json.dumps(old_job)}).label('optimized')]") == ["구매수당 비용", "매출 ÷ 비용", "예상 매출"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

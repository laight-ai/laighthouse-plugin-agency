#!/usr/bin/env python3
"""16MB 초과로 호스트가 읽지 못한 표 데이터 호출 → 기간을 반으로(다시 반으로) 나눠 받아 합치는 흐름 자체 검사(표준 라이브러리만).

    python3 tests/test_oversized_split.py      # 성공하면 "ok"

저장 훅(hooks/save_responses.py)과 종합 리포트 prepare.py를 실제 프로세스로 돌린다 — 임시 폴더를 TEMP로 넘겨
사용자의 저장 응답과 섞이지 않게 한다. 값은 검사용 고정값이다(보고서에 쓰는 수치가 아니다).
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", "plugins", "laighthouse-agency"))
HOOK = os.path.join(PLUGIN, "hooks", "save_responses.py")
PREPARE = os.path.join(PLUGIN, "skills", "overall-summary", "assets", "prepare.py")
TOO_LARGE = ('The response from MCP server "plugin:laighthouse-agency:laighthouse" for tool "get_ad_performance" was larger '
             'than 16MB, so it was not read. The tool may have run: check whether it did before running it again, and when '
             'you run it again, ask for less data.')
FINE = ["media", "campaign_name"]


def env_for(tmp):
    env = dict(os.environ)
    env.update(TEMP=tmp, TMP=tmp, TMPDIR=tmp)
    return env


def call(s, e, group_by=FINE):
    return {"brand_name": "acme", "start_date": str(s), "end_date": str(e), "time_grain": "day", "group_by": group_by}


def envelope(s, e, group_by=FINE):
    days = [s + timedelta(days=i) for i in range((e - s).days + 1)]
    rows = [dict({d: "meta" if d == "media" else "c1" for d in group_by}, date=str(day), cost=1) for day in days]
    return json.dumps({"dimensions": group_by, "metrics": ["cost"], "rows": rows, "row_count": len(rows)})


def hook(tmp, payload):
    base = {"session_id": "split-test", "tool_name": "mcp__plugin_laighthouse-agency_laighthouse__get_ad_performance"}
    subprocess.run([sys.executable, HOOK], input=json.dumps(dict(base, **payload)).encode("utf-8"),
                   env=env_for(tmp), check=True)


def ok(tmp, s, e, group_by=FINE):
    hook(tmp, {"hook_event_name": "PostToolUse", "tool_input": call(s, e, group_by),
               "tool_response": [{"type": "text", "text": envelope(s, e, group_by)}]})


def fail(tmp, s, e, error=TOO_LARGE, group_by=FINE):
    hook(tmp, {"hook_event_name": "PostToolUseFailure", "tool_input": call(s, e, group_by), "error": error})


def prepare(tmp, tables="product"):
    out = subprocess.run([sys.executable, PREPARE, "--brand", "acme", "--target-date", "2026-10-31", "--part", "tables",
                          "--tables", tables], env=env_for(tmp), capture_output=True, check=True)
    return json.loads(out.stdout.decode("utf-8"))


def data_missing(result):
    return [(m["range"], "note" in m) for m in result["missing"] if m.get("group_by") == "FINE_DIMS"]


D = date.fromisoformat


def test_month_over_16mb_is_split_in_halves_then_quarters_and_merged():
    with tempfile.TemporaryDirectory() as tmp:
        ok(tmp, D("2026-09-01"), D("2026-10-31"), ["media"])   # 매체별 일별
        ok(tmp, D("2026-09-01"), D("2026-09-30"))               # 9월은 한 번에 받힌다
        fail(tmp, D("2026-10-01"), D("2026-10-31"))             # 10월은 16MB 초과
        # 같은 달을 그대로 다시 부르라고 하지 않고 반쪽 두 기간(31일 → 16일 + 15일)을 낸다
        assert data_missing(prepare(tmp)) == [("2026-10-01~2026-10-16", True), ("2026-10-17~2026-10-31", True)]

        ok(tmp, D("2026-10-01"), D("2026-10-16"))
        fail(tmp, D("2026-10-17"), D("2026-10-31"))             # 뒤쪽 반도 초과 → 그 반만 다시 반으로(1/4)
        assert data_missing(prepare(tmp)) == [("2026-10-17~2026-10-24", True), ("2026-10-25~2026-10-31", True)]

        ok(tmp, D("2026-10-17"), D("2026-10-24"))
        ok(tmp, D("2026-10-25"), D("2026-10-31"))
        result = prepare(tmp)
        assert result["missing"] == [] and result["errors"] == [], result
        with open(result["base"], encoding="utf-8") as f:
            files = json.load(f)["data"]["json_files"]
        dates = []
        for path in files:
            with open(path, encoding="utf-8") as f:
                dates += [r["date"] for r in json.load(f)["rows"]]
        # 9/1~10/31 하루도 빠지거나 겹치지 않는다(조각 3개 + 9월)
        assert sorted(dates) == [str(D("2026-09-01") + timedelta(days=i)) for i in range(61)], dates
        assert len(files) == 4, files


def test_other_failures_are_not_split_and_one_day_over_16mb_asks_to_drop_dims():
    with tempfile.TemporaryDirectory() as tmp:
        ok(tmp, D("2026-09-01"), D("2026-10-31"), ["media"])
        ok(tmp, D("2026-09-01"), D("2026-09-30"))
        fail(tmp, D("2026-10-01"), D("2026-10-31"), error="Exit code 1\nupstream timeout")
        # 크기 상한이 아닌 실패는 나누지 않는다 — 그 달 그대로 다시 부른다
        assert data_missing(prepare(tmp)) == [("2026-10-01~2026-10-31", False)]

    with tempfile.TemporaryDirectory() as tmp:
        ok(tmp, D("2026-09-01"), D("2026-10-31"), ["media"])
        ok(tmp, D("2026-09-01"), D("2026-09-30"))
        fail(tmp, D("2026-10-01"), D("2026-10-31"))
        ok(tmp, D("2026-10-17"), D("2026-10-31"))
        fail(tmp, D("2026-10-01"), D("2026-10-16"))
        fail(tmp, D("2026-10-01"), D("2026-10-08"))
        ok(tmp, D("2026-10-09"), D("2026-10-16"))
        fail(tmp, D("2026-10-01"), D("2026-10-04"))
        ok(tmp, D("2026-10-05"), D("2026-10-08"))
        fail(tmp, D("2026-10-01"), D("2026-10-02"))
        ok(tmp, D("2026-10-03"), D("2026-10-04"))
        fail(tmp, D("2026-10-01"), D("2026-10-01"))
        ok(tmp, D("2026-10-02"), D("2026-10-02"))
        missing = [m for m in prepare(tmp)["missing"] if m.get("group_by") == "FINE_DIMS"]
        # 하루치도 넘으면 더 나눌 수 없다 — 그날만 차원을 줄여 받으라고 안내한다
        assert [m["range"] for m in missing] == ["2026-10-01~2026-10-01"], missing
        assert "ad_name" in missing[0]["note"]

        ok(tmp, D("2026-10-01"), D("2026-10-01"), ["media", "ad_type"])   # 차원을 줄여 받은 그날
        assert data_missing(prepare(tmp)) == []


PLACE = ["media", "ad_type", "placement"]


def test_too_large_text_in_a_normal_response_is_recorded_as_failure_not_saved():
    with tempfile.TemporaryDirectory() as tmp:
        ok(tmp, D("2026-09-01"), D("2026-10-31"), ["media"])
        ok(tmp, D("2026-09-01"), D("2026-09-30"))
        # 호스트가 실패를 에러 이벤트가 아니라 일반 응답 텍스트로 넘겨도 같은 실패로 기록한다 — 안내문을 응답으로 저장하지 않는다
        hook(tmp, {"hook_event_name": "PostToolUse", "tool_input": call(D("2026-10-01"), D("2026-10-31")),
                   "tool_response": [{"type": "text", "text": TOO_LARGE}]})
        result = prepare(tmp)
        assert result["errors"] == [], result["errors"]
        assert data_missing(result) == [("2026-10-01~2026-10-16", True), ("2026-10-17~2026-10-31", True)]


def place_missing(result):
    return [(m["range"], m.get("note", "")) for m in result["missing"] if m.get("group_by") == "PLACE"]


def test_placement_missing_only_when_split_or_partly_received():
    with tempfile.TemporaryDirectory() as tmp:
        ok(tmp, D("2026-09-01"), D("2026-10-31"), ["media"])
        ok(tmp, D("2026-09-01"), D("2026-09-30"))
        ok(tmp, D("2026-10-01"), D("2026-10-31"))
        # 노출 위치 차원이 없는 브랜드는 Placement를 부르지 않는다 — missing을 내지 않는다
        assert place_missing(prepare(tmp, "place")) == []

        ok(tmp, D("2026-09-01"), D("2026-09-30"), PLACE)
        fail(tmp, D("2026-10-01"), D("2026-10-31"), group_by=PLACE)
        # 10월 Placement가 16MB로 실패 → 반쪽 두 기간을 낸다
        got = place_missing(prepare(tmp, "place"))
        assert [r for r, _ in got] == ["2026-10-01~2026-10-16", "2026-10-17~2026-10-31"], got
        assert all("나눠 받는" in n for _, n in got), got

        ok(tmp, D("2026-10-01"), D("2026-10-16"), PLACE)
        ok(tmp, D("2026-10-17"), D("2026-10-31"), PLACE)
        result = prepare(tmp, "place")
        assert result["missing"] == [] and result["errors"] == [], result
        with open(result["base"], encoding="utf-8") as f:
            assert len(json.load(f)["place"]["json_files"]) == 3   # 9월 + 10월 반쪽 둘


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

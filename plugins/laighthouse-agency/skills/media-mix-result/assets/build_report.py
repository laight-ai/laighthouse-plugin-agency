#!/usr/bin/env python3
"""미디어믹스 결과 보고서 조립기 — 미리 검증된 asset 스크립트.

저장 훅이 남긴 `get_media_mix_job` 응답(include_allocation·include_diagnostics 를 켠 호출)을 그대로
`assets/report-template.html`에 넣고, 그리기 코드(`mm_view.js`)·모양(`mm_view.css`)·Chart.js 를 인라인해 HTML 한 파일을
만든다. 계산과 그리기는 모두 mm_view.js 가 한다(laighthouse-web 결과 화면과 같은 계산) — 이 스크립트는 숫자를 만지지 않는다.

사용법:
  python3 assets/build_report.py --brand <브랜드> --job-id <job id>            (저장 훅이 남긴 응답에서 고른다)
  python3 assets/build_report.py --brand <브랜드> --json <응답 파일>          (저장 훅이 없을 때 — 응답 원문 파일)
  [--out <경로>]   기본: ~/Downloads/laighthouse-reports/{브랜드}_media-mix_{제안 달}_{job id 앞 8자}.html

출력(stdout, JSON 한 줄):
  성공  {"out": 절대경로, "bytes": 크기, "status": job 상태}
  다시 호출 필요  {"missing": "<보낼 호출>"} — 저장된 응답이 없거나, 끝난 job 인데 배분 행·진단이 빠진 응답뿐이다
  응답이 job 이 아님  {"error": "<응답 첫 줄>"} — 도구 에러(권한·없는 job 등)를 그대로 옮긴다
  저장 훅 없음  {"note": ...} — SKILL.md 「저장 훅이 없을 때」대로 --json 으로 다시 부른다
"""
import argparse
import json
import os
import re
import sys
import time
from html import escape

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
# 공용 킷 위치: <스킬>/shared/assets(zip 번들) → <플러그인>/shared/assets(개발 트리)
SHARED_DIRS = [
    os.path.normpath(os.path.join(ASSETS_DIR, "..", "shared", "assets")),
    os.path.normpath(os.path.join(ASSETS_DIR, "..", "..", "..", "shared", "assets")),
]
for _d in SHARED_DIRS:
    if os.path.exists(os.path.join(_d, "saved_responses.py")):
        sys.path.insert(0, _d)
        break
else:
    raise SystemExit("saved_responses.py를 찾을 수 없다 (shared/assets)")
import saved_responses as saved  # noqa: E402

TOOL = "get_media_mix_job"


def call_text(brand, job_id):
    return (f'get_media_mix_job(brand_name="{brand}", job_id="{job_id}", '
            "include_allocation=true, include_diagnostics=true)")


def read_first(dirs, names):
    for d in dirs:
        for name in names:
            path = os.path.join(d, name)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    return f.read()
    raise SystemExit(f"{names[0]}을(를) 찾을 수 없다")


def script_json(value):
    """<script> 안에 넣을 JSON. `<`를 모두 \\u003c 로 적어 데이터 속 `</script>`·`<!--<script` 가 블록을 닫거나 삼키지 못하게
    하고, 줄 구분 문자(U+2028·2029)도 이스케이프한다. JSON 문자열 안에서만 나오므로 값은 그대로다."""
    text = json.dumps(value, ensure_ascii=False)
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def parse_job(text):
    """응답 원문 → job dict. job 이 아니면(도구 에러 문구 등) None."""
    try:
        job = json.loads(saved.unwrap(text))
    except (TypeError, ValueError):
        return None
    return job if isinstance(job, dict) and "status" in job and isinstance(job.get("request"), dict) else None


def is_complete(job):
    """끝난 job 이면 배분 행·진단이 함께 와야 결과 화면과 같은 보고서가 된다. 끝나지 않았으면 상태만으로 충분하다."""
    return job["status"] != "succeeded" or ("allocation" in job and "diagnostics" in job)


def is_current(job):
    """요청이 제안받을 달(target_month)로 오는 지금 API 의 응답인지. 그 전 응답(start_date·cost_basis)은 비용이 Gross 였을
    수 있어 날짜만 메워 그리면 틀린다 — 그리지 않고 다시 받는다. 서버가 저장된 요청을 새 모양으로 바꿔 두었다."""
    return "target_month" in job["request"]


def proposal_month(job):
    """요청의 제안받을 달(YYYY-MM)."""
    return str(job["request"]["target_month"])


def default_out(brand, job):
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", brand).strip("_") or "brand"
    name = f"{safe}_media-mix_{proposal_month(job)}_{str(job.get('id') or 'job')[:8]}.html"
    return os.path.join(os.path.expanduser("~"), "Downloads", "laighthouse-reports", name)


def render(job, brand, as_of):
    """as_of: 응답을 받은 시각(epoch 초). 대기·계산 중 job 의 경과 시간을 HTML 을 여는 시각이 아니라 이 시각으로 센다."""
    html = read_first([ASSETS_DIR], ["report-template.html"])
    values = {
        "__TITLE__": escape(f"{brand} 미디어믹스 {proposal_month(job)} 예산 제안"),
        "__MM_VIEW_CSS__": read_first([ASSETS_DIR], ["mm_view.css"]),
        "__CHART_JS__": read_first([ASSETS_DIR, *SHARED_DIRS], ["chart.umd.min.txt", "chart.umd.min.js"]),
        "__MM_JOB_JSON__": script_json(job),
        "__MM_AS_OF_MS__": str(int(as_of * 1000)),
        "__MM_VIEW_JS__": read_first([ASSETS_DIR], ["mm_view_js.txt", "mm_view.js"]),
    }
    # 한 번에 바꾼다 — 앞에서 넣은 본문(JSON·JS) 안의 같은 글자를 뒤에서 다시 바꾸지 않게
    return re.sub("|".join(re.escape(k) for k in values), lambda m: values[m.group(0)], html)


def pick_job(brand, job_id):
    """저장된 응답 중 이 job 의 것을 골라 (job, 받은 시각, 문제)로 돌려준다.

    가장 최근 응답이 대기·계산 중이면 그것이 지금 상태다. 끝난(succeeded) job 이면 결과가 더 바뀌지 않으므로, 배분 행·진단을 켜고
    받은 응답을 더 오래된 것까지 찾는다(그 뒤에 기본 인자로 한 번 더 부른 응답이 있어도 된다). 없으면 그 호출을 다시 보내라고 한다.
    가장 최근 응답이 도구 에러면 그보다 오래된 대기·계산 중 상태를 쓰지 않고 그 에러를 돌려준다.
    이전 API 형식의 응답(is_current 가 아님)은 건너뛰고, 쓸 응답이 그것뿐이면 다시 받으라고(outdated) 한다."""
    recs = saved.load_records(brand)
    if not recs:
        return None, None, {"note": saved.no_records_note()}
    error, newest, outdated = None, True, False
    for rec in reversed(recs):
        if rec["_tool"] != TOOL or (rec.get("tool_input") or {}).get("job_id") != job_id:
            continue
        text = saved.response_text(rec)
        job = parse_job(text)
        if job is None:
            if newest:
                error = {"error": str(text).strip().split("\n", 1)[0][:300]}
            newest = False
            continue
        if not is_current(job):
            outdated, newest = True, False
            continue
        if job["status"] != "succeeded":
            if newest:
                return job, rec.get("saved_at"), None
            continue   # 끝나기 전에 받은 지난 상태다
        if is_complete(job):
            return job, rec.get("saved_at"), None
        newest = False
    return None, None, error or {("outdated" if outdated else "missing"): call_text(brand, job_id)}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--brand", required=True)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--job-id")
    src.add_argument("--json", help="get_media_mix_job 응답 원문 파일(저장 훅이 없을 때)")
    p.add_argument("--out")
    args = p.parse_args(argv)

    if args.json:
        with open(args.json, encoding="utf-8") as f:
            text = f.read()
        job = parse_job(text)
        if job is None:
            saved.emit({"error": text.strip().split("\n", 1)[0][:300]})
            return
        if not is_current(job):
            saved.emit({"outdated": call_text(args.brand, job.get("id"))})
            return
        if not is_complete(job):
            saved.emit({"missing": call_text(args.brand, job.get("id"))})
            return
        as_of = os.path.getmtime(args.json)   # 응답을 파일로 저장한 시각
    else:
        job, as_of, problem = pick_job(args.brand, args.job_id)
        if problem:
            saved.emit(problem)
            return

    out = os.path.abspath(os.path.expanduser(args.out or default_out(args.brand, job)))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    data = render(job, args.brand, as_of or time.time()).encode("utf-8")
    with open(out, "wb") as f:
        f.write(data)
    saved.emit({"out": out.replace("\\", "/"), "bytes": len(data), "status": job["status"]})


if __name__ == "__main__":
    main()

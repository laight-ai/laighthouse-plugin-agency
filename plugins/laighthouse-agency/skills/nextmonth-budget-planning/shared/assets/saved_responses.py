"""저장 훅이 남긴 MCP 응답 읽기 — 각 스킬의 `assets/prepare.py`가 import 한다(모델이 직접 import 하지 않는다).

플러그인 저장 훅(hooks/save_responses.py)이 laighthouse 응답 원본을 <tmp>/laighthouse_mcp_responses/<session>/에
{tool_name, tool_input, saved_at, response}로 남긴다. prepare.py는 그중 이 브랜드의 응답을 (도구 + 인자)로 골라
빌더 입력(build.json)을 만든다 — 모델이 응답 원문을 읽거나 옮겨 적지 않는다.

부품:
- `load_records(brand)`      이 브랜드의 가장 최근 세션 응답(24시간 이내, 저장 순, 본문은 고를 때 읽는다)
- `pick(recs, tool, **args)` 인자가 맞는 가장 최근 응답 (args 값이 None이면 "인자 생략"과 같다)
- `response_text(rec)`       응답 본문(래퍼·호스트 저장 파일 안내문을 푼 것)
- `Workdir`                  봉투를 작업 폴더에 저장하고 missing·errors를 모은다
- `future_date_error(day)`   보고서 날짜가 오늘(KST) 이후면 이유 문자열(데이터는 어제까지)
"""
import json
import os
import re
import tempfile
import time

ROOT = os.path.join(tempfile.gettempdir(), "laighthouse_mcp_responses")
WORK_ROOT = os.path.join(tempfile.gettempdir(), "laighthouse_prepare")
MAX_AGE = 24 * 3600
SPILL_RE = re.compile(r"Output has been saved to (\S+?)\.?\s*$", re.M)


def unwrap(text):
    """{"result": "<본문>"} 래퍼·[{"type":"text","text":…}] 블록 리스트를 벗긴다."""
    for _ in range(3):
        if not isinstance(text, str) or not text.lstrip().startswith(("{", "[")):
            return text
        try:
            obj = json.loads(text)
        except ValueError:
            return text
        if isinstance(obj, dict) and set(obj) == {"result"}:
            text = obj["result"] if isinstance(obj["result"], str) else json.dumps(obj["result"], ensure_ascii=False)
        elif isinstance(obj, list) and obj and all(isinstance(b, dict) and "text" in b for b in obj):
            text = "\n".join(b["text"] for b in obj)
        else:
            return text
    return text


def response_text(rec):
    text = rec.get("response")
    if text is None and rec.get("_path"):   # 색인으로 고른 기록 — 본문은 이때 읽는다
        try:
            with open(rec["_path"], encoding="utf-8") as f:
                full = json.load(f)
            text, rec["spilled_path"] = full.get("response"), rec.get("spilled_path") or full.get("spilled_path")
        except (OSError, ValueError):
            text = ""
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    m = SPILL_RE.search(text) if len(text) < 5000 else None
    path = rec.get("spilled_path") or (m.group(1) if m else None)
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            pass
    return unwrap(text)


def _session_records(folder, now):
    """세션 폴더의 기록(본문 제외). index.jsonl이 있으면 그것만 읽고, 없으면(색인을 남기지 않는 훅) 파일을 연다."""
    out = []
    index = os.path.join(folder, "index.jsonl")
    if os.path.exists(index):
        with open(index, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                rec["_path"] = os.path.join(folder, rec.get("file", ""))
                out.append(rec)
    else:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if not name.endswith(".json"):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    rec = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return [r for r in out if now - (r.get("saved_at") or 0) <= MAX_AGE]


def load_records(brand):
    """이 브랜드의 응답이 있는 세션 중 **가장 최근 세션**의 기록만(저장 순). 다른 실행의 응답을 섞지 않는다 —
    이번 실행에서 빠진 호출은 옛 응답으로 채워지지 않고 missing으로 드러난다."""
    now, latest = time.time(), []
    try:
        sessions = os.listdir(ROOT)
    except OSError:
        return []
    for s in sessions:
        folder = os.path.join(ROOT, s)
        if not os.path.isdir(folder):
            continue
        recs = [r for r in _session_records(folder, now)
                if isinstance(r.get("tool_input"), dict) and r["tool_input"].get("brand_name") == brand]
        if recs and max(r.get("saved_at") or 0 for r in recs) > max((r.get("saved_at") or 0 for r in latest), default=0):
            latest = recs
    for r in latest:
        r["_tool"] = str(r.get("tool_name") or "").rsplit("__", 1)[-1]
    latest.sort(key=lambda r: r.get("saved_at") or 0)
    return latest


def _norm(key, value):
    if key in ("start_date", "end_date", "as_of_date"):
        return str(value)[:10] if value else None
    if key == "month":
        return str(value)[:7] if value else None
    if key == "time_grain":
        return value or "day"
    if key == "media":
        return None if value in (None, "", "all") else str(value)   # 생략·"all" = 전체
    if key in ("group_by", "filters"):
        return value or None   # [] · {} = 생략
    if key == "day_offset":
        return int(value) if value not in (None, "") else None
    return value


def pick(recs, tool, **args):
    """인자가 모두 맞는 가장 최근 응답. group_by="*"는 "표 데이터(그 밖의 group_by)"다 — None·["media"]·차원 확인이 아닌 것.
    get_ad_performance는 metrics·filters를 생략한 호출만 고른다."""
    for r in reversed(recs):
        if r["_tool"] != tool:
            continue
        ti = r.get("tool_input") or {}
        if tool == "get_ad_performance" and (ti.get("metrics") is not None or ti.get("filters")):
            continue
        ok = True
        for k, want in args.items():
            got = _norm(k, ti.get(k))
            if k == "group_by" and want == "*":
                ok = bool(got) and got != ["media"] and "__list_dimensions__" not in got
            else:
                ok = got == _norm(k, want)
            if not ok:
                break
        if ok:
            return r
    return None


class Workdir:
    """봉투를 작업 폴더에 저장하고 빠진 호출(missing)·에러 응답(errors)을 모은다."""

    def __init__(self, name):
        self.folder = os.path.join(WORK_ROOT, re.sub(r"[^\w.-]", "_", name))
        os.makedirs(self.folder, exist_ok=True)
        self.missing, self.errors = [], []

    def envelope(self, rec, name, call):
        """기록 → {"json_files": [경로]} (봉투가 아니면 errors에 남기고 None). rec이 None이면 missing."""
        if rec is None:
            self.missing.append(call)
            return None
        text = response_text(rec)
        try:
            env = json.loads(text)
        except ValueError:
            env = None
        if not isinstance(env, dict) or not isinstance(env.get("rows"), list):
            self.errors.append({"call": call, "response": str(text).strip().split("\n", 1)[0][:300]})
            return None
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(env, f, ensure_ascii=False)
        return {"json_files": [path.replace("\\", "/")]}

    def text(self, rec, call):
        """목표 응답 원문(한 줄 '목표 없음' 메시지도 그대로). rec이 None이면 missing."""
        if rec is None:
            self.missing.append(call)
            return None
        return response_text(rec)

    def write(self, base):
        path = os.path.join(self.folder, "build.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(base, f, ensure_ascii=False)
        return path.replace("\\", "/")


def emit(obj):
    os.write(1, json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def future_date_error(last_day):
    """보고서 날짜(= 데이터 마지막 날)가 오늘(KST) 이후면 그 이유 — 데이터는 어제까지만 있다. 괜찮으면 None."""
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=9))).date()
    if last_day >= today:
        return f"{last_day}은(는) 아직 데이터가 없다 — 보고서 날짜는 어제({today - timedelta(days=1)})까지만 된다."
    return None


def no_records_note():
    return (f"저장된 응답이 없다({ROOT}) — 저장 훅이 동작하지 않는 환경이다. SKILL.md 「저장 훅이 없을 때」대로 "
            "build.json을 직접 만든다.")

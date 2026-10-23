#!/usr/bin/env python3
"""PostToolUse 캡처 훅: `get_ad_performance`의 대용량 응답을 파일로 우회시킨다.

왜 존재하나: `group_by`에 캠페인/광고그룹/광고 차원(campaign_id/campaign_name/ad_group_id/
ad_group_name/ad_id/ad_name)이 들어간 응답은 수만~수십만 자까지 커진다. 이 원본이 모델
컨텍스트에 통째로 들어가고, asset 스크립트(build_report.py 등)에 넘기려면 모델이 그 전문을
heredoc으로 **다시 타이핑**해야 했다 — 보고서 생성 시간의 최대 병목이자, "응답이 너무 커서
대체/추정하겠다"는 데이터 무결성 사고의 반복 원인이었다.

무엇을 하나 (Claude Code가 이 훅을 도구 응답 직후, 모델이 보기 전에 실행한다):
1. stdin으로 받은 훅 입력(JSON)에 `tool_input.group_by`(문자열 리스트)가 있고 응답 텍스트가 충분히
   크면(MIN_CHARS 초과), 응답 원본(JSON 봉투 문자열)을 임시 디렉터리에 .json 파일로 저장한다.
   (agency판: TBWA 보고서는 몇 달치 매체별 일별(`["media"]`)·Placement(`["media","ad_type","placement"]`)
   응답도 커서 group_by가 있으면 차원과 관계없이 캡처한다.)
2. `hookSpecificOutput.updatedToolOutput`으로 모델에게 보이는 응답을 "저장 경로 + 행 통계 +
   사용법 + 미리보기" 스텁으로 교체한다 — 원본은 컨텍스트에 들어가지 않는다.
3. 조건에 안 맞으면(작은 응답, group_by 생략/["media"]뿐, 파싱 실패 등) 아무것도 출력하지
   않고 종료한다 → 원본이 그대로 모델에게 전달된다 (안전한 폴백).

응답 형식 참고: `get_ad_performance`는 마크다운 표가 아니라 **JSON 봉투**를 반환한다 —
`{"source": "elt", "tenant": ..., "time_grain": ..., "dimensions": [...], "metrics": [...],
"metric_units": {...}, "row_count": N, "rows": [ {...}, ... ]}`. 저장 파일에도 이 봉투가 그대로 담긴다.
스텁 미리보기에는 `metric_units`(지표별 단위 기호)도 넣는다 — 원본이 컨텍스트에서 빠지는 만큼,
모델이 지표명으로 단위를 추측하지 않도록 이 맵은 남겨 둔다.

이 훅이 실패해도 보고서 생성은 깨지지 않는다 — 응답이 예전처럼 원본 그대로 전달될 뿐이고,
스킬들은 기존 heredoc(`json` 배열) 경로로 동작한다.
"""

import io
import json
import os
import re
import shutil
import sys
import tempfile
import time

# Windows 콘솔 기본 인코딩(cp949)에서도 한글/기호가 깨지지 않도록 항상 UTF-8로 고정
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

MIN_CHARS = 1500  # 이보다 작은 응답은 스텁으로 바꿀 실익이 없다 — 원본 그대로 통과
STALE_SECS = 3 * 24 * 3600  # 3일 지난 세션 캡처 디렉터리는 정리

CAPTURE_ROOT = os.path.join(tempfile.gettempdir(), "laighthouse_mcp_capture")


def extract_text(resp):
    """tool_response에서 텍스트를 꺼낸다 — str / {"text":...} / {"content":[...]} / [블록들]
    어떤 shape이 와도 방어적으로 처리한다."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        if isinstance(resp.get("text"), str):
            return resp["text"]
        if "content" in resp:
            return extract_text(resp["content"])
        return None
    if isinstance(resp, list):
        parts = []
        for block in resp:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts) if parts else None
    return None


def rebuild_like(resp, new_text):
    """updatedToolOutput은 원래 도구 출력과 같은 shape이어야 한다 — 받은 tool_response의
    구조를 그대로 유지한 채 텍스트만 교체해서 돌려준다."""
    if isinstance(resp, str):
        return new_text
    if isinstance(resp, dict):
        if isinstance(resp.get("text"), str):
            out = dict(resp)
            out["text"] = new_text
            return out
        if "content" in resp:
            out = dict(resp)
            out["content"] = rebuild_like(resp["content"], new_text)
            return out
        return new_text
    if isinstance(resp, list):
        return [{"type": "text", "text": new_text}]
    return new_text


def unwrap_json_result(text):
    """Cowork(Claude Desktop)는 툴 응답 본문을 `{"result": "<본문>"}` JSON 문자열로 감싸서
    훅에 넘긴다 — 이대로 저장하면 파서가 봉투 대신 래퍼를 읽는다(실측: 2026-08-12,
    마크다운 시절 section-4가 빈 배열을 반환한 원인). JSON 래퍼면 벗겨서 본문만 돌려주고,
    아니면 그대로 돌려준다. 중첩 래핑도 방어적으로 푼다. `get_ad_performance` 봉투 자체도
    JSON이지만 `result` 키가 없으므로 그대로 통과한다."""
    for _ in range(3):
        if not isinstance(text, str) or not text.lstrip().startswith("{"):
            return text
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text
        if isinstance(obj, dict) and isinstance(obj.get("result"), str):
            text = obj["result"]
        elif isinstance(obj, str):
            text = obj
        else:
            return text
    return text


def envelope_stats(text):
    """JSON 봉투에서 (dimensions, metrics, metric_units, row_count, media별 행 수, 첫 행)을 뽑는다.
    봉투가 아니면 전부 None/빈 값."""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None, None, None, 0, {}, None
    if not isinstance(obj, dict) or not isinstance(obj.get("rows"), list):
        return None, None, None, 0, {}, None
    rows = obj["rows"]
    by_media = {}
    for r in rows:
        if isinstance(r, dict) and "media" in r:
            k = str(r.get("media"))
            by_media[k] = by_media.get(k, 0) + 1
    first_row = rows[0] if rows else None
    return (
        obj.get("dimensions"),
        obj.get("metrics"),
        obj.get("metric_units"),
        obj.get("row_count", len(rows)),
        by_media,
        first_row,
    )


def prune_stale():
    try:
        now = time.time()
        for name in os.listdir(CAPTURE_ROOT):
            p = os.path.join(CAPTURE_ROOT, name)
            if os.path.isdir(p) and now - os.path.getmtime(p) > STALE_SECS:
                shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def _breadcrumb(message):
    """훅이 실행됐는지 여부를 사후 진단할 수 있도록 남기는 한 줄 로그 —
    스텁 교체가 일어나지 않은 실행에서도 '훅 자체는 돌았는가'를 구분하게 해준다."""
    try:
        os.makedirs(CAPTURE_ROOT, exist_ok=True)
        with open(os.path.join(CAPTURE_ROOT, "hook.log"), "a", encoding="utf-8") as f:
            f.write(message + "\n")
    except OSError:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        _breadcrumb("ran: stdin not json — pass-through")
        return  # 입력이 이상하면 조용히 통과

    tool_input = data.get("tool_input") or {}
    group_by = tool_input.get("group_by")
    _breadcrumb(f"ran: tool={data.get('tool_name')} group_by={group_by} session={data.get('session_id')}")
    if not isinstance(group_by, list) or not group_by:
        return  # group_by 생략(총계)은 통과 — 크기는 아래 MIN_CHARS로 거른다

    # 호스트마다 응답 필드명이 다를 수 있다 (Claude Code: tool_response; 다른 호스트 방어)
    resp = None
    resp_field = None
    for field in ("tool_response", "tool_output", "tool_result"):
        if data.get(field) is not None:
            resp = data[field]
            resp_field = field
            break
    if resp is None:
        _breadcrumb(f"skip: no response field; stdin keys={sorted(data.keys())}")
        return

    text = extract_text(resp)
    text = unwrap_json_result(text)
    if not text:
        sample = json.dumps(resp, ensure_ascii=False, default=str)[:400]
        _breadcrumb(f"skip: text extraction failed; field={resp_field} type={type(resp).__name__} sample={sample}")
        return

    # Cowork는 초대형 응답을 스스로 파일로 빼고 "Output has been saved to <경로>" 안내만 넘긴다
    # (실측: 마크다운 시절 naver ad 단위 101,905자 → 1,325자 안내문). 그 파일을 직접 읽어 정상
    # 캡처로 전환한다 — 모델이 offset/limit으로 원본을 더듬는 경로를 원천 차단.
    saved_match = re.search(r"saved to (\S+?\.txt)", text)
    if len(text) <= MIN_CHARS and saved_match:
        saved_path = saved_match.group(1)
        try:
            with open(saved_path, encoding="utf-8") as f:
                redirected = unwrap_json_result(f.read())
        except OSError:
            _breadcrumb(f"skip: oversized notice but cannot read {saved_path} — pass-through")
            return
        if redirected:
            _breadcrumb(f"redirect: oversized output read from {saved_path} chars={len(redirected)}")
            text = redirected

    if len(text) <= MIN_CHARS:
        sample = text[:400].replace("\n", "\\n")
        _breadcrumb(f"skip: small response ({len(text)} chars <= {MIN_CHARS}) sample={sample}")
        return

    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("session_id") or "nosession"))[:48]
    capture_dir = os.path.join(CAPTURE_ROOT, session)
    os.makedirs(capture_dir, exist_ok=True)
    prune_stale()

    filters = tool_input.get("filters") or {}
    media_filter = filters.get("media") if isinstance(filters, dict) else None
    if isinstance(media_filter, list):
        media_filter = "+".join(str(m) for m in media_filter)
    media = str(media_filter or "all")
    grain = str(tool_input.get("time_grain") or "day")
    dims = "-".join(str(d) for d in group_by)
    start = str(tool_input.get("start_date") or "")
    end = str(tool_input.get("end_date") or "")
    seq = len([f for f in os.listdir(capture_dir) if f.endswith(".json")]) + 1
    fname = f"ad_perf_{seq:02d}_{media}_{grain}_{dims}_{start}_{end}.json"
    fname = re.sub(r"[^A-Za-z0-9._-]", "_", fname)
    path = os.path.join(capture_dir, fname)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    _breadcrumb(f"captured: {path} chars={len(text)}")

    dimensions, metrics, metric_units, n_rows, by_media, first_row = envelope_stats(text)
    media_summary = ", ".join(f"{k}={v}" for k, v in sorted(by_media.items())) or "n/a"
    preview_parts = []
    if dimensions is not None:
        preview_parts.append(f"dimensions={json.dumps(dimensions, ensure_ascii=False)}")
    if metrics is not None:
        preview_parts.append(f"metrics={json.dumps(metrics, ensure_ascii=False)}")
    if metric_units is not None:
        preview_parts.append(f"metric_units={json.dumps(metric_units, ensure_ascii=False)}")
    if first_row is not None:
        preview_parts.append(f"첫 행={json.dumps(first_row, ensure_ascii=False)[:400]}")
    preview = "\n".join(preview_parts) or "(JSON 봉투 파싱 실패 — 파일에 원본 그대로 저장됨)"

    stub = (
        f"[laighthouse-capture-hook] 이 도구 응답 원본({len(text):,}자, 데이터 {n_rows}행; "
        f"media={media}, time_grain={grain}, group_by={dims}, {start}~{end})은 아래 파일에 전문 저장됨:\n"
        f"{path}\n"
        f"media별 행 수: {media_summary}\n"
        f"⚠️ 원본을 컨텍스트에 다시 타이핑하지 말 것. asset 스크립트(build_report.py 등)에 넘길 때는 "
        f'{{"json_files": ["{path}", ...]}} 입력 형태(경로 배열)를 heredoc으로 넘기고, '
        f"그 외 집계가 필요하면 Bash(python)에서 이 파일을 직접 읽어 처리한다. "
        f"수치를 요약·추정으로 대체하지 않는다.\n"
        f"미리보기:\n{preview}"
    )

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "updatedToolOutput": rebuild_like(resp, stub),
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

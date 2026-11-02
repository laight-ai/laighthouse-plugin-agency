#!/usr/bin/env python3
"""PostToolUse 저장 훅: laighthouse MCP 응답(get_ad_performance / get_target_progress_v2 /
list_promotions / list_campaign_change_raw)을 원본 그대로 파일로 남긴다.

왜 존재하나: 보고서 스킬은 MCP 호출을 한 메시지에 모두 보낸 뒤 `assets/prepare.py`로 빌더 입력과
요약 근거를 한 번에 만든다. prepare.py는 이 훅이 남긴 파일을 (도구 + 인자)로 골라 읽는다 — 모델이
응답 원문을 읽거나 옮겨 적을 필요가 없다.

- 저장 위치: <tmp>/laighthouse_mcp_responses/<session_id>/<ms>_<도구>.json
- 저장 형식: {tool_name, tool_input, saved_at, response} — laighthouse-plugin-external의 저장 훅
  (save_mcp_response.py)과 같다. 둘 중 어느 훅이 있어도 prepare.py가 동작한다.
- 호스트가 큰 응답을 잘라 "… Output has been saved to <경로>" 안내만 넘기면 그 파일을 읽어 원본을
  저장한다. 읽지 못하면 안내문과 `spilled_path`를 남겨 prepare.py가 다시 시도하게 한다.
- `brand_name` 인자가 없는 같은 이름의 다른 서버 도구는 무시한다.
- 모델에게 보이는 응답은 바꾸지 않는다(stdout 없음). 실패해도 도구 호출을 깨지 않는다(예외 무시).
- 같은 폴더의 index.jsonl에 응답 본문을 뺀 한 줄(도구·인자·저장 시각·파일명)을 덧붙인다.
- 24시간 지난 세션 폴더는 정리한다.
"""

import io
import json
import os
import re
import shutil
import sys
import tempfile
import time

ROOT = os.path.join(tempfile.gettempdir(), "laighthouse_mcp_responses")
STALE_SECS = 24 * 3600
SPILL_RE = re.compile(r"Output has been saved to (\S+?)\.?\s*$", re.M)
SPILL_MAX = 5000      # 안내문은 짧다 — 이보다 긴 텍스트는 데이터로 본다
SPILL_WAIT = 5.0


def extract_text(resp):
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        if isinstance(resp.get("text"), str):
            return resp["text"]
        if "content" in resp:
            return extract_text(resp["content"])
        return json.dumps(resp, ensure_ascii=False)
    if isinstance(resp, list):
        parts = [b if isinstance(b, str) else b.get("text") for b in resp if isinstance(b, (str, dict))]
        parts = [p for p in parts if isinstance(p, str)]
        return "\n".join(parts) if parts else json.dumps(resp, ensure_ascii=False)
    return None


def block_text(text):
    """호스트 저장 파일이 [{"type":"text","text":…}] 블록 리스트면 본문만 꺼낸다."""
    try:
        obj = json.loads(text)
    except ValueError:
        return text
    if isinstance(obj, list) and obj and all(isinstance(b, dict) and isinstance(b.get("text"), str) for b in obj):
        return "\n".join(b["text"] for b in obj)
    return text


def read_spilled(path, wait=SPILL_WAIT):
    deadline = time.time() + wait
    while True:
        try:
            with open(path, encoding="utf-8") as f:
                return block_text(f.read())
        except OSError:
            if time.time() >= deadline:
                return None
            time.sleep(0.25)


def prune():
    now = time.time()
    try:
        for name in os.listdir(ROOT):
            p = os.path.join(ROOT, name)
            if os.path.isdir(p) and now - os.path.getmtime(p) > STALE_SECS:
                shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def main():
    try:
        data = json.load(io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8"))
    except Exception:
        return
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict) or "brand_name" not in tool_input:
        return
    resp = next((data[k] for k in ("tool_response", "tool_output", "tool_result") if data.get(k) is not None), None)
    text = extract_text(resp)
    if not text:
        return
    rec = {"tool_name": str(data.get("tool_name") or ""), "tool_input": tool_input, "saved_at": time.time(), "response": text}
    m = SPILL_RE.search(text) if len(text) < SPILL_MAX else None
    if m:
        full = read_spilled(m.group(1))
        if full:
            rec["response"] = full
        else:
            rec["spilled_path"] = m.group(1)
    session = "".join(c for c in str(data.get("session_id") or "nosession") if c.isalnum() or c in "-_") or "nosession"
    folder = os.path.join(ROOT, session)
    os.makedirs(folder, exist_ok=True)
    name = "%d_%s.json" % (int(time.time() * 1000), rec["tool_name"].rsplit("__", 1)[-1])
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    # 색인: prepare.py가 큰 응답 본문을 열지 않고 (도구 + 인자)로 고르게 한다 — 본문은 고른 것만 읽는다
    meta = {k: v for k, v in rec.items() if k != "response"}
    with open(os.path.join(folder, "index.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(meta, file=name), ensure_ascii=False) + "\n")
    prune()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass

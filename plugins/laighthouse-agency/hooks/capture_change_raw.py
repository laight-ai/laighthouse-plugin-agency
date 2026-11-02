#!/usr/bin/env python3
"""PostToolUse 캡처 훅: `list_campaign_change_raw`(캠페인 변경 이력 원본) 응답을 모델에게는 짧은 안내로 바꿔 보여 준다.

왜 존재하나: 변경 이력은 매체 로그 원본(Google change_event의 old/new 리소스 통째 등)이라 1,000행 페이지 하나가 수십만 자다.
보고서는 저장 훅(save_responses.py)이 남긴 원본을 prepare.py가 읽어 규칙으로 줄을 만든다 — 모델이 원본을 읽을 필요가 없다.
모델이 알아야 하는 것은 다음 페이지가 있는지(`next_cursor`)뿐이다.

무엇을 하나:
1. 응답에서 {"items": [...], "next_cursor": …} 봉투를 꺼낸다(래퍼·호스트의 큰 응답 저장 파일 안내도 푼다).
2. `hookSpecificOutput.updatedToolOutput`으로 "건수(매체·스트림별) + next_cursor + 다음에 할 일" 안내로 바꾼다.
3. 봉투가 아니면(에러 등) 아무것도 출력하지 않는다 → 원본이 그대로 모델에게 간다(안전한 폴백).
"""

import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capture_ad_performance import extract_text, rebuild_like, unwrap_json_result  # noqa: E402  (stdin/stdout을 UTF-8로 맞춘다)


def read_saved(text):
    """호스트가 큰 응답을 파일로 빼고 'saved to <경로>' 안내만 넘기면 그 파일을 읽는다."""
    m = re.search(r"saved to (\S+?\.(?:txt|json))", text)
    if not m or text.lstrip().startswith("{"):
        return text
    path = m.group(1)
    if os.name == "nt" and not path.startswith("\\\\?\\"):
        path = "\\\\?\\" + os.path.abspath(path)
    try:
        with open(path, encoding="utf-8-sig") as f:
            body = f.read()
    except OSError:
        return text
    try:   # 블록 리스트로 저장된 경우
        obj = json.loads(body)
        if isinstance(obj, list) and obj and all(isinstance(b, dict) and isinstance(b.get("text"), str) for b in obj):
            body = "\n".join(b["text"] for b in obj)
    except ValueError:
        pass
    return unwrap_json_result(body)


def main():
    try:
        data = json.load(sys.stdin)
    except (ValueError, UnicodeDecodeError):
        return
    resp = next((data[k] for k in ("tool_response", "tool_output", "tool_result") if data.get(k) is not None), None)
    text = unwrap_json_result(extract_text(resp))
    if not text:
        return
    text = read_saved(text)
    try:
        page = json.loads(text)
    except ValueError:
        return
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        return
    counts = {}
    for it in page["items"]:
        k = f"{it.get('source')}/{it.get('stream')}"
        counts[k] = counts.get(k, 0) + 1
    cur = page.get("next_cursor")
    stub = (f"[laighthouse-capture-hook] 변경 이력 원본 {len(page['items'])}건 저장됨 — 원본은 prepare.py가 읽는다(옮겨 적지 않는다). "
            f"매체/스트림별: {', '.join(f'{k}={v}' for k, v in sorted(counts.items())) or '없음'}\n"
            + (f"next_cursor: {cur}\n다음 페이지가 있다 — 같은 인자에 cursor만 이 값으로 바꿔 다시 부른다."
               if cur else "next_cursor: null — 마지막 페이지다."))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": rebuild_like(resp, stub)}},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:   # 훅이 실패해도 도구 호출은 그대로(원본이 모델에게 간다)
        pass

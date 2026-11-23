#!/usr/bin/env python3
"""PostToolUse 훅: `get_ad_performance` 응답 뒤에 광고 성과 도메인 규칙을 모델 컨텍스트로 넣는다.

왜 존재하나: 모델이 성과 숫자를 해석할 때 매체 상식을 놓친다 — 계약형인 네이버 브랜드검색(BRS)의 예산 증액을 제안하거나,
"광고집행 상품명"(광고 지표)과 "매출발생 상품명"(매출)을 이어 붙여 상품별 ROAS를 만드는 식이다. 스킬은 모델이 골라야
불러오므로 빠질 수 있다. 훅은 도구를 부를 때마다 실행되므로 규칙이 항상 들어간다.

규칙 원문과 절 형식은 `ad_performance_domain.md`(머리 주석)에 있다. 이 파일은 절을 고르고 세션당 한 번만 넣는다.
group_by에 광고집행 상품 차원과 매출발생 상품 차원이 함께 있으면 매번 경고를 붙인다 — 차원 키는 테넌트마다 다르고
한글일 수 있어 키에 든 낱말(`광고집행`·`매출발생`)로 판별한다. 다른 이름을 쓰는 테넌트가 생기면 AD_PRODUCT·SALES_PRODUCT에 더한다.

세션 기록은 (session_id, agent_id)마다 따로 둔다. 컨텍스트 압축 뒤에는 규칙이 요약에서 빠질 수 있으므로, 같은 명령을
SessionStart(matcher `compact`)에도 걸어 두면 그 세션 기록을 지워 다음 호출에 규칙을 다시 넣는다.

`hookSpecificOutput.additionalContext`만 쓰고 응답(updatedToolOutput)은 건드리지 않는다 — 캡처 훅과 함께 돌아도 된다.
어떤 오류가 나도 아무것도 출력하지 않고 끝난다(도구 응답은 그대로 전달된다).
"""

import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capture_ad_performance import block_text, extract_text, unwrap_json_result  # noqa: E402  (stdin/stdout을 UTF-8로 맞춘다)

RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ad_performance_domain.md")
STATE_ROOT = os.environ.get("LAIGHTHOUSE_DOMAIN_HOOK_STATE") or os.path.join(tempfile.gettempdir(), "laighthouse_domain_hook")
STALE_SECS = 3 * 24 * 3600
TAG = "[laighthouse-domain-hook]"
AD_PRODUCT = ("광고집행",)
SALES_PRODUCT = ("매출발생",)


def parse_sections(md):
    """[(제목, 키워드 목록, 본문)] — 키워드가 빈 목록이면 공통 절. 본문의 HTML 주석은 뺀다."""
    md = re.sub(r"\A\s*<!--.*?-->", "", md, flags=re.S)  # 파일 머리 설명
    sections = []
    for block in re.split(r"^## ", md, flags=re.M)[1:]:
        title, _, body = block.partition("\n")
        m = re.search(r"<!--\s*match:(.*?)-->", body, flags=re.S)
        keywords = [k.strip().lower() for k in m.group(1).split(",") if k.strip()] if m else []
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S).strip()
        sections.append((title.strip(), keywords, body))
    return sections


def response_text(data):
    resp = next((data[f] for f in ("tool_response", "tool_output", "tool_result") if data.get(f) is not None), None)
    text = unwrap_json_result(extract_text(resp)) if resp is not None else None
    if not text:
        return ""
    saved = re.search(r"saved to (\S+\.(?:txt|json))", text)  # 호스트가 큰 응답을 파일로 뺀 경우
    if saved and not text.lstrip().startswith("{"):
        path = saved.group(1)
        if os.name == "nt" and not path.startswith("\\\\?\\"):
            path = "\\\\?\\" + os.path.abspath(path)
        try:
            with open(path, encoding="utf-8-sig") as f:
                text = unwrap_json_result(block_text(f.read())) or ""
        except OSError:
            return ""
    return text


def media_values(data, keywords):
    """응답 행의 media 값, 없으면 filters.media — 모두 소문자.

    응답 원문에 남은 매체 키워드가 하나도 없으면 JSON을 파싱하지 않는다(큰 응답을 호출마다 다시 파싱하지 않게).
    원문이 유니코드 이스케이프(백슬래시 u)로 와서 한글 키워드를 원문에서 못 찾을 수 있으면 그대로 파싱한다."""
    values = set()
    text = response_text(data)
    lowered = text.lower()
    if "\\u" in text or any(k in lowered for k in keywords):
        try:
            rows = json.loads(text).get("rows")
            if isinstance(rows, list):
                values = {str(r.get("media")).lower() for r in rows if isinstance(r, dict) and r.get("media")}
        except (ValueError, AttributeError):
            pass
    if not values:
        filters = (data.get("tool_input") or {}).get("filters")
        media = filters.get("media") if isinstance(filters, dict) else None
        if isinstance(media, str):
            media = [media]
        if isinstance(media, list):
            values = {str(m).lower() for m in media}
    return values


def load_sent(path):
    try:
        with open(path, encoding="utf-8") as f:
            sent = json.load(f)
        return set(sent) if isinstance(sent, list) else set()
    except (OSError, ValueError):
        return set()


def save_sent(path, sent):
    sent = sent | load_sent(path)   # 같은 세션의 병렬 호출이 그사이 기록한 절을 지우지 않는다
    try:
        os.makedirs(STATE_ROOT, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"   # 병렬 호출이 반쯤 쓴 파일을 읽지 않게 바꿔 끼운다
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sorted(sent), f, ensure_ascii=False)
        os.replace(tmp, path)
        now = time.time()
        for name in os.listdir(STATE_ROOT):
            p = os.path.join(STATE_ROOT, name)
            if now - os.path.getmtime(p) > STALE_SECS:
                os.remove(p)
    except OSError:
        pass


def safe(value):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(value))[:48]


def session_key(data):
    return safe(data.get("session_id") or "nosession")


def forget_session(data):
    """SessionStart(compact): 압축 요약에서 규칙 본문이 빠질 수 있으므로 그 세션의 기록을 지워 다음 호출에 다시 넣게 한다."""
    prefix = session_key(data) + "__"
    try:
        for name in os.listdir(STATE_ROOT):
            if name.startswith(prefix):
                os.remove(os.path.join(STATE_ROOT, name))
    except OSError:
        pass


def build_context(data):
    with open(RULES, encoding="utf-8") as f:
        sections = parse_sections(f.read())
    # 서브에이전트는 부모와 같은 session_id에 agent_id가 따로 붙는다 — 컨텍스트가 따로라 상태도 따로 둔다
    state = os.path.join(STATE_ROOT, f"{session_key(data)}__{safe(data.get('agent_id') or 'main')}.json")
    sent = load_sent(state)

    pending = [(title, keywords, body) for title, keywords, body in sections if title not in sent]
    remaining = {k for _, keywords, _ in pending for k in keywords}
    media = media_values(data, remaining) if remaining else set()
    new = [(title, body) for title, keywords, body in pending
           if not keywords or any(k in m for k in keywords for m in media)]

    parts = []
    group_by = (data.get("tool_input") or {}).get("group_by") or []
    group_by = [str(d) for d in ([group_by] if isinstance(group_by, str) else group_by)]
    if any(k in d for k in AD_PRODUCT for d in group_by) and any(k in d for k in SALES_PRODUCT for d in group_by):
        parts.append(f"⚠️ 이번 group_by에 광고집행 상품 차원과 매출발생 상품 차원이 함께 있다({group_by}). 두 차원의 교차 행은 해석하지 않는다 — "
                     "광고 지표는 광고집행 상품명으로, 매출은 매출발생 상품명으로 나눠 다시 조회한다.")
    if new:
        parts.append("이 응답을 해석·설명·보고할 때 아래 광고 성과 도메인 규칙을 지킨다.")
        parts.extend(f"## {title}\n{body}" for title, body in new)
        save_sent(state, sent | {title for title, _ in new})
    else:
        titles = ", ".join(t for t, _, _ in sections if t in sent)
        parts.append(f"이 세션에서 앞서 안내한 광고 성과 도메인 규칙{f'({titles})' if titles else ''}을 계속 지킨다.")
    return f"{TAG}\n" + "\n\n".join(parts)


def main():
    try:
        data = json.load(sys.stdin)
        if data.get("hook_event_name") == "SessionStart":
            forget_session(data)
            return
        context = build_context(data)
    except Exception:  # noqa: BLE001 — 훅 실패가 도구 응답을 막으면 안 된다
        return
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

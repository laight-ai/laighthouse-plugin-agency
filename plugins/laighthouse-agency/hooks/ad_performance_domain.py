#!/usr/bin/env python3
"""PostToolUse 훅: `get_ad_performance` 응답 뒤에 광고 성과 도메인 규칙을 모델 컨텍스트로 넣는다.

왜 존재하나: 모델이 성과 숫자를 해석할 때 매체 상식을 놓친다 — 계약형인 네이버 브랜드검색(BRS)의 예산 증액을 제안하거나,
"광고집행 상품명"(광고 지표)과 "매출발생 상품명"(매출)을 이어 붙여 상품별 ROAS를 만드는 식이다. 스킬은 모델이 골라야
불러오므로 빠질 수 있다. 훅은 도구를 부를 때마다 실행되므로 규칙이 항상 들어간다.

규칙 원문과 절 형식은 `ad_performance_domain.md`(머리 주석)에 있다. 이 파일은 절을 고르고 세션당 한 번만 넣는다.
group_by에 광고집행 상품 차원과 매출발생 상품 차원이 함께 있으면 매번 경고를, 한쪽만 있으면 반대 기준도 조회해 한 답에 내라는 안내를 붙인다 — 차원 키는 테넌트마다 다르고
한글일 수 있어 키에 든 낱말(`광고집행`·`매출발생`)로 판별한다. 다른 이름을 쓰는 테넌트가 생기면 AD_PRODUCT·SALES_PRODUCT에 더한다.
응답에 BRS(네이버 브랜드검색) 행이 처음 나오면 합계·ROAS에서 빼라는 경고를 붙인다 — BRS는 광고비를 알 수 없어 합치면 매출만 부풀린다.
규칙 본문처럼 (session_id, agent_id)마다 한 번이다. 같은 내용이 규칙 본문에도 있어 매번 붙이면 토큰만 쌓인다.
쿠팡 행이 있고 조회 종료일이 오늘 − 14일(그날 포함) 이후면 매번 잠정 구간과 확정일을 한 줄로 붙인다 — 날짜가 조회마다 달라 본문으로 대신할 수 없다.
붙일 것이 없으면(규칙을 이미 보냈고 경고 조건도 없으면) 아무것도 출력하지 않는다.

세션 기록은 (session_id, agent_id)마다 따로 둔다. 컨텍스트 압축 뒤에는 규칙이 요약에서 빠질 수 있으므로, 같은 명령을
SessionStart(matcher `compact`)에도 걸어 두면 그 세션 기록을 지워 다음 호출에 규칙을 다시 넣는다.

`hookSpecificOutput.additionalContext`만 쓰고 응답(updatedToolOutput)은 건드리지 않는다 — 캡처 훅과 함께 돌아도 된다.
어떤 오류가 나도 아무것도 출력하지 않고 끝난다(도구 응답은 그대로 전달된다).
"""

import datetime
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
BRS = ("brs", "브랜드검색")   # 원문 사전 검사용. 행 판별은 is_naver_brs
COUPANG = ("coupang", "쿠팡")
COUPANG_LAG_DAYS = 14
BRS_WARNED = "!brs-warned"   # 세션 기록에 절 제목과 함께 둔다(절 제목은 `!`로 시작하지 않는다)
KST = datetime.timezone(datetime.timedelta(hours=9))


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


def today():
    """테스트가 날짜를 고정할 수 있게 LAIGHTHOUSE_DOMAIN_HOOK_TODAY(YYYY-MM-DD)를 먼저 본다."""
    fixed = os.environ.get("LAIGHTHOUSE_DOMAIN_HOOK_TODAY")
    # 광고 데이터 날짜는 한국 기준이다 — UTC로 도는 환경에서도 하루 어긋나지 않게 KST로 센다
    return datetime.date.fromisoformat(fixed) if fixed else datetime.datetime.now(KST).date()


def is_naver_brs(media):
    """매체 값이 네이버 브랜드검색인가 — `BRS` 낱말, 또는 네이버와 함께 쓴 `브랜드검색`(카카오 브랜드검색은 아니다)."""
    return bool(re.search(r"(?<![a-z])brs(?![a-z])", media)) or ("브랜드검색" in media and ("네이버" in media or "naver" in media))


def coupang_lag_note(data):
    """쿠팡 전환은 클릭 후 14일까지 붙는다 — 조회 기간이 그 안에 걸리면 잠정 구간과 확정일을 날짜로 알린다."""
    tool_input = data.get("tool_input") or {}
    try:
        start = datetime.date.fromisoformat(str(tool_input.get("start_date")))
        end = datetime.date.fromisoformat(str(tool_input.get("end_date")))
    except ValueError:
        return None
    # d일 클릭에는 d+14일까지 전환이 붙는다 — 오늘이 d+14일 이하면 d일은 아직 잠정, d+15일부터 확정
    now = today()
    first_open = now - datetime.timedelta(days=COUPANG_LAG_DAYS)
    if end < first_open:
        return None
    first = max(start, first_open)
    final = end + datetime.timedelta(days=COUPANG_LAG_DAYS + 1)
    return f"⏳ 쿠팡 {first}~{end} 전환·매출·주문·ROAS는 잠정(14일 기여 미종료, {final} 확정) — 답 첫머리에 밝히고 하락으로 해석하지 않는다."


def build_context(data):
    with open(RULES, encoding="utf-8") as f:
        sections = parse_sections(f.read())
    # 서브에이전트는 부모와 같은 session_id에 agent_id가 따로 붙는다 — 컨텍스트가 따로라 상태도 따로 둔다
    state = os.path.join(STATE_ROOT, f"{session_key(data)}__{safe(data.get('agent_id') or 'main')}.json")
    sent = load_sent(state)

    pending = [(title, keywords, body) for title, keywords, body in sections if title not in sent]
    remaining = {k for _, keywords, _ in pending for k in keywords}
    media = media_values(data, remaining | set(BRS) | set(COUPANG))
    new = [(title, body) for title, keywords, body in pending
           if not keywords or any(k in m for k in keywords for m in media)]

    parts = []
    record = set()
    if BRS_WARNED not in sent and any(is_naver_brs(m) for m in media):
        record.add(BRS_WARNED)
        parts.append("⚠️ 응답에 BRS(네이버 브랜드검색) 행이 있다. BRS는 계약형이라 광고비가 없거나 실제 계약금과 달라 BRS 매출을 합치면 ROAS가 부풀려진다 — "
                     "네이버·전체 합계와 ROAS는 BRS를 뺀 값으로 내고(\"BRS 제외\"라고 밝힌다), BRS는 별도 행으로 따로 보인다. BRS 광고비가 없거나 0이면 BRS ROAS는 산출하지 않는다.")
    if any(k in m for k in COUPANG for m in media):
        note = coupang_lag_note(data)
        if note:
            parts.append(note)
    group_by = (data.get("tool_input") or {}).get("group_by") or []
    group_by = [str(d) for d in ([group_by] if isinstance(group_by, str) else group_by)]
    has_ad = any(k in d for k in AD_PRODUCT for d in group_by)
    has_sales = any(k in d for k in SALES_PRODUCT for d in group_by)
    if has_ad and has_sales:
        parts.append(f"⚠️ 이번 group_by에 광고집행 상품 차원과 매출발생 상품 차원이 함께 있다({group_by}). 두 차원의 교차 행은 해석하지 않는다 — "
                     "광고 지표는 광고집행 상품명으로, 매출은 매출발생 상품명으로 나눠 다시 조회한다.")
    elif has_ad or has_sales:
        mine, other = ("광고집행", "매출발생") if has_ad else ("매출발생", "광고집행")
        rule = next((t for t, keywords, _ in sections if not keywords and AD_PRODUCT[0] in t), "상품 차원")
        parts.append(f"📌 이번 조회는 {mine} 상품 기준이다. 상품별 분석이면 차원 목록에서 {other} 상품 차원을 찾아 같은 기간·필터로 따로 조회하고, "
                     f"묻지 말고 규칙 '{rule}' 절의 ①~④ 형식으로 한 답에 함께 낸다. 이미 조회했으면 무시한다.")
    if new:
        parts.append("이 응답을 해석·설명·보고할 때 아래 광고 성과 도메인 규칙을 지킨다.")
        parts.extend(f"## {title}\n{body}" for title, body in new)
        record |= {title for title, _ in new}
    if record:
        save_sent(state, sent | record)
    return f"{TAG}\n" + "\n\n".join(parts) if parts else None


def main():
    try:
        data = json.load(sys.stdin)
        if data.get("hook_event_name") == "SessionStart":
            forget_session(data)
            return
        context = build_context(data)
    except Exception:  # noqa: BLE001 — 훅 실패가 도구 응답을 막으면 안 된다
        return
    if not context:
        return
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

"""저장 훅 응답 읽기 — 이 폴더가 플러그인마다 다른 ``prepare_kit``·``report_kit`` 없이 동작하게 하는 최소 부품.

laighthouse-plugin(``laighthouse-analytics-prod``)과 laighthouse-plugin-agency(``laighthouse-agency``)가
``shared/assets/external_context/``를 같은 파일로 나눠 쓴다. 저장 위치·형식은 두 플러그인의
``hooks/save_responses.py``가 같다: ``<tmp>/laighthouse_mcp_responses/<session>/<ms>_<도구>.json``에
``{tool_name, tool_input, saved_at, response}``.

- :func:`response_text`: 레코드 → 응답 본문(호스트가 잘라 둔 파일·``{"result": …}`` 래퍼 처리).
- :func:`work_dir`: 보고서 중간 JSON을 둘 작업 폴더.
- :func:`daily_ad_envelope`: weather-impact가 겹쳐 그릴 ``get_ad_performance``(day, group_by media) 응답.
- :func:`metric_keys`: 지표 이름 → 클릭·전환·매출 키(laighthouse-plugin ``report_kit`` 역할 규칙과 같다).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time

ROOT = os.path.join(tempfile.gettempdir(), "laighthouse_mcp_responses")
WORK_ROOT = os.path.join(tempfile.gettempdir(), "laighthouse_prepare")
MAX_AGE = 24 * 3600
SPILL_RE = re.compile(r"Output has been saved to (\S+?)\.?\s*$", re.M)

ROLE_CANDIDATES = {
    "click": ["클릭", "click", "clicks"],
    "revenue": ["매출", "revenue"],
    "conversion": ["전환", "conversion", "conversions", "구매", "구매수", "purchase", "purchases"],
}


def _unwrap(text):
    """Cowork/Desktop의 {"result": "<본문>"} 래퍼와 [{"type":"text",…}] 블록 리스트를 벗긴다."""
    for _ in range(3):
        if not isinstance(text, str) or not text.lstrip().startswith(("{", "[")):
            return text
        try:
            obj = json.loads(text)
        except ValueError:
            return text
        if isinstance(obj, dict) and "result" in obj and len(obj) == 1:
            inner = obj["result"]
            text = inner if isinstance(inner, str) else json.dumps(inner, ensure_ascii=False)
        elif isinstance(obj, list) and obj and all(isinstance(b, dict) and "text" in b for b in obj):
            text = "\n".join(b["text"] for b in obj)
        else:
            return text
    return text


def response_text(rec: dict) -> str:
    text = rec.get("response")
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
    return _unwrap(text)


def work_dir(brand: str, skill: str, label: str) -> str:
    path = os.path.join(WORK_ROOT, re.sub(r"[^\w.-]", "_", f"{brand}_{skill}_{label}"))
    os.makedirs(path, exist_ok=True)
    return path


def _is_daily_media_call(ti: dict, start: str, end: str) -> bool:
    """day grain·group_by ["media"]·지표 생략·필터·day_offset 없는 호출만(전체 매체 일별 합에 쓴다)."""
    return (
        str(ti.get("start_date") or "")[:10] == start
        and str(ti.get("end_date") or "")[:10] == end
        and (ti.get("time_grain") or "day") == "day"
        and [str(x) for x in ti.get("group_by") or []] == ["media"]
        and ti.get("day_offset") in (None, "")
        and ti.get("metrics") is None
        and not any(v for v in (ti.get("filters") or {}).values())
    )


def daily_ad_envelope(brand: str, start: str, end: str) -> dict | None:
    """``ROOT`` 아래 이 브랜드·기간의 가장 최근 ``get_ad_performance`` 응답 봉투. 없거나 오류면 None."""
    hits = []
    now = time.time()
    for dirpath, _, names in os.walk(ROOT):
        for name in names:
            if not name.endswith("_get_ad_performance.json"):
                continue
            path = os.path.join(dirpath, name)
            try:
                if now - os.path.getmtime(path) > MAX_AGE:
                    continue
                with open(path, encoding="utf-8") as f:
                    rec = json.load(f)
            except (OSError, ValueError):
                continue
            ti = rec.get("tool_input") or {}
            if isinstance(ti, dict) and ti.get("brand_name") == brand and _is_daily_media_call(ti, start, end):
                hits.append((rec.get("saved_at") or 0, path, rec))
    if not hits:
        return None
    try:
        env = json.loads(response_text(max(hits, key=lambda h: h[:2])[2]))
    except ValueError:
        return None
    return env if isinstance(env, dict) and isinstance(env.get("rows"), list) else None


def _resolve(role: str, metrics: list, prefer_suffix: str | None = None) -> str | None:
    """완전 일치(대소문자 무시) 우선, 없으면 '<후보>_' 접두 일치가 하나일 때만. 여럿이면 매출 접미어로 고른다."""
    lower = {m.lower(): m for m in metrics}
    for cand in ROLE_CANDIDATES[role]:
        if cand.lower() in lower:
            return lower[cand.lower()]
    for cand in ROLE_CANDIDATES[role]:
        hits = [m for m in metrics if m.lower().startswith(cand.lower() + "_")]
        if len(hits) == 1:
            return hits[0]
        if prefer_suffix:
            same = [h for h in hits if h[len(cand):] == prefer_suffix]
            if len(same) == 1:
                return same[0]
        if hits:
            return None
    return None


def metric_keys(metrics: list) -> dict:
    """{역할: 지표 키} — 클릭·매출·전환. 전환은 매출과 같은 접미어(예: 매출_AB ↔ 전환_AB)를 우선한다."""
    keys = {r: k for r in ("click", "revenue") if (k := _resolve(r, metrics))}
    suffix = None
    for cand in ROLE_CANDIDATES["revenue"]:
        if keys.get("revenue", "").lower().startswith(cand.lower()):
            suffix = keys["revenue"][len(cand):]
            break
    if conv := _resolve("conversion", metrics, suffix or None):
        keys["conversion"] = conv
    return keys

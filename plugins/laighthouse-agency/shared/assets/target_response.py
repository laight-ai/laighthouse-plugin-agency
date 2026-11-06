"""get_target_progress_v2 응답 읽기 — 빌더가 공유한다(표준 라이브러리만).

- `target_text`  get_target_progress_v2 응답(JSON 객체·옛 서버 markdown·래퍼) → 목표 원문(목표 파서가 읽는 markdown)
"""
import json


_TP_TABLES = (("summary", ("metric", "target", "actual", "progress_ratio")),
              ("scopes", ("media", "campaign_name", "included", "metric", "target", "actual", "achievement")),
              ("fees", ("media", "fee_mode", "rate")))


def target_text(raw):
    """get_target_progress_v2 응답 → 목표 원문(markdown).
    JSON 응답(status 키가 있는 객체 또는 그 JSON 문자열)은 옛 서버가 같은 내용으로 내던 원문으로 바꾸고(status가 ok가 아니면 message 한 줄
    — 목표 없음), 그 밖(옛 서버 markdown·목표 없음 한 줄)은 그대로 둔다. {"result": …}·content 블록 래퍼는 먼저 벗긴다."""
    v = _target_payload(raw)
    if isinstance(v, dict) and "status" in v:
        return _target_markdown(v)
    return v if isinstance(v, str) else ""


def _target_payload(v):
    """래퍼를 벗긴 응답 — 새 형식 객체(dict) 또는 문자열. JSON 문자열은 읽어서 보고(새 형식도 래퍼도 아니면 받은 문자열 그대로),
    {"result": x}·{"content": x}는 x, MCP content 블록 [{"type": "text", "text"}]는 text를 이은 것."""
    if isinstance(v, str):
        s = v.strip()
        try:
            obj = json.loads(s) if s[:1] in ("{", "[") else None
        except ValueError:
            obj = None
        out = v if obj is None else _target_payload(obj)
        return out if isinstance(out, str) or (isinstance(out, dict) and "status" in out) else v
    if isinstance(v, list):
        texts = [b["text"] for b in v if isinstance(b, dict) and isinstance(b.get("text"), str)]
        return _target_payload("\n".join(texts)) if texts else v
    if isinstance(v, dict) and "status" not in v:
        for k in ("content", "result"):
            if k in v:
                return _target_payload(v[k])
    return v


def _md_cell(v):
    """JSON 값 → 옛 서버 표의 칸: null → '-', true/false → Y/N, 그 밖은 서버가 찍던 그대로(이름은 공백 정리·'|' 이스케이프 — 서버와 같다)."""
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "Y" if v else "N"
    return " ".join(str(v).split()).replace("|", r"\|")


def _target_markdown(obj):
    """새 형식 객체 → 옛 서버 원문(머리 줄, summary·scopes 표, fees가 있으면 셋째 표). status가 ok가 아니면 message 한 줄."""
    if obj.get("status") != "ok":
        return str(obj.get("message") or "")
    lines = [f"month: {obj.get('month')}", f"as_of_date: {obj.get('as_of_date')}", f"media: {obj.get('media') or 'all'}",
             f"fee_basis: {obj.get('fee_basis')}"]
    for key, cols in _TP_TABLES:
        rows = obj.get(key) or []
        if rows or key != "fees":
            lines += ["", "| " + " | ".join(cols) + " |", "|" + " --- |" * len(cols),
                      *("| " + " | ".join(_md_cell(r.get(c)) for c in cols) + " |" for r in rows)]
    return "\n".join(lines)

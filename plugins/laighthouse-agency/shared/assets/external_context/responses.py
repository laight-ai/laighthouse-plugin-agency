"""저장 훅 응답 리더 — MCP ``get_external_context`` 응답을 집계 코드가 부르는 조회 객체로 바꾼다.

저장 훅(``hooks/save_responses.py``)이 남긴 응답 하나를 읽고, 집계 코드(``search_aggregate``·``buzz``·
``search_db.quality``)가 부르는 메서드를 응답 키로 채운다. 응답 모양은 laighthouse-elt
``external_context/serving.py``다.

- :func:`find_response`: ``tool_input``의 ``brand_name``·``kind``·``start_date``·``end_date``가 같은
  가장 최근 파일.
- :func:`tenant_of`: 응답 ``brands`` → 테넌트 dict(``group_name``·``own``·``keywords``·
  ``brand_query``·``collect_search``).
- :class:`SearchData`·:class:`BuzzData`: 검색량·뉴스/블로그 조회 메서드.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime

import saved
import search_db
from buzz import Doc

TOOL = "get_external_context"


def records(root: str, max_age: float | None = None):
    """``root`` 아래(세션 폴더 한 단계 포함)의 응답 레코드. ``max_age``초보다 오래된 파일은 뺀다."""
    now = time.time()
    for dirpath, _, names in os.walk(root):
        for name in names:
            if not name.endswith(f"_{TOOL}.json"):
                continue
            path = os.path.join(dirpath, name)
            try:
                if max_age is not None and now - os.path.getmtime(path) > max_age:
                    continue
                with open(path, encoding="utf-8") as f:
                    rec = json.load(f)
            except (OSError, ValueError):
                continue
            rec["_path"] = path
            yield rec


def _input(rec: dict, key: str) -> str:
    value = str((rec.get("tool_input") or {}).get(key) or "")
    return value[:10] if key.endswith("_date") else value


def find_response(brand: str, kind: str, start: str, end: str, root: str | None = None) -> dict:
    """조건이 같은 가장 최근 응답(dict). 없으면 LookupError, 응답이 오류 문자열이면 ValueError."""
    want = {"brand_name": brand, "kind": kind, "start_date": start, "end_date": end}
    hits = [
        r
        for r in (records(root) if root else records(saved.ROOT, saved.MAX_AGE))
        if all(_input(r, k) == v for k, v in want.items())
    ]
    if not hits:
        raise LookupError(
            f"저장된 {TOOL} 응답이 없습니다: brand_name={brand}, kind={kind}, "
            f"start_date={start}, end_date={end}"
        )
    rec = max(hits, key=lambda r: (r.get("saved_at") or 0, r["_path"]))
    text = saved.response_text(rec)
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, dict) or "start" not in data:
        raise ValueError(f"{TOOL} 응답이 데이터가 아닙니다: {str(text).strip()[:300]}")
    return data


def tenant_of(resp: dict, range_start: date | None = None) -> dict:
    brands = [
        {
            "group_name": b["name"],
            "own": b["role"] == "own",
            "keywords": b["keywords"],
            "brand_query": b.get("brand_query"),
            "collect_search": b.get("collect_search", True),
        }
        for b in resp["brands"]
        # 검색량 응답에는 collect_search=false 회사의 키워드가 없다(ELT는 회사 단위로 거른다).
        if resp.get("kind") != "search_volume" or b.get("collect_search", True)
    ]
    return {
        "tenant_id": resp.get("tenant"),
        "name": next((b["group_name"] for b in brands if b["own"]), brands[0]["group_name"]),
        "brands": brands,
        "collect_search": any(b["collect_search"] for b in brands),
        "range_start": range_start,
    }


def _d(text: str) -> date:
    return date.fromisoformat(text)


def _in(d: date, start: date, end: date) -> bool:
    return start <= d <= end


class SearchData:
    """``kind=search_volume`` 응답 → 검색량 조회 메서드."""

    def __init__(self, resp: dict) -> None:
        self.cfg = {
            "anchor_keyword": resp["anchor_keyword"],
            "window_lag_days": int(resp["window_lag_days"]),
        }
        self.rows = [
            (r["keyword"], _d(r["period"]), r["est_volume"], r["request_id"]) for r in resp["rows"]
        ]
        self._requests = {r["id"]: r for r in resp["requests"]}
        self._snapshot_date = _d(resp["snapshot_date"]) if resp.get("snapshot_date") else None
        self._snapshots = {s["keyword"]: s for s in resp["snapshots"]}
        self._last_period = _d(resp["last_period"]) if resp.get("last_period") else None
        self._first = {k: _d(v) for k, v in resp["first_periods"].items()}
        self._covering = set(resp["covering_keywords"])
        self._end = _d(resp["end"])

    def _rows(self, keywords: list[str], start: date, end: date):
        ks = set(keywords)
        return [r for r in self.rows if r[0] in ks and _in(r[1], start, end)]

    def points(self, keywords: list[str], start: date, end: date) -> list[tuple]:
        return self._rows(keywords, start, end)

    def coverage(self, keywords: list[str], start: date, end: date) -> dict[str, int]:
        out: dict[str, int] = {}
        for k, *_ in self._rows(keywords, start, end):
            out[k] = out.get(k, 0) + 1
        return out

    def window_sum(self, keywords: list[str], start: date, end: date) -> dict[str, float]:
        out: dict[str, float] = {}
        for k, _, v, _ in self._rows(keywords, start, end):
            out[k] = out.get(k, 0.0) + float(v)
        return out

    def last_period(self, keywords: list[str]) -> date | None:
        return self._last_period

    def first_periods(self, keywords: list[str]) -> dict[str, date]:
        return {k: self._first[k] for k in keywords if k in self._first}

    def requests(self, ids: list[int]) -> list[dict]:
        out = []
        for i in sorted(ids):
            r = self._requests[i]
            out.append(
                {
                    "id": i,
                    "start": r["start_date"],
                    "end": r["end_date"],
                    "requested_at": r["requested_at"],
                }
            )
        return out

    def snapshot(self, keywords: list[str], anchor: str):
        if self._snapshot_date is None:
            return None, {}
        return self._snapshot_date, {
            k: search_db.tool_total(s["pc_count"], s["mobile_count"])
            for k, s in self._snapshots.items()
            if k in keywords
        }

    def covering_keywords(self, target: date) -> set[str]:
        if target != self._end:
            raise ValueError(f"검색량 응답의 end({self._end})와 기준일({target})이 다릅니다.")
        return self._covering


class BuzzData:
    """``kind=news|blog`` 응답 → 뉴스·블로그 조회 메서드. 문서는 서버가 거른 센 글만 있다."""

    def __init__(self, resp: dict) -> None:
        self.kind = resp["kind"]
        self._docs = [
            Doc(
                d["query"],
                d["link"],
                d["title"],
                bool(d["snippet_match"]),
                _d(d["published_date"]),
                datetime.fromisoformat(d["published_at"]) if d.get("published_at") else None,
                d.get("author"),
            )
            for d in resp["documents"]
        ]
        self._coverage = {
            (c["query"], _d(c["published_date"])): bool(c["is_complete"]) for c in resp["coverage"]
        }
        self._fetch = {f["query"]: f for f in resp["fetch_info"]}

    def docs(self, queries: list[str], start: date, end: date) -> list[Doc]:
        qs = set(queries)
        return [d for d in self._docs if d.query in qs and _in(d.published_date, start, end)]

    def coverage(self, queries: list[str], start: date, end: date) -> dict[tuple[str, date], bool]:
        qs = set(queries)
        return {k: v for k, v in self._coverage.items() if k[0] in qs and _in(k[1], start, end)}

    def fetch_info(self, queries: list[str]) -> dict[str, dict]:
        return {
            q: {"last_fetched_at": f["latest"], "first_date": f["first_date"]}
            for q, f in self._fetch.items()
            if q in queries and f.get("latest")
        }


def data_of(resp: dict):
    return SearchData(resp) if resp["kind"] == "search_volume" else BuzzData(resp)


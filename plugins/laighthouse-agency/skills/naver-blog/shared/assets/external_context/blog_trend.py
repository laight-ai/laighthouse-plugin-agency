"""블로그 언급량 집계 — naver-blog skill의 소스.

조회 객체(kind=blog)를 읽어 브랜드별 언급량과 급증일
글을 JSON으로 낸다. 브랜드 대표 검색어·고유 링크 집계·집계 불완전·급증 판정은 `buzz.py`, 기간
통계는 `trend_core.py` docstring을 따른다.

블로그 규칙
- 건수 = 제목 일치 글: 그 글을 찾은 검색어가 제목에 띄어쓰기까지 그대로 있는 글의 고유 링크 수.
  판정은 laighthouse-elt 수집기가 하고(``title_match``) 응답에는 그런 글만 온다. 블로그 검색은
  합성어를 쪼개고 따옴표를 무시해 제목·요약 일치만으로는 호텔 후기 같은 부수 언급이 섞이기 때문이다.
- 급증 = 제목 일치가 같은 요일 유형 기준선의 2배 이상이고 10건 이상(가설값).
- 급증일 글 = 그날 글에서 최신순, 같은 블로거는 1건만.

JSON은 `buzz.build`와 같고 글에 `blogger`가 더해진다.
"""

from __future__ import annotations

from datetime import date

import buzz

KIND = "blog"
SPIKE_RATIO, SPIKE_MIN = 2.0, 10
FOOTNOTES = [
    "블로그 검색은 합성어를 쪼개고 따옴표를 무시하므로, 건수는 브랜드 검색어가 제목에 그대로 있는 "
    "글의 고유 건수이며 썸트렌드 언급량과는 비교하지 않습니다.",
    "'집계 불완전' 표시가 있는 날은 1,000건 한도에 걸려 전부 받지 못한 날이며 합산에서 "
    "제외했습니다.",
]


def pick_posts(docs: list[buzz.Doc], queries: list[str], limit: int) -> list[dict]:
    """급증일 글: 링크로 합친 뒤 최신순, 같은 블로거는 1건만."""
    merged = buzz.merge_by_link(
        docs,
        lambda doc: {"blogger": (doc.author or "").strip()},
    )
    ranked = sorted(
        merged,
        key=lambda r: (r["date"], r["published_at"], r["link"]),
        reverse=True,
    )
    out, seen = [], set()
    for r in ranked:
        if r["blogger"] and r["blogger"] in seen:
            continue
        seen.add(r["blogger"])
        out.append(
            {
                "title": r["title"],
                "link": r["link"],
                "date": r["date"].isoformat(),
                "duplicates": 1,
                "snippet_match": r["snippet_match"],
                "blogger": r["blogger"] or None,
            }
        )
        if len(out) == limit:
            break
    return out


SPEC = buzz.BuzzSpec(
    kind=KIND,
    spike_ratio=SPIKE_RATIO,
    spike_min=SPIKE_MIN,
    count_rule="제목 일치 글 고유 링크 수",
    footnotes=FOOTNOTES,
    counted=lambda doc, queries: True,
    spike_doc=lambda doc, queries: True,
    pick=pick_posts,
)


def build(tenant: dict, target: date, db) -> dict:
    return buzz.build(tenant, target, db, SPEC)
